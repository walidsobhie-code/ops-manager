import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import json

# ── Path bootstrap ──────────────────────────────────────────────────────────────
# Works whether launched from project root, dash/ folder, or Streamlit Cloud
_here = os.path.dirname(os.path.abspath(__file__))   # .../dash
_root = os.path.abspath(os.path.join(_here, '..'))   # project root
for _p in [_root, _here]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from brain.db_handler import StoreDB
from brain.ops_brain import OpsManagerAI

# ── Inline analytics fallback ───────────────────────────────────────────────────
# Defined here so the dashboard works even if brain/analytics.py has issues.
# If brain.analytics imports cleanly, these get overwritten — no conflict.
from datetime import datetime as _dt, timedelta as _td
from typing import Any as _Any, Dict as _Dict, List as _List

def analyze_store_status(current_value: float, baseline: float) -> str:
    if baseline <= 0: return "Green"
    r = current_value / baseline
    return "Green" if r >= 0.90 else ("Yellow" if r >= 0.70 else "Red")

def calculate_7day_baseline(store_reports: _List[_Dict[str, _Any]]) -> float:
    if not store_reports: return 0.0
    parsed = []
    for r in store_reports:
        try:
            d = r.get("report_date")
            if isinstance(d, str): d = _dt.fromisoformat(d.split("T")[0])
            s = float(r.get("sales") or 0)
            parsed.append((d, s))
        except: continue
    if not parsed: return 0.0
    most_recent = max(d for d, _ in parsed)
    cutoff = most_recent - _td(days=6)
    recent = [s for d, s in parsed if d >= cutoff and s > 0]
    if not recent:
        all_s = [s for _, s in parsed if s > 0]
        return round(sum(all_s) / len(all_s), 2) if all_s else 0.0
    return round(sum(recent) / len(recent), 2)

def identify_red_zone_stores(today_reports, baselines, threshold_pct=30.0):
    out = []
    for r in today_reports:
        sid = r.get("store_id")
        if not sid: continue
        cur = float(r.get("sales") or 0)
        base = baselines.get(sid, 0.0)
        if base <= 0: continue
        drop = (base - cur) / base * 100
        if drop >= threshold_pct:
            out.append({"store_id": sid, "current_value": round(cur,2),
                        "baseline": round(base,2), "drop_pct": round(drop,1)})
    return sorted(out, key=lambda x: x["drop_pct"], reverse=True)

def generate_fleet_summary_prompt(recent_reports):
    if not recent_reports:
        return ('{"fleet_health_score":0,"strategic_recommendation":"No data.",'
                '"critical_alerts":[],"top_performer":"","at_risk_stores":[]}')
    lines = []
    for r in recent_reports:
        lines.append(f"  • {r.get('store_id')}: sales={r.get('sales')}, "
                     f"inv={r.get('inventory_status')}, staff={r.get('staffing')}, "
                     f"note={r.get('analysis')}")
    return f"""You are the AI ops brain for a multi-store retail fleet.
Analyse this data and return ONLY valid JSON — no markdown, no preamble:
{chr(10).join(lines)}
Schema: {{"fleet_health_score":<0-100>,"strategic_recommendation":"<one sentence>",
"critical_alerts":["<alert>"],"top_performer":"<store_id>","at_risk_stores":["<store_id>"]}}"""

def calculate_fleet_kpis(all_reports):
    if not all_reports:
        return {"total_sales":0.0,"avg_sales":0.0,"store_count":0,
                "report_count":0,"top_store":"—","top_sales":0.0}
    store_totals = {}
    for r in all_reports:
        sid = r.get("store_id","Unknown")
        store_totals[sid] = store_totals.get(sid,0.0) + float(r.get("sales") or 0)
    total = sum(store_totals.values())
    cnt   = len(store_totals)
    top   = max(store_totals, key=store_totals.get) if store_totals else "—"
    return {"total_sales":round(total,2),"avg_sales":round(total/cnt,2) if cnt else 0,
            "store_count":cnt,"report_count":len(all_reports),
            "top_store":top,"top_sales":round(store_totals.get(top,0),2)}

# Try to import the proper module — overrides the stubs above if successful
try:
    from brain.analytics import (
        analyze_store_status,
        calculate_7day_baseline,
        identify_red_zone_stores,
        generate_fleet_summary_prompt,
        calculate_fleet_kpis,
    )
except Exception as _analytics_err:
    import logging as _log
    _log.getLogger(__name__).warning(
        "brain.analytics import failed (%s) — using inline fallbacks", _analytics_err
    )

# ─── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OPS NEXUS — Command",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Design System ──────────────────────────────────────────────────────────────
# Color palette: high contrast, corporate-grade
# Background: near-black navy, not pure black (easier on eyes, more depth)
# Text: warm white #F0F2F8 on dark (contrast ratio ~14:1)
# Accent Blue: #4F8EF7 — brighter, more readable than #3b82f6
# Green: #22C87A  Amber: #F5A623  Red: #F5454A  Purple: #A78BFA

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=Bricolage+Grotesque:wght@400;500;600;700;800&family=DM+Sans:wght@300;400;500;600&display=swap');

/* ════════════════════════════════════════════════
   DESIGN TOKENS
════════════════════════════════════════════════ */
:root {
    --bg-base:    #080C16;
    --bg-surface: #0D1221;
    --bg-raised:  #131828;
    --bg-overlay: #1A2035;

    --border-subtle: rgba(255,255,255,0.06);
    --border-mid:    rgba(255,255,255,0.10);
    --border-strong: rgba(255,255,255,0.18);

    --text-primary:   #F0F2F8;
    --text-secondary: #9BA3C0;
    --text-muted:     #4E577A;
    --text-dim:       #2E3555;

    --blue:   #4F8EF7;
    --blue-dim: rgba(79,142,247,0.12);
    --blue-border: rgba(79,142,247,0.28);

    --green:   #22C87A;
    --green-dim: rgba(34,200,122,0.12);
    --green-border: rgba(34,200,122,0.28);

    --amber:   #F5A623;
    --amber-dim: rgba(245,166,35,0.12);
    --amber-border: rgba(245,166,35,0.28);

    --red:   #F5454A;
    --red-dim: rgba(245,69,74,0.12);
    --red-border: rgba(245,69,74,0.28);

    --purple:   #A78BFA;
    --purple-dim: rgba(167,139,250,0.12);
    --purple-border: rgba(167,139,250,0.28);

    --cyan: #38BDF8;
    --font-display: 'Bricolage Grotesque', sans-serif;
    --font-body:    'DM Sans', sans-serif;
    --font-mono:    'IBM Plex Mono', monospace;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --radius-xl: 18px;
}

