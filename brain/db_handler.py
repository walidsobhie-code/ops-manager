import os
import json
import time
import sqlite3
import logging
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Local fallback queue. If Supabase is unreachable, save_report writes here
# so the report is never lost. flush_pending() can be called periodically to
# replay. The HF container has ephemeral disk, so this only protects against
# transient outages, not full container loss — that's acceptable.
_DEFAULT_FALLBACK_PATH = os.getenv(
    "OPS_FALLBACK_DB", str(Path(__file__).parent.parent / ".ops_fallback.db")
)


class StoreDB:
    def __init__(self, url: str, key: str, fallback_path: str = _DEFAULT_FALLBACK_PATH):
        if not url or not key:
            raise ValueError("StoreDB: Supabase url and key are required")
        self.supabase: Client = create_client(url, key)
        self._fb_path = fallback_path
        self._fb_lock = threading.Lock()
        self._init_fallback()

    # ─── Fallback queue (SQLite WAL) ────────────────────────────────────────────
    def _init_fallback(self) -> None:
        try:
            with sqlite3.connect(self._fb_path) as conn:
                # WAL = crash-safe + concurrent readers
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_reports (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        payload     TEXT    NOT NULL,
                        attempts    INTEGER NOT NULL DEFAULT 0,
                        last_error  TEXT,
                        created_at  REAL    NOT NULL
                    );
                    """
                )
                conn.commit()
        except Exception as e:
            logger.warning("StoreDB: could not init fallback queue at %s: %s", self._fb_path, e)

    def _queue_pending(self, payload: Dict[str, Any], last_error: str) -> None:
        try:
            with self._fb_lock, sqlite3.connect(self._fb_path) as conn:
                conn.execute(
                    "INSERT INTO pending_reports (payload, attempts, last_error, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (json.dumps(payload, default=str), 99, last_error[:500], time.time()),
                )
                conn.commit()
        except Exception as e:
            logger.error("StoreDB: failed to queue pending report: %s", e)

    def flush_pending(self, max_items: int = 50) -> int:
        """
        Try to replay queued reports into Supabase. Returns number successfully flushed.
        Safe to call periodically (e.g. hourly cron / health endpoint).
        """
        flushed = 0
        try:
            with self._fb_lock, sqlite3.connect(self._fb_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, payload FROM pending_reports ORDER BY id ASC LIMIT ?",
                    (max_items,),
                ).fetchall()
        except Exception as e:
            logger.warning("StoreDB.flush_pending: could not read queue: %s", e)
            return 0

        for row in rows:
            try:
                payload = json.loads(row["payload"])
                self.supabase.table("store_reports").insert(payload).execute()
                with self._fb_lock, sqlite3.connect(self._fb_path) as conn:
                    conn.execute("DELETE FROM pending_reports WHERE id = ?", (row["id"],))
                    conn.commit()
                flushed += 1
            except Exception as e:
                logger.warning("StoreDB.flush_pending: replay failed for id=%s: %s", row["id"], e)
                with self._fb_lock, sqlite3.connect(self._fb_path) as conn:
                    conn.execute(
                        "UPDATE pending_reports SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                        (str(e)[:500], row["id"]),
                    )
                    conn.commit()
        return flushed

    def pending_count(self) -> int:
        try:
            with self._fb_lock, sqlite3.connect(self._fb_path) as conn:
                cur = conn.execute("SELECT COUNT(*) FROM pending_reports")
                return int(cur.fetchone()[0])
        except Exception:
            return -1

    # ─── Public API ─────────────────────────────────────────────────────────────
    def save_report(self, report_data: Dict[str, Any]) -> Any:
        """
        Saves a parsed report to the 'store_reports' table.
        On Supabase failure, queues the report locally so it's not lost.
        """
        data = {
            "store_id": report_data.get("store_id"),
            "sales": (report_data.get("metrics") or {}).get("sales"),
            "inventory_status": (report_data.get("metrics") or {}).get("inventory_status"),
            "staffing": (report_data.get("metrics") or {}).get("staffing"),
            "issues": report_data.get("issues") or [],
            "analysis": report_data.get("analysis"),
            "actions": report_data.get("actions_needed") or [],
            "report_date": time.strftime('%Y-%m-%d') # Force ISO date for Dashboard sync
        }
        try:
            return self.supabase.table("store_reports").insert(data).execute()
        except Exception as e:
            logger.error("StoreDB.save_report: Supabase insert failed, queuing locally: %s", e)
            self._queue_pending(data, str(e))
            # Re-raise so the caller (Telegram handler) can decide UX.
            raise

    def get_latest_reports(self, limit: int = 20) -> Any:
        return (
            self.supabase.table("store_reports")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

    def get_all_store_summaries(self) -> Any:
        return self.supabase.table("store_reports").select("*").execute()

    def get_recent_operator_actions(self, limit: int = 50) -> Any:
        """For the dashboard's operator log panel."""
        return (
            self.supabase.table("operator_logs")
            .select("*")
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )

    def log_operator_action(self, store_id: str, action: str, notes: str) -> Any:
        """
        Logs a manual operator correction/intervention to a separate audit table.
        """
        data = {
            "store_id": store_id,
            "action_type": action,
            "notes": notes,
            "timestamp": "now()",
        }
        return self.supabase.table("operator_logs").insert(data).execute()

    def save_bulk_reports(self, reports: List[Dict[str, Any]]) -> Any:
        """
        Saves a list of reports in a single batch operation.
        Essential for processing large Excel/CSV imports without hitting API limits.
        """
        try:
            return self.supabase.table("store_reports").insert(reports).execute()
        except Exception as e:
            logger.error("StoreDB.save_bulk_reports: Batch insert failed: %s", e)
            for report in reports:
                try:
                    self.save_report(report)
                except:
                    pass
            raise e
