import os
import json
import time
import logging
from typing import List, Dict, Any, Optional
from groq import Groq

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("OPS_BRAIN_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT_S = 15.0
GROQ_MAX_RETRIES = 2
GROQ_RETRY_BACKOFF_S = 1.5


def _safe_json_loads(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.find("\\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    logger.error("ops_brain: could not parse JSON from model output: %r", raw[:300])
    return None


def _groq_chat(client: Groq, prompt: str, model: str) -> Optional[Dict[str, Any]]:
    last_err = None
    for attempt in range(1, GROQ_MAX_RETRIES + 1):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                timeout=GROQ_TIMEOUT_S,
            )
            raw = completion.choices[0].message.content
            parsed = _safe_json_loads(raw)
            if parsed is not None:
                return parsed
            last_err = ValueError("json parse failed")
        except Exception as e:
            last_err = e
            logger.warning("ops_brain: groq attempt %d/%d failed: %s", attempt, GROQ_MAX_RETRIES, e)
        if attempt < GROQ_MAX_RETRIES:
            time.sleep(GROQ_RETRY_BACKOFF_S * attempt)
    logger.error("ops_brain: giving up after %d attempts. last_err=%s", GROQ_MAX_RETRIES, last_err)
    return None


class OpsManagerAI:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        if not api_key or not api_key.strip():
            raise ValueError("OpsManagerAI: api_key is empty")
        self.client = Groq(api_key=api_key)
        self.model = model

    def process_telegram_message(self, text: str) -> Dict[str, Any]:
        prompt = f"""
        You are a Professional AI Operations Manager. Parse store reports into JSON.

        Templates:
        - Daily: 'Daily Update [ Store Name ] Date: [Date] 💵 Sales: [Value] 🛍️Transactions: [Value] 📊Average Transaction (AT): [Value]'
        - Monthly: 'Monthly Update [ Store Name ] Period: [Period] 💵 Total Sales: [Value] 🛍️Transactions: [Value] 📊Average Selling Price: [Value]'

        Extract store_id from [ ], sales from Sales:/Total Sales:, transactions from Transactions:

 la
        Input: {text}

        Return JSON:
        {{
            "store_id": "name from brackets",
            "metrics": {{"sales": float, "inventory_status": "Good|Warning|Critical", "staffing": "OK|Understaffed|Overstaffed"}},
            "issues": [],
            "analysis": "brief summary",
            "actions_needed": ["action"]
        }}
        ONLY JSON.
        """
        parsed = _groq_chat(self.client, prompt, self.model)
        if parsed is not None and parsed.get("store_id"):
            return parsed
        return {
            "store_id": None,
            "metrics": {"sales": None, "inventory_status": None, "staffing": None},
            "issues": [],
            "analysis": "AI could not extract a valid store report from the message.",
            "actions_needed": [],
        }

    def process_voice_memo(self, transcription: str) -> Dict[str, Any]:
        """
        Converts transcribed voice notes into structured store data.
        """
        prompt = f"""
        You are a Professional AI Operations Manager. The following is a transcription of a manager's voice note.
        Convert this informal speech into a structured store report JSON.

        Input Transcription: {transcription}

        Return JSON:
        {{
            "store_id": "name from text",
            "metrics": {{"sales": float, "inventory_status": "Good|Warning|Critical", "staffing": "OK|Understaffed|Overstaffed"}},
            "issues": [],
            "analysis": "summary of the voice note",
            "actions_needed": ["action"]
        }}
        ONLY JSON.
        """
        parsed = _groq_chat(self.client, prompt, self.model)
        if parsed:
            return parsed
        return {"store_id": None, "metrics": {}, "analysis": "AI could not structure the voice note."}