/* ════════════════════════════════════════════════
   GLOBAL RESET
════════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; }

html, body, .stApp {
    background-color: var(--bg-base) !important;
    color: var(--text-primary);
    font-family: var(--font-body);
}
#MainMenu, footer, header { visibility: hidden; }

.block-container {
    padding: clamp(1rem,3vw,2.25rem) clamp(1rem,3vw,2.5rem) 5rem !important;
    max-width: 100% !important;
}

::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg-surface); }
::-webkit-scrollbar-thumb { background: var(--bg-overlay); border-radius: 99px; }

/* ════════════════════════════════════════════════
   TOPBAR
════════════════════════════════════════════════ */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    padding-bottom: clamp(16px,3vw,26px);
    border-bottom: 1px solid var(--border-subtle);
    margin-bottom: clamp(16px,3vw,26px);
}
.wordmark {
    display: flex;
    align-items: center;
    gap: 14px;
}
.logo-mark {
    width: clamp(32px,5vw,40px);
    height: clamp(32px,5vw,40px);
    background: var(--blue);
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-display);
    font-size: clamp(16px,3vw,20px);
    font-weight: 800;
    color: #fff;
    letter-spacing: -1px;
    flex-shrink: 0;
}
.logo-text-block { display: flex; flex-direction: column; gap: 1px; }
.logo-title {
    font-family: var(--font-display);
    font-size: clamp(16px,3vw,22px);
    font-weight: 800;
    color: var(--text-primary);
    letter-spacing: -0.4px;
    line-height: 1;
}
.logo-sub {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9.5px);
    color: var(--text-muted);
    letter-spacing: 2.5px;
    text-transform: uppercase;
}
.topbar-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.topbar-time {
    font-family: var(--font-mono);
    font-size: clamp(9px,1.4vw,10.5px);
    color: var(--text-muted);
    letter-spacing: 1px;
}
.live-pill {
    display: flex;
    align-items: center;
    gap: 7px;
    background: var(--green-dim);
    border: 1px solid var(--green-border);
    border-radius: 99px;
    padding: 5px 14px;
    font-family: var(--font-mono);
    font-size: clamp(9px,1.5vw,10px);
    color: var(--green);
    letter-spacing: 2px;
    text-transform: uppercase;
    white-space: nowrap;
}
.live-dot {
    width: 6px; height: 6px;
    background: var(--green);
    border-radius: 50%;
    flex-shrink: 0;
    animation: blink 1.8s ease-in-out infinite;
}
@keyframes blink {
    0%,100% { opacity:1; transform:scale(1); }
    50%      { opacity:0.3; transform:scale(0.6); }
}

/* ════════════════════════════════════════════════
   AI BANNER
════════════════════════════════════════════════ */
.ai-banner {
    background: linear-gradient(120deg, rgba(15,22,45,0.98) 0%, rgba(12,20,40,0.98) 100%);
    border: 1px solid var(--blue-border);
    border-radius: var(--radius-xl);
    padding: clamp(16px,3vw,24px);
    margin-bottom: clamp(16px,3vw,24px);
    position: relative;
    overflow: hidden;
}
.ai-banner::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent 0%, var(--blue) 40%, var(--purple) 70%, transparent 100%);
    opacity: 0.6;
}
.ai-header { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
.ai-title {
    font-family: var(--font-display);
    font-size: clamp(13px,2.5vw,16px);
    font-weight: 700;
    color: var(--blue);
}
.ai-score {
    font-family: var(--font-mono);
    font-size: clamp(9px,1.4vw,10px);
    color: var(--blue);
    background: var(--blue-dim);
    border: 1px solid var(--blue-border);
    border-radius: var(--radius-sm);
    padding: 3px 10px;
    letter-spacing: 1px;
}
.ai-rec {
    font-size: clamp(11px,1.8vw,13px);
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 10px;
    max-width: 900px;
}
.ai-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.ai-pill {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.3vw,9.5px);
    color: #FCA5A5;
    background: var(--red-dim);
    border: 1px solid var(--red-border);
    border-radius: var(--radius-sm);
    padding: 3px 10px;
    letter-spacing: 0.3px;
}

/* ════════════════════════════════════════════════
   DATE FILTER
════════════════════════════════════════════════ */
.filter-label {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.3vw,9px);
    color: var(--text-muted);
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-bottom: 8px;
}

/* ════════════════════════════════════════════════
   SECTION HEADER
════════════════════════════════════════════════ */
.section-hdr {
    display: flex; align-items: center; gap: 12px;
    margin: clamp(24px,4vw,36px) 0 clamp(14px,2.5vw,20px);
}
.section-line { height: 1px; flex: 1; background: var(--border-subtle); }
.section-label {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.3vw,9.5px);
    color: var(--text-muted);
    letter-spacing: 3px;
    text-transform: uppercase;
    white-space: nowrap;
}

/* ════════════════════════════════════════════════
   KPI CARDS
════════════════════════════════════════════════ */
.kpi-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: clamp(14px,2.5vw,22px);
    position: relative;
    overflow: hidden;
    height: 100%;
    min-height: 110px;
    transition: border-color 0.2s;
}
.kpi-card:hover { border-color: var(--border-mid); }
.kpi-top-line {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}
.kpi-left-bar {
    position: absolute; top: 0; left: 0; bottom: 0;
    width: 3px;
    border-radius: var(--radius-lg) 0 0 var(--radius-lg);
}
.kpi-card.kpi-blue  .kpi-top-line { background: var(--blue); }
.kpi-card.kpi-green .kpi-top-line { background: var(--green); }
.kpi-card.kpi-amber .kpi-top-line { background: var(--amber); }
.kpi-card.kpi-red   .kpi-top-line { background: var(--red); }
.kpi-card.kpi-purple .kpi-top-line { background: var(--purple); }
.kpi-card.kpi-cyan  .kpi-top-line { background: var(--cyan); }

.kpi-card.kpi-blue  .kpi-left-bar { background: var(--blue); }
.kpi-card.kpi-green .kpi-left-bar { background: var(--green); }
.kpi-card.kpi-amber .kpi-left-bar { background: var(--amber); }
.kpi-card.kpi-red   .kpi-left-bar { background: var(--red); }
.kpi-card.kpi-purple .kpi-left-bar { background: var(--purple); }
.kpi-card.kpi-cyan  .kpi-left-bar { background: var(--cyan); }

.kpi-icon-bg {
    position: absolute; top: 14px; right: 14px;
    font-size: clamp(22px,3.5vw,30px);
    opacity: 0.07;
    line-height: 1;
}
.kpi-label {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.3vw,9px);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 8px;
    padding-right: 30px;
}
.kpi-value {
    font-family: var(--font-display);
    font-size: clamp(22px,4vw,34px);
    font-weight: 800;
    color: var(--text-primary);
    line-height: 1;
    margin-bottom: 8px;
    word-break: break-all;
    letter-spacing: -0.5px;
}
.kpi-delta {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.3vw,9.5px);
    display: flex;
    align-items: center;
    gap: 4px;
}
.delta-up   { color: var(--green); }
.delta-down { color: var(--red); }
.delta-flat { color: var(--text-muted); }
.kpi-divider {
    height: 1px;
    background: var(--border-subtle);
    margin: 10px 0;
}
.kpi-sub {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-muted);
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 4px;
}
.kpi-sub span { color: var(--text-secondary); }

/* ════════════════════════════════════════════════
   STORE COMPARISON TABLE (DAY BY DAY)
════════════════════════════════════════════════ */
.comp-table-wrap {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border-subtle);
}
.comp-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-surface);
    font-family: var(--font-body);
}
.comp-table thead { position: sticky; top: 0; z-index: 2; }
.comp-table th {
    background: var(--bg-raised);
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    padding: 10px 14px;
    text-align: right;
    border-bottom: 1px solid var(--border-mid);
    white-space: nowrap;
}
.comp-table th:first-child { text-align: left; }
.comp-table td {
    font-size: clamp(11px,1.7vw,12.5px);
    color: var(--text-secondary);
    padding: 9px 14px;
    text-align: right;
    border-bottom: 1px solid var(--border-subtle);
    white-space: nowrap;
}
.comp-table td:first-child {
    font-family: var(--font-display);
    font-size: clamp(12px,1.8vw,13.5px);
    font-weight: 600;
    color: var(--text-primary);
    text-align: left;
}
.comp-table tr:last-child td { border-bottom: none; }
.comp-table tr:hover td { background: var(--bg-raised); }
.comp-table .best  { color: var(--green); font-weight: 600; }
.comp-table .worst { color: var(--red); }
.comp-table .cell-bar {
    position: relative;
    padding-bottom: 14px;
}
.cell-minibar {
    position: absolute;
    bottom: 4px; left: 14px; right: 14px;
    height: 2px;
    background: var(--border-subtle);
    border-radius: 99px;
}
.cell-minibar-fill {
    height: 2px;
    border-radius: 99px;
    background: var(--blue);
    transition: width 0.4s ease;
}

