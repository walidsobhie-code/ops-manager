"""
DEPRECATED — DO NOT RUN.

This is a vestigial v1 of the bot runner. The real entry point is ../main.py
(uses ApplicationBuilder + FastAPI heartbeat on port 7860 in a single asyncio loop).

Kept in-tree for historical reference. Imports deliberately broken to fail fast
if anyone tries to run it.
"""
raise RuntimeError(
    "bot/main.py is deprecated. Run `python main.py` from the project root instead."
)

# ─── Old code (kept for archaeology, unreachable) ──────────────────────────────
# import os
# import logging
# from telegram import Update
# from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
# from brain.ops_brain import OpsManagerAI
# from brain.db_handler import StoreDB
#
# TELEGRAM_TOKEN = "8721772880:***"   # ← redacted placeholder, would 404 against real API
# TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# SUPABASE_URL = os.getenv("SUPABASE_URL")
# SUPABASE_KEY = os.getenv("SUPABASE_KEY")
#
# ai_manager = OpsManagerAI(api_key=GROQ_API_KEY)
# db = StoreDB(url=SUPABASE_URL, key=SUPABASE_KEY)
#
# logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
#
# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     ...