/* ════════════════════════════════════════════════
   STORE STATUS CARDS (NODE FEED)
════════════════════════════════════════════════ */
.node-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: clamp(14px,2.5vw,20px);
    margin-bottom: 14px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, transform 0.15s;
}
.node-card:hover { border-color: var(--border-mid); transform: translateY(-1px); }
.node-card-accent {
    position: absolute; top: 0; left: 0; bottom: 0;
    width: 3px;
}
.node-header {
    display: flex; justify-content: space-between;
    align-items: flex-start; margin-bottom: 14px; gap: 8px;
}
.node-name {
    font-family: var(--font-display);
    font-size: clamp(14px,2.5vw,17px);
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1;
}
.node-date {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-muted);
    margin-top: 3px;
}
.node-badge {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 4px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid;
    white-space: nowrap;
    font-weight: 500;
}
.badge-critical { color: var(--red);   background: var(--red-dim);   border-color: var(--red-border); }
.badge-growth   { color: var(--green); background: var(--green-dim); border-color: var(--green-border); }
.badge-stable   { color: var(--amber); background: var(--amber-dim); border-color: var(--amber-border); }

.node-metrics {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 8px;
    margin-bottom: 12px;
}
.node-metric {
    background: var(--bg-raised);
    border-radius: var(--radius-sm);
    padding: 8px 10px;
}
.node-metric-label {
    font-family: var(--font-mono);
    font-size: clamp(7px,1.1vw,8.5px);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin-bottom: 3px;
}
.node-metric-value {
    font-family: var(--font-display);
    font-size: clamp(13px,2.2vw,15px);
    font-weight: 700;
    color: var(--text-primary);
}
.node-analysis {
    font-size: clamp(11px,1.7vw,12.5px);
    color: var(--text-secondary);
    background: var(--bg-raised);
    border-radius: var(--radius-sm);
    padding: 9px 12px;
    line-height: 1.6;
    border-left: 2px solid;
}

/* ════════════════════════════════════════════════
   RED ZONE
════════════════════════════════════════════════ */
.rz-header {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.3vw,9px);
    color: var(--red);
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
}
.rz-card {
    background: linear-gradient(135deg, rgba(80,15,15,0.4), rgba(40,8,8,0.6));
    border: 1px solid var(--red-border);
    border-radius: var(--radius-md);
    padding: clamp(10px,2vw,14px);
    margin-bottom: 10px;
    transition: transform 0.15s;
}
.rz-card:hover { transform: translateX(3px); }
.rz-store {
    font-family: var(--font-display);
    font-size: clamp(13px,2vw,15px);
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 4px;
}
.rz-drop {
    font-family: var(--font-display);
    font-size: clamp(20px,3.5vw,26px);
    font-weight: 800;
    color: var(--red);
    line-height: 1;
    margin-bottom: 4px;
}
.rz-meta {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-muted);
}
.rz-ok {
    font-family: var(--font-mono);
    font-size: clamp(9px,1.4vw,10px);
    color: var(--green);
    letter-spacing: 1px;
}

/* ════════════════════════════════════════════════
   LEADERBOARD
════════════════════════════════════════════════ */
.lb-wrap {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    overflow: hidden;
}
.lb-table { width: 100%; border-collapse: collapse; }
.lb-table th {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    padding: 10px 14px;
    text-align: left;
    background: var(--bg-raised);
    border-bottom: 1px solid var(--border-mid);
}
.lb-table td {
    font-size: clamp(11px,1.7vw,13px);
    padding: 11px 14px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    vertical-align: middle;
}
.lb-table tr:last-child td { border-bottom: none; }
.lb-table tr:hover td { background: var(--bg-raised); }
.lb-store-name {
    font-family: var(--font-display);
    font-size: clamp(12px,1.8vw,14px);
    font-weight: 600;
    color: var(--text-primary);
}
.lb-bar-wrap {
    background: var(--bg-overlay);
    border-radius: 99px;
    height: 4px;
    width: 100%;
    margin-top: 5px;
    overflow: hidden;
}
.lb-bar-fill {
    height: 4px;
    border-radius: 99px;
    background: linear-gradient(90deg, var(--blue), var(--purple));
}
.lb-revenue { font-family: var(--font-display); font-weight: 700; color: var(--blue); }
.lb-share { font-family: var(--font-mono); font-size: clamp(9px,1.4vw,10px); color: var(--text-muted); }

/* ════════════════════════════════════════════════
   MINI STATS
════════════════════════════════════════════════ */
.mini-stat {
    background: var(--bg-raised);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: clamp(10px,2vw,14px);
}
.mini-stat-label {
    font-family: var(--font-mono);
    font-size: clamp(7px,1.2vw,8.5px);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 4px;
}
.mini-stat-value {
    font-family: var(--font-display);
    font-size: clamp(16px,3vw,22px);
    font-weight: 800;
    color: var(--text-primary);
}

/* ════════════════════════════════════════════════
   CHART LABEL
════════════════════════════════════════════════ */
.chart-label {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-muted);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 10px;
}

/* ════════════════════════════════════════════════
   STATUS ZONE PILLS
════════════════════════════════════════════════ */
.zone-pill {
    border-radius: var(--radius-md);
    padding: 12px 16px;
    text-align: center;
    border: 1px solid;
}
.zone-pill-label {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 4px;
}
.zone-pill-count {
    font-family: var(--font-display);
    font-size: clamp(22px,4vw,30px);
    font-weight: 800;
    line-height: 1;
}

/* ════════════════════════════════════════════════
   FOOTER
════════════════════════════════════════════════ */
.footer {
    margin-top: 48px;
    padding-top: 20px;
    border-top: 1px solid var(--border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}
.footer-text {
    font-family: var(--font-mono);
    font-size: clamp(8px,1.2vw,9px);
    color: var(--text-dim);
    letter-spacing: 2px;
    text-transform: uppercase;
}

/* ════════════════════════════════════════════════
   STREAMLIT WIDGET OVERRIDES
════════════════════════════════════════════════ */
.stSelectbox > div > div {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-mid) !important;
    border-radius: var(--radius-md) !important;
    color: var(--text-primary) !important;
    font-family: var(--font-body) !important;
    font-size: clamp(12px,2vw,13px) !important;
}
.stDateInput > div > div {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-mid) !important;
    border-radius: var(--radius-md) !important;
    color: var(--text-primary) !important;
    font-size: clamp(12px,2vw,13px) !important;
}
.stTextInput > div > div {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-mid) !important;
    border-radius: var(--radius-md) !important;
    color: var(--text-primary) !important;
    font-family: var(--font-mono) !important;
    font-size: clamp(11px,1.8vw,12px) !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: var(--bg-raised);
    border-radius: var(--radius-md);
    gap: 2px; padding: 4px;
    border: 1px solid var(--border-subtle);
    flex-wrap: wrap;
}
.stTabs [data-baseweb="tab"] {
    font-family: var(--font-mono);
    font-size: clamp(9px,1.4vw,10px);
    letter-spacing: 1px; text-transform: uppercase;
    color: var(--text-muted); background: transparent;
    border-radius: var(--radius-sm);
    padding: 7px 16px; min-height: 36px;
}
.stTabs [aria-selected="true"] {
    background: var(--blue-dim) !important;
    color: var(--blue) !important;
}
div[data-testid="stDataFrame"] {
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    overflow: hidden;
}
.stButton > button {
    background: var(--blue-dim) !important;
    border: 1px solid var(--blue-border) !important;
    color: var(--blue) !important;
    font-family: var(--font-mono) !important;
    font-size: clamp(10px,1.5vw,11px) !important;
    letter-spacing: 1px !important; text-transform: uppercase !important;
    border-radius: var(--radius-sm) !important;
    min-height: 38px !important; padding: 0 16px !important;
    transition: background 0.15s, border-color 0.15s !important;
}
.stButton > button:hover {
    background: rgba(79,142,247,0.2) !important;
    border-color: var(--blue) !important;
}

@media (max-width: 640px) {
    .logo-sub, .topbar-time { display: none; }
    .section-hdr { margin: 20px 0 14px; }
}
</style>
""", unsafe_allow_html=True)

# ─── Services ───────────────────────────────────────────────────────────────────
@st.cache_resource
def init_services():
    url    = os.getenv("SUPABASE_URL")
    key    = os.getenv("SUPABASE_KEY")
    ai_key = os.getenv("GROQ_API_KEY")
    return StoreDB(url=url, key=key), OpsManagerAI(api_key=ai_key)

db, ai = init_services()

# ─── Data ───────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_data():
    response = db.get_all_store_summaries()
    data = response.data if hasattr(response, 'data') else response
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df['sales'] = pd.to_numeric(df['sales'], errors='coerce').fillna(0)
    df['report_date'] = pd.to_datetime(df['report_date'])
    return df

df_raw = load_data()

if df_raw.empty:
    st.markdown("""
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
         height:60vh;gap:12px;text-align:center;padding:1rem;">
        <div style="font-family:var(--font-mono);color:var(--text-muted);letter-spacing:4px;font-size:10px;">
            TELEMETRY OFFLINE</div>
        <div style="font-family:var(--font-display);font-size:clamp(22px,5vw,36px);
             font-weight:800;color:var(--text-dim);">Awaiting Data Stream</div>
    </div>""", unsafe_allow_html=True)
    st.stop()

baselines = {}
for store in df_raw['store_id'].unique():
    store_reports = df_raw[df_raw['store_id'] == store].to_dict('records')
    baselines[store] = calculate_7day_baseline(store_reports)

# ─── TOPBAR ─────────────────────────────────────────────────────────────────────
now_str = datetime.now().strftime("%a %d %b %Y  ·  %H:%M")
st.markdown(f"""
<div class="topbar">
    <div class="wordmark">
        <div class="logo-mark">◈</div>
        <div class="logo-text-block">
            <div class="logo-title">OPS NEXUS</div>
            <div class="logo-sub">Sovereign Intelligence Console</div>
        </div>
    </div>
    <div class="topbar-right">
        <div class="topbar-time">{now_str}</div>
        <div class="live-pill"><div class="live-dot"></div>Live</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── AI BANNER ──────────────────────────────────────────────────────────────────
latest_date   = df_raw['report_date'].max()
recent_df_raw = df_raw[df_raw['report_date'] == latest_date]

try:
    prompt      = generate_fleet_summary_prompt(recent_df_raw.to_dict('records'))
    summary_raw = ai.client.chat.completions.create(
        model=ai.model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    ).choices[0].message.content
    summary = json.loads(summary_raw)
    score   = summary.get('fleet_health_score', '—')
    rec     = summary.get('strategic_recommendation', 'No data.')
    alerts  = summary.get('critical_alerts', [])
    pills   = "".join([f'<span class="ai-pill">🚨 {a}</span>' for a in alerts])
    st.markdown(f"""
    <div class="ai-banner">
        <div class="ai-header">
            <div class="ai-title">⚡ AI Fleet Intelligence</div>
            <span class="ai-score">Health Score {score} / 100</span>
        </div>
        <div class="ai-rec">{rec}</div>
        <div class="ai-pills">{pills}</div>
    </div>""", unsafe_allow_html=True)
except Exception:
    st.markdown("""
    <div class="ai-banner">
        <div class="ai-header"><div class="ai-title">⚡ AI Fleet Intelligence</div></div>
        <div class="ai-rec" style="color:var(--text-muted);">
            Connect <code>GROQ_API_KEY</code> to enable live AI fleet analysis.
        </div>
    </div>""", unsafe_allow_html=True)

# ─── DATE FILTER ────────────────────────────────────────────────────────────────
min_date = df_raw['report_date'].min().date()
max_date = df_raw['report_date'].max().date()

# Always clamp session state into [min_date, max_date] — guards against:
#   • stale values from a previous session
#   • values set by quick-filter buttons before data refreshes
#   • first-load with no prior state
if 'start_date' not in st.session_state:
    st.session_state.start_date = min_date
if 'end_date' not in st.session_state:
    st.session_state.end_date = max_date

# Hard clamp — value must always satisfy min_date <= value <= max_date
st.session_state.start_date = max(min_date, min(st.session_state.start_date, max_date))
st.session_state.end_date   = max(min_date, min(st.session_state.end_date,   max_date))
# Also ensure start <= end
if st.session_state.start_date > st.session_state.end_date:
    st.session_state.start_date = st.session_state.end_date

st.markdown('<div class="filter-label">Date Range Filter</div>', unsafe_allow_html=True)
dc1, dc2, dc3, dc4, dc5, dc6 = st.columns([2, 2, 1, 1, 1, 1])
with dc1:
    new_start = st.date_input(
        "From",
        value=st.session_state.start_date,
        min_value=min_date,
        max_value=max_date,
        label_visibility="collapsed",
    )
    st.session_state.start_date = max(min_date, min(new_start, max_date))
with dc2:
    new_end = st.date_input(
        "To",
        value=st.session_state.end_date,
        min_value=min_date,
        max_value=max_date,
        label_visibility="collapsed",
    )
    st.session_state.end_date = max(min_date, min(new_end, max_date))
with dc3:
    if st.button("7D"):
        st.session_state.start_date = max(min_date, max_date - timedelta(days=7))
        st.session_state.end_date   = max_date
        st.rerun()
with dc4:
    if st.button("30D"):
        st.session_state.start_date = max(min_date, max_date - timedelta(days=30))
        st.session_state.end_date   = max_date
        st.rerun()
with dc5:
    if st.button("90D"):
        st.session_state.start_date = max(min_date, max_date - timedelta(days=90))
        st.session_state.end_date   = max_date
        st.rerun()
with dc6:
    if st.button("ALL"):
        st.session_state.start_date = min_date
        st.session_state.end_date   = max_date
        st.rerun()

start_date = st.session_state.start_date
end_date   = st.session_state.end_date

# ─── FILTERED DATA ──────────────────────────────────────────────────────────────
df = df_raw[
    (df_raw['report_date'].dt.date >= start_date) &
    (df_raw['report_date'].dt.date <= end_date)
].copy()

df_latest = df.sort_values('report_date', ascending=False).drop_duplicates(subset=['store_id'])
period_days = max((end_date - start_date).days, 1)
df_prev = df_raw[
    (df_raw['report_date'].dt.date >= start_date - timedelta(days=period_days)) &
    (df_raw['report_date'].dt.date <  start_date)
]
df_prev_latest = df_prev.sort_values('report_date', ascending=False).drop_duplicates(subset=['store_id'])

def delta_html(curr, prev):
    if prev == 0: return '<span class="delta-flat">— no prior data</span>'
    pct = (curr - prev) / abs(prev) * 100
    arrow, cls = ("▲","delta-up") if pct >= 0 else ("▼","delta-down")
    return f'<span class="{cls}">{arrow} {abs(pct):.1f}%</span>'

# ─── KPI CALCULATIONS ───────────────────────────────────────────────────────────
total_sales     = df_latest['sales'].sum()
prev_sales      = df_prev_latest['sales'].sum() if not df_prev_latest.empty else 0
avg_sales       = df_latest['sales'].mean()     if not df_latest.empty else 0
prev_avg        = df_prev_latest['sales'].mean() if not df_prev_latest.empty else 0
store_count     = df_latest['store_id'].nunique()
crit_count      = len(df_latest[df_latest['analysis'].str.contains(
                      'decline|lower|drop|critical|alert', case=False, na=False)])
top_row         = df_latest.loc[df_latest['sales'].idxmax()] if not df_latest.empty else None
top_store_sales = top_row['sales']    if top_row is not None else 0
top_store_name  = top_row['store_id'] if top_row is not None else '—'
prev_top        = df_prev_latest['sales'].max() if not df_prev_latest.empty else 0
period_ttl      = df['sales'].sum()
daily_avg_net   = df.groupby('report_date')['sales'].sum().mean() if not df.empty else 0

# ─── PLOTLY THEME ───────────────────────────────────────────────────────────────
PT = dict(
    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    font=dict(family='DM Sans', color='#9BA3C0', size=11),
    margin=dict(l=6, r=6, t=32, b=6),
    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', zerolinecolor='rgba(255,255,255,0.05)',
               tickfont=dict(size=10, color='#9BA3C0')),
    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', zerolinecolor='rgba(255,255,255,0.05)',
               tickfont=dict(size=10, color='#9BA3C0')),
)
COLORS = ['#4F8EF7','#22C87A','#A78BFA','#F5A623','#F5454A','#38BDF8','#F472B6']
STORES = sorted(df['store_id'].unique().tolist())

# ════════════════════════════════════════════════════════════════════════════════
# TIER 1: KPI ROW (6 cards)
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="section-hdr">
  <div class="section-line"></div>
  <div class="section-label">Executive KPIs</div>
  <div class="section-line"></div>
</div>""", unsafe_allow_html=True)

k1,k2,k3,k4,k5,k6 = st.columns(6)

def kpi_card(col, label, val_fmt, delta_str, icon, color, sub_left="", sub_right=""):
    with col:
        sub_html = f"""
        <div class="kpi-divider"></div>
        <div class="kpi-sub">{sub_left}<span>{sub_right}</span></div>
        """ if sub_left or sub_right else ""
        st.markdown(f"""
        <div class="kpi-card {color}">
            <div class="kpi-top-line"></div>
            <div class="kpi-left-bar"></div>
            <div class="kpi-icon-bg">{icon}</div>
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{val_fmt}</div>
            <div class="kpi-delta">{delta_str}</div>
            {sub_html}
        </div>""", unsafe_allow_html=True)

kpi_card(k1, "Network Revenue",   f"${total_sales:,.0f}",
         delta_html(total_sales, prev_sales), "◈", "kpi-blue",
         "Period total", f"${period_ttl:,.0f}")

kpi_card(k2, "Avg Store Sales",   f"${avg_sales:,.0f}",
         delta_html(avg_sales, prev_avg), "⌀", "kpi-green",
         "Daily net avg", f"${daily_avg_net:,.0f}")

kpi_card(k3, "Active Stores",     str(store_count),
         '<span class="delta-flat">nodes reporting</span>', "◉", "kpi-purple",
         "Reports in period", str(len(df)))

kpi_card(k4, "Critical Alerts",   str(crit_count),
         f'<span class="{"delta-down" if crit_count>0 else "delta-up"}">{"⚠ Needs attention" if crit_count>0 else "✓ Fleet nominal"}</span>',
         "⚑", "kpi-red",
         "Of", f"{store_count} stores")

kpi_card(k5, f"Top — {top_store_name}", f"${top_store_sales:,.0f}",
         delta_html(top_store_sales, prev_top), "★", "kpi-amber",
         "vs fleet avg", f"+{top_store_sales - avg_sales:,.0f}" if avg_sales else "—")

kpi_card(k6, "Period Days",       str(period_days),
         f'<span class="delta-flat">{start_date.strftime("%b %d")} → {end_date.strftime("%b %d")}</span>',
         "📅", "kpi-cyan",
         "Start", start_date.strftime("%d %b %Y"))

# ════════════════════════════════════════════════════════════════════════════════
# TIER 2: STORE-BY-STORE DAY-BY-DAY COMPARISON TABLE
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="section-hdr">
  <div class="section-line"></div>
  <div class="section-label">Store × Day Sales Comparison</div>
  <div class="section-line"></div>
</div>""", unsafe_allow_html=True)

# Build pivot: rows = dates, cols = stores
pivot = df.pivot_table(
    index='report_date', columns='store_id', values='sales', aggfunc='sum'
).fillna(0).sort_index()
pivot.index = pivot.index.strftime('%a %d %b')

if not pivot.empty:
    stores_in_pivot = pivot.columns.tolist()
    date_labels     = pivot.index.tolist()
    col_max = pivot.max(axis=1)  # best store per day

    # Build header
    th_cells = "<th>Date</th>" + "".join(
        f"<th style='color:{COLORS[i % len(COLORS)]};'>{s}</th>"
        for i, s in enumerate(stores_in_pivot)
    ) + "<th>Best Store</th><th>Day Total</th>"

    # ── Fully inlined table (no CSS class deps — Streamlit strips mid-page classes) ──
    TD_BASE  = "font-size:clamp(11px,1.7vw,13px);padding:10px 14px;text-align:right;border-bottom:1px solid #151c30;white-space:nowrap;vertical-align:middle;"
    TD_DATE  = "font-family:'IBM Plex Mono',monospace;font-size:clamp(9px,1.4vw,10px);color:#4E577A;padding:10px 14px;border-bottom:1px solid #151c30;white-space:nowrap;"
    TH_BASE  = "background:#111827;font-family:'IBM Plex Mono',monospace;font-size:clamp(8px,1.2vw,9px);text-transform:uppercase;letter-spacing:1.5px;padding:10px 14px;border-bottom:1px solid #1D2540;white-space:nowrap;text-align:right;"

    # Header row
    th_inline = (
        f'<th style="{TH_BASE}text-align:left;color:#4E577A;">Date</th>' +
        "".join(f'<th style="{TH_BASE}color:{COLORS[i%len(COLORS)]};">{s}</th>' for i, s in enumerate(stores_in_pivot)) +
        f'<th style="{TH_BASE}color:#4E577A;">Best</th>' +
        f'<th style="{TH_BASE}color:#4E577A;">Day Total</th>'
    )

    rows_html = ""
    for date_label, row in pivot.iterrows():
        day_total   = row.sum()
        active      = row[row > 0]
        best_val    = active.max()    if not active.empty else 0
        best_store  = active.idxmax() if not active.empty else "—"
        worst_store = active.idxmin() if len(active) >= 2 else None

        cells = ""
        for i, store in enumerate(stores_in_pivot):
            val   = row[store]
            color = COLORS[i % len(COLORS)]

            if val == 0:
                cells += f'<td style="{TD_BASE}color:#2E3555;font-family:IBM Plex Mono,monospace;">—</td>'
                continue

            pct      = int(val / best_val * 100) if best_val > 0 else 0
            is_best  = store == best_store
            is_worst = store == worst_store

            if is_best:
                val_color  = "#22C87A"
                bar_color  = "#22C87A"
                val_weight = "font-weight:700;"
            elif is_worst:
                val_color  = "#F5454A"
                bar_color  = "#F5454A"
                val_weight = ""
            else:
                val_color  = "#9BA3C0"
                bar_color  = color
                val_weight = ""

            cells += (
                f'<td style="{TD_BASE}color:{val_color};{val_weight}position:relative;padding-bottom:18px;">' +
                f'${val:,.0f}' +
                f'<div style="position:absolute;bottom:5px;left:14px;right:14px;height:2px;background:#1A2035;border-radius:99px;">' +
                f'<div style="height:2px;border-radius:99px;width:{pct}%;background:{bar_color};"></div></div></td>'
            )

        best_html = (
            f'<span style="color:#22C87A;font-weight:600;">{best_store}</span>'
            if best_store != "—" else '<span style="color:#2E3555;">—</span>'
        )
        rows_html += (
            f'<tr>' +
            f'<td style="{TD_DATE}">{date_label}</td>' +
            cells +
            f'<td style="{TD_BASE}text-align:left;">{best_html}</td>' +
            f'<td style="{TD_BASE}font-weight:700;color:#F0F2F8;">${day_total:,.0f}</td>' +
            f'</tr>'
        )

    # Totals row
    total_cells = "".join(
        f'<td style="padding:10px 14px;text-align:right;font-weight:700;color:{COLORS[i%len(COLORS)]};">${pivot[s].sum():,.0f}</td>'
        for i, s in enumerate(stores_in_pivot)
    )
    rows_html += (
        '<tr style="background:#111827;">' +
        f'<td style="padding:10px 14px;font-family:IBM Plex Mono,monospace;font-size:9px;color:#4E577A;letter-spacing:2px;text-transform:uppercase;">TOTAL</td>' +
        total_cells +
        '<td style="padding:10px 14px;color:#4E577A;">—</td>' +
        f'<td style="padding:10px 14px;text-align:right;font-weight:800;color:#4F8EF7;">${pivot.values.sum():,.0f}</td>' +
        '</tr>'
    )

    st.markdown(
        f'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:10px;border:1px solid #151c30;margin-bottom:8px;">' +
        f'<table style="width:100%;border-collapse:collapse;background:#0D1221;">' +
        f'<thead><tr>{th_inline}</tr></thead>' +
        f'<tbody>{rows_html}</tbody></table></div>' +
        '<div style="font-family:IBM Plex Mono,monospace;font-size:8.5px;color:#4E577A;letter-spacing:1px;">' +
        '🟢 Best day &nbsp;·&nbsp; 🔴 Lowest reporter &nbsp;·&nbsp; — = no report &nbsp;·&nbsp; Bar = % of day peak' +
        '</div>',
        unsafe_allow_html=True
    )

# ════════════════════════════════════════════════════════════════════════════════
# TIER 3: TACTICAL — TABS + RED ZONE
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="section-hdr">
  <div class="section-line"></div>
  <div class="section-label">Tactical Operations</div>
  <div class="section-line"></div>
</div>""", unsafe_allow_html=True)

main_col, rz_col = st.columns([3, 1])

with main_col:
    tabs = st.tabs(["🌡️ Status Map", "📅 Store Calendar", "📈 Momentum", "📊 Density & Volatility"])

    # ── TAB 1: Status Map ──
    with tabs[0]:
        latest_snap = df[df['report_date'] == df['report_date'].max()]
        hm_data = []
        for _, row in latest_snap.iterrows():
            sid    = row['store_id']
            val    = float(row['sales'] or 0)
            base   = baselines.get(sid, 0)
            status = analyze_store_status(val, base)
            vs_base = ((val - base) / base * 100) if base > 0 else 0
            hm_data.append({"Store": sid, "Status": status, "Sales": val,
                             "Baseline": round(base, 2), "vs Baseline %": round(vs_base, 1)})

        hm_df     = pd.DataFrame(hm_data)
        color_map = {"Green": "#22C87A", "Yellow": "#F5A623", "Red": "#F5454A"}

        fig_status = px.bar(
            hm_df, x="Store", y="Sales", color="Status",
            color_discrete_map=color_map, template="plotly_dark",
            text=hm_df['Sales'].apply(lambda v: f"${v:,.0f}"),
            hover_data={"Baseline": True, "vs Baseline %": True},
        )
        fig_status.update_traces(
            textposition='outside',
            textfont=dict(size=11, color='#F0F2F8'),
            marker_line_width=0
        )
        fig_status.update_layout(**PT, height=280,
            legend=dict(orientation='h', yanchor='bottom', y=1.02,
                        font=dict(size=10), bgcolor='rgba(0,0,0,0)'))
        fig_status.update_yaxes(visible=False)
        st.plotly_chart(fig_status, use_container_width=True)

        pill_cols = st.columns(3)
        for col, status, color_val, border_val in [
            (pill_cols[0], "Green",  "#22C87A", "rgba(34,200,122,0.25)"),
            (pill_cols[1], "Yellow", "#F5A623", "rgba(245,166,35,0.25)"),
            (pill_cols[2], "Red",    "#F5454A", "rgba(245,69,74,0.25)"),
        ]:
            cnt = len(hm_df[hm_df['Status'] == status])
            stores_in_zone = hm_df[hm_df['Status'] == status]['Store'].tolist()
            with col:
                st.markdown(f"""
                <div class="zone-pill" style="background:rgba(0,0,0,0.25);
                     border-color:{border_val};">
                    <div class="zone-pill-label" style="color:{color_val};">{status} Zone</div>
                    <div class="zone-pill-count" style="color:{color_val};">{cnt}</div>
                    <div style="font-family:var(--font-mono);font-size:8px;
                         color:var(--text-muted);margin-top:4px;">
                        {', '.join(stores_in_zone) if stores_in_zone else 'None'}
                    </div>
                </div>""", unsafe_allow_html=True)

    # ── TAB 2: Calendar ──
    with tabs[1]:
        sel_store  = st.selectbox("Store", options=STORES, key="cal_store")
        store_hist = df[df['store_id'] == sel_store].sort_values('report_date')

        fig_cal = px.bar(
            store_hist, x='report_date', y='sales',
            template='plotly_dark', color_discrete_sequence=['#4F8EF7'],
            text=store_hist['sales'].apply(lambda v: f"${v:,.0f}")
        )
        fig_cal.update_traces(textposition='outside',
                              textfont=dict(size=10, color='#9BA3C0'),
                              marker_line_width=0)
        fig_cal.update_layout(**PT, height=200)
        fig_cal.update_yaxes(visible=False)
        st.plotly_chart(fig_cal, use_container_width=True)

        cal_df = store_hist[['report_date','sales','inventory_status','staffing','analysis']].copy()
        cal_df['report_date'] = cal_df['report_date'].dt.strftime('%a %d %b %Y')
        cal_df.columns = ['Date','Sales ($)','Inventory','Staffing','Analysis']
        st.dataframe(cal_df.set_index('Date'), use_container_width=True)

    # ── TAB 3: Momentum ──
    with tabs[2]:
        store_totals = df.groupby('store_id')['sales'].sum().reset_index().sort_values('sales', ascending=False)
        ts = df.groupby(['report_date','store_id'])['sales'].sum().reset_index()

        st.markdown('<div class="chart-label">Multi-Store Revenue Timeline</div>', unsafe_allow_html=True)
        fig_ts = px.line(ts, x='report_date', y='sales', color='store_id',
                         template='plotly_dark', color_discrete_sequence=COLORS, markers=True)
        fig_ts.update_traces(line=dict(width=2.5), marker=dict(size=6))
        fig_ts.update_layout(**PT, height=250,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1,
                        font=dict(size=10), bgcolor='rgba(0,0,0,0)'))
        st.plotly_chart(fig_ts, use_container_width=True)

        bc, dc = st.columns([3,2])
        with bc:
            st.markdown('<div class="chart-label">Period Revenue by Store</div>', unsafe_allow_html=True)
            fig_bar = go.Figure(go.Bar(
                x=store_totals['store_id'], y=store_totals['sales'],
                marker=dict(color=COLORS[:len(store_totals)], line=dict(width=0)),
                text=[f"${v:,.0f}" for v in store_totals['sales']],
                textposition='outside', textfont=dict(size=10, color='#9BA3C0'),
            ))
            fig_bar.update_layout(**PT, height=220)
            fig_bar.update_yaxes(visible=False)
            st.plotly_chart(fig_bar, use_container_width=True)
        with dc:
            st.markdown('<div class="chart-label">Revenue Share</div>', unsafe_allow_html=True)
            fig_donut = go.Figure(go.Pie(
                labels=store_totals['store_id'], values=store_totals['sales'], hole=0.65,
                marker=dict(colors=COLORS[:len(store_totals)], line=dict(color='#080C16', width=3)),
                textinfo='none',
                hovertemplate='<b>%{label}</b><br>$%{value:,.2f} · %{percent}<extra></extra>'
            ))
            fig_donut.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=0,r=0,t=32,b=0), height=220, showlegend=True,
                legend=dict(font=dict(size=10, color='#9BA3C0'), bgcolor='rgba(0,0,0,0)',
                            orientation='v', x=0.72, y=0.5),
                annotations=[dict(
                    text=f"<b>${total_sales/1000:.0f}k</b><br><span style='font-size:8px;color:#4E577A;'>TOTAL</span>",
                    x=0.5, y=0.5, font=dict(size=13, color='#F0F2F8'), showarrow=False
                )]
            )
            st.plotly_chart(fig_donut, use_container_width=True)

    # ── TAB 4: Density & Volatility ──
    with tabs[3]:
        hm_c, box_c = st.columns([3,2])
        with hm_c:
            st.markdown('<div class="chart-label">Sales Density Matrix</div>', unsafe_allow_html=True)
            matrix_df = df.pivot_table(
                index='store_id',
                columns=df['report_date'].dt.strftime('%b %d'),
                values='sales', aggfunc='sum'
            ).fillna(0)
            if not matrix_df.empty:
                fig_hm2 = px.imshow(matrix_df,
                    color_continuous_scale=[[0,'#0D1221'],[0.35,'#1A3060'],
                                             [0.7,'#4F8EF7'],[1,'#BFD9FF']],
                    template='plotly_dark')
                fig_hm2.update_layout(**PT, height=250, coloraxis_showscale=False)
                fig_hm2.update_xaxes(tickfont=dict(size=9))
                fig_hm2.update_yaxes(tickfont=dict(size=9))
                st.plotly_chart(fig_hm2, use_container_width=True)
        with box_c:
            st.markdown('<div class="chart-label">Daily Sales Volatility</div>', unsafe_allow_html=True)
            fig_box = px.box(df, x='store_id', y='sales', points='all',
                             template='plotly_dark', color='store_id',
                             color_discrete_sequence=COLORS)
            fig_box.update_traces(marker=dict(size=4, opacity=0.7))
            fig_box.update_layout(**PT, height=250, showlegend=False)
            st.plotly_chart(fig_box, use_container_width=True)

# ── RED ZONE ────────────────────────────────────────────────────────────────────
with rz_col:
    st.markdown('<div class="rz-header">🚨 Red Zone</div>', unsafe_allow_html=True)

    today_reports = df[df['report_date'] == df['report_date'].max()].to_dict('records')
    red_zone      = identify_red_zone_stores(today_reports, baselines)

    if not red_zone:
        st.markdown("""
        <div style="background:var(--green-dim);border:1px solid var(--green-border);
             border-radius:var(--radius-md);padding:14px;">
            <div class="rz-ok">✓ All stores nominal</div>
        </div>""", unsafe_allow_html=True)
    else:
        for store in red_zone:
            st.markdown(f"""
            <div class="rz-card">
                <div class="rz-store">{store['store_id']}</div>
                <div class="rz-drop">↓ {store['drop_pct']}%</div>
                <div class="rz-meta">
                    Now: ${store['current_value']:,.0f}<br>
                    Base: ${store['baseline']:,.0f}
                </div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Alert {store['store_id']}", key=f"rz_{store['store_id']}"):
                st.toast(f"⚡ Alert sent to {store['store_id']} manager", icon="🚨")

# ════════════════════════════════════════════════════════════════════════════════
# TIER 4: LIVE NODE FEED
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="section-hdr">
  <div class="section-line"></div>
  <div class="section-label">Live Node Feed</div>
  <div class="section-line"></div>
</div>""", unsafe_allow_html=True)

store_list = list(df_latest.iterrows())
for i in range(0, len(store_list), 2):
    chunk = store_list[i:i+2]
    cols  = st.columns(len(chunk))
    for j, (_, r) in enumerate(chunk):
        al  = str(r['analysis']).lower()
        if any(w in al for w in ['decline','lower','drop','critical','alert']):
            badge_cls, accent, badge_lbl = 'badge-critical', '#F5454A', 'Critical'
        elif any(w in al for w in ['growth','up','increase','healthy','strong']):
            badge_cls, accent, badge_lbl = 'badge-growth',   '#22C87A', 'Growth'
        else:
            badge_cls, accent, badge_lbl = 'badge-stable',   '#F5A623', 'Stable'

        inv      = r.get('inventory_status') or '—'
        staff    = r.get('staffing') or '—'
        date_str = r['report_date'].strftime('%a %d %b %Y') if pd.notna(r['report_date']) else '—'
        s_total  = df[df['store_id'] == r['store_id']]['sales'].sum()
        net_share= (s_total / total_sales * 100) if total_sales > 0 else 0
        base     = baselines.get(r['store_id'], 0)
        vs_base  = ((r['sales'] - base) / base * 100) if base > 0 else 0
        vs_col   = '#22C87A' if vs_base >= 0 else '#F5454A'

        with cols[j]:
            st.markdown(f"""
            <div class="node-card">
                <div class="node-card-accent" style="background:{accent};"></div>
                <div class="node-header">
                    <div>
                        <div class="node-name">{r['store_id']}</div>
                        <div class="node-date">{date_str}</div>
                    </div>
                    <span class="node-badge {badge_cls}">{badge_lbl}</span>
                </div>
                <div class="node-metrics">
                    <div class="node-metric">
                        <div class="node-metric-label">Today Sales</div>
                        <div class="node-metric-value">${r['sales']:,.0f}</div>
                    </div>
                    <div class="node-metric">
                        <div class="node-metric-label">vs Baseline</div>
                        <div class="node-metric-value" style="color:{vs_col};">
                            {'▲' if vs_base>=0 else '▼'}{abs(vs_base):.1f}%
                        </div>
                    </div>
                    <div class="node-metric">
                        <div class="node-metric-label">Net Share</div>
                        <div class="node-metric-value">{net_share:.1f}%</div>
                    </div>
                    <div class="node-metric">
                        <div class="node-metric-label">Inventory</div>
                        <div class="node-metric-value" style="font-size:clamp(11px,1.8vw,13px);">{inv}</div>
                    </div>
                    <div class="node-metric">
                        <div class="node-metric-label">Staffing</div>
                        <div class="node-metric-value" style="font-size:clamp(11px,1.8vw,13px);">{staff}</div>
                    </div>
                    <div class="node-metric">
                        <div class="node-metric-label">Period Total</div>
                        <div class="node-metric-value">${s_total:,.0f}</div>
                    </div>
                </div>
                <div class="node-analysis" style="border-color:{accent};">
                    💡 {r['analysis']}
                </div>
            </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TIER 5: LEADERBOARD + DRILLDOWN
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="section-hdr">
  <div class="section-line"></div>
  <div class="section-label">Performance Leaderboard</div>
  <div class="section-line"></div>
</div>""", unsafe_allow_html=True)

rank_df = df.groupby('store_id').agg(
    total_sales=('sales','sum'),
    avg_sales=('sales','mean'),
    max_sales=('sales','max'),
    min_sales=('sales','min'),
    report_count=('report_date','count')
).reset_index().sort_values('total_sales', ascending=False)
rank_df['share'] = rank_df['total_sales'] / rank_df['total_sales'].sum() * 100
rank_df['rank']  = range(1, len(rank_df)+1)
max_total = rank_df['total_sales'].max()

lb_col2, drill_col2 = st.columns([2,3])

with lb_col2:
    rows_html = ""
    for _, row in rank_df.iterrows():
        bar_pct = int(row['total_sales'] / max_total * 100)
        medal   = {1:"🥇",2:"🥈",3:"🥉"}.get(int(row['rank']),
                  f"<span style='font-family:var(--font-mono);font-size:10px;color:var(--text-muted);'>#{int(row['rank'])}</span>")
        rows_html += f"""
        <tr>
            <td style="width:32px;">{medal}</td>
            <td><div class="lb-store-name">{row['store_id']}</div></td>
            <td>
                <div class="lb-revenue">${row['total_sales']:,.0f}</div>
                <div class="lb-bar-wrap">
                    <div class="lb-bar-fill" style="width:{bar_pct}%;"></div>
                </div>
            </td>
            <td class="lb-share">{row['share']:.1f}%</td>
            <td style="color:var(--text-secondary);font-family:var(--font-mono);font-size:11px;">${row['avg_sales']:,.0f}</td>
            <td style="color:var(--green);font-family:var(--font-mono);font-size:11px;">${row['max_sales']:,.0f}</td>
        </tr>"""

    st.markdown(f"""
    <div class="lb-wrap">
        <table class="lb-table">
            <thead><tr>
                <th></th><th>Store</th><th>Revenue</th>
                <th>Share</th><th>Daily Avg</th><th>Peak Day</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>""", unsafe_allow_html=True)

with drill_col2:
    selected = st.selectbox("Drill into store", options=STORES, label_visibility="collapsed")
    s_df     = df[df['store_id'] == selected].sort_values('report_date')
    rolling  = s_df['sales'].rolling(window=min(7, len(s_df)), min_periods=1).mean()

    fig_drill = make_subplots(rows=1, cols=2,
        subplot_titles=["Daily Sales", "7-Day Rolling Avg"],
        horizontal_spacing=0.1)
    fig_drill.add_trace(go.Scatter(
        x=s_df['report_date'], y=s_df['sales'], mode='lines+markers',
        line=dict(color='#4F8EF7', width=2.5, shape='spline'),
        marker=dict(size=6, color='#4F8EF7'),
        fill='tozeroy', fillcolor='rgba(79,142,247,0.1)'
    ), row=1, col=1)
    fig_drill.add_trace(go.Scatter(
        x=s_df['report_date'], y=rolling, mode='lines',
        line=dict(color='#22C87A', width=2.5, dash='dot', shape='spline'),
    ), row=1, col=2)
    fig_drill.update_layout(**PT, height=230, showlegend=False,
        annotations=[dict(font=dict(size=10, color='#9BA3C0'))
                     for _ in fig_drill.layout.annotations])
    st.plotly_chart(fig_drill, use_container_width=True)

    s_stats = rank_df[rank_df['store_id'] == selected].iloc[0]
    sc1,sc2,sc3,sc4,sc5 = st.columns(5)
    for scol, lbl, val in [
        (sc1, "Period Total", f"${s_stats['total_sales']:,.0f}"),
        (sc2, "Daily Avg",    f"${s_stats['avg_sales']:,.0f}"),
        (sc3, "Peak Day",     f"${s_stats['max_sales']:,.0f}"),
        (sc4, "Low Day",      f"${s_stats['min_sales']:,.0f}"),
        (sc5, "Net Share",    f"{s_stats['share']:.1f}%"),
    ]:
        with scol:
            st.markdown(f"""
            <div class="mini-stat">
                <div class="mini-stat-label">{lbl}</div>
                <div class="mini-stat-value">{val}</div>
            </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TIER 6: ARCHIVE LEDGER
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""<div class="section-hdr">
  <div class="section-line"></div>
  <div class="section-label">Historical Archive</div>
  <div class="section-line"></div>
</div>""", unsafe_allow_html=True)

search_term = st.text_input("",
    placeholder="⚡  Search by store, inventory status, or keyword...",
    label_visibility="collapsed")

filtered = df.copy()
if search_term:
    mask = (
        df['store_id'].str.contains(search_term, case=False, na=False) |
        df['analysis'].str.contains(search_term, case=False, na=False) |
        df['inventory_status'].str.contains(search_term, case=False, na=False)
    )
    filtered = df[mask]

st.dataframe(
    filtered.sort_values('report_date', ascending=False).rename(columns={
        'report_date':      '📅 Date',
        'store_id':         '🏪 Store',
        'sales':            '💰 Sales',
        'inventory_status': '📦 Inventory',
        'staffing':         '👥 Staffing',
        'analysis':         '📋 Analysis',
    }),
    use_container_width=True,
    hide_index=True,
    height=320,
)

# ─── FOOTER ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="footer">
    <div class="footer-text">OPS◈NEXUS — Sovereign Intelligence Console v3.0</div>
    <div class="footer-text">
        {len(df_raw)} records · {df_raw['store_id'].nunique()} stores ·
        Groq Llama 3.3 · Supabase · refresh 2 min
    </div>
</div>
""", unsafe_allow_html=True)
