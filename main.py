import os
import signal
import logging
import asyncio
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse
import uvicorn
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest
from brain.ops_brain import OpsManagerAI
from brain.db_handler import StoreDB

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # Suppress URLs containing bot token

def get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value or not value.strip():
        raise RuntimeError(f"Missing environment variable: '{var_name}'")
    return value

TELEGRAM_TOKEN   = get_required_env("TELEGRAM_TOKEN")
GROQ_API_KEY     = get_required_env("GROQ_API_KEY")
SUPABASE_URL     = get_required_env("SUPABASE_URL")
SUPABASE_KEY     = get_required_env("SUPABASE_KEY")
WEBHOOK_SECRET   = get_required_env("WEBHOOK_SECRET")
SPACE_URL        = get_required_env("SPACE_URL")

WEBHOOK_PATH     = "/telegram-webhook"
WEBHOOK_URL      = f"{SPACE_URL.rstrip('/')}{WEBHOOK_PATH}"

ai_manager = None
db = None
bot_app = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def safe_reply(message, text: str) -> None:
    """Send a reply, silently swallowing network timeouts so the handler never crashes."""
    try:
        await message.reply_text(text)
    except Exception as e:
        logger.warning(f"safe_reply: could not deliver message to user: {e}")

# ---------------------------------------------------------------------------
# Telegram message handler
# ---------------------------------------------------------------------------

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.voice:
        return

    user = update.message.from_user
    user_name = user.first_name if user else "Staff"
    logger.info(f"Processing voice memo from {user_name}")

    try:
        # 1. Download voice file
        voice_file = await update.message.voice.get_file()
        file_path = f"voice_{update.message.message_id}.ogg"
        await voice_file.download_to_drive(file_path)

        # 2. Transcription (Whisper API)
        import openai
        client = openai.OpenAI()
        audio_file = open(file_path, "rb")
        transcription = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file
        ).text

        # 3. Structure data via Groq
        structured_data = ai_manager.process_voice_memo(transcription)

        if not structured_data or not structured_data.get('store_id'):
            await safe_reply(
                update.message, 
                "⚠️ I received your voice note, but couldn't identify the store. Please try again or text the report."
            )
            return

        db.save_report(structured_data)
        await safe_reply(
            update.message, 
            f"✅ Voice report processed for {structured_data.get('store_id')}.\\n\\n"
            f"Transcription: {transcription}\\n\\n"
            f"Analysis: {structured_data.get('analysis', 'N/A')}\\n\\n"
            f"Logged to Dashboard."
        )
        
        # Cleanup
        os.remove(file_path)

    except Exception as e:
        logger.error(f"Voice memo error: {e}")
        await safe_reply(update.message, "❌ Failed to process voice memo. Ensure OpenAI key is configured.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    user = update.message.from_user
    user_name = user.first_name if user else "Staff"
    logger.info(f"Processing report from {user_name}")

    try:
        structured_data = ai_manager.process_telegram_message(text)

        if not structured_data or not structured_data.get('store_id'):
            await safe_reply(
                update.message,
                "⚠️ I couldn't extract a valid Store ID. Please mention your store location clearly."
            )
            return

        db.save_report(structured_data)
        await safe_reply(
            update.message,
            f"✅ Report successfully received for {structured_data.get('store_id')}.\\n\\n"
            f"Analysis Summary:\\n{structured_data.get('analysis', 'N/A')}\\n\\n"
            f"Actions logged to Live Dashboard."
        )

    except Exception as e:
        logger.error(f"Error in execution handler: {e}")
        await safe_reply(update.message, "❌ An error occurred while saving your report parameters.")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Sovereign Ops Heartbeat Engine")

@app.head("/")
async def head_root():
    return Response(status_code=status.HTTP_200_OK)

@app.get("/", response_class=HTMLResponse)
async def root():
    bot_status = "Webhook Active" if (ai_manager and db and bot_app) else "Booting"
    return f"""
    <!DOCTYPE html>
    <html style="background:#03050a;color:#cbd5e1;font-family:sans-serif;">
        <head><title>Sovereign Ops</title></head>
        <body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;">
            <div style="background:rgba(10,14,26,0.8);border:1px solid rgba(255,255,255,0.05);padding:32px;border-radius:12px;text-align:center;">
                <h1 style="color:#3b82f6;">◈ SOVEREIGN OPS MANAGER ◈</h1>
                <p>Status: <span style="background:rgba(16,185,129,0.08);color:#10b981;border:1px solid rgba(16,185,129,0.2);padding:4px 12px;border-radius:6px;font-weight:bold;">Online & Healthy</span></p>
                <p>Pipeline Engine: <span style="color:#e2e8f0;">{bot_status}</span></p>
            </div
        </body
    </html
    """

@app.get("/health")
async def health():
    return {
        "status": "ok" if (ai_manager and db and bot_app) else "initializing",
        "ai_service": bool(ai_manager),
        "db_connection": bool(db),
        "bot_active": bool(bot_app),
        "mode": "webhook",
        "pending_reports": db.pending_count() if db else -1,
    }

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != WEBHOOK_SECRET:
        logger.warning("Webhook received with invalid secret token.")
        raise HTTPException(status_code=403, detail="Forbidden")

    if not bot_app:
        logger.warning("Webhook hit before bot_app is ready.")
        raise HTTPException(status_code=503, detail="Bot not ready yet")

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}

# ---------------------------------------------------------------------------
# Bot initialisation — single attempt, cleans up on failure
# ---------------------------------------------------------------------------

async def _init_bot():
    """
    Build a fresh Application instance with generous timeouts, initialise it,
    and register the webhook. On any failure, gracefully shut down the partial
    instance so no lingering connections block the next retry.
    """
    global bot_app

    request_client = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=20.0,
    )

    app_instance = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .request(request_client)
        .updater(None)
        .build()
    )
    
    app_instance.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app_instance.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    try:
        logger.info("Step 1/3: Initializing app instance...")
        await app_instance.initialize()
        logger.info("Step 1/3: Initialization complete.")

        logger.info("Step 2/3: Starting app instance...")
        await app_instance.start()
        logger.info("Step 2/3: Start complete.")

        logger.info(f"Step 3/3: Registering webhook → {WEBHOOK_URL}")
        await app_instance.bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info("Step 3/3: Webhook registration complete.")

        bot_app = app_instance

    except Exception:
        try:
            await app_instance.stop()
        except Exception:
            pass
        try:
            await app_instance.shutdown()
        except Exception:
            pass
        raise

# ---------------------------------------------------------------------------
# Bot pipeline with retry loop
# ---------------------------------------------------------------------------

async def start_webhook_pipeline():
    global ai_manager, db

    await asyncio.sleep(2.0)

    logger.info("⚙️ Initializing Core AI and Database engines...")
    ai_manager = OpsManagerAI(api_key=GROQ_API_KEY)
    db = StoreDB(url=SUPABASE_URL, key=SUPABASE_KEY)

    max_attempts = 10
    retry_delay  = 30

    for attempt in range(1, max_attempts + 1):
        logger.info(f"🤖 Building Telegram bot application (attempt {attempt}/{max_attempts})...")
        try:
            await _init_bot()
            logger.info("🚀 Webhook registered. System is live and monitoring operational channels.")
            return
        except Exception as e:
            logger.warning(f"Bot init attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                logger.info(f"Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)

    logger.error("❌ Bot failed to initialize after all attempts. FastAPI health server still running.")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: stop_event.set())
        except NotImplementedError:
            pass

    config = uvicorn.Config(app, host="0.0.0.0", port=7860, log_level="info")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    logger.info("HF Heartbeat Web Server initialized onto port 7860.")

    asyncio.create_task(start_webhook_pipeline())

    await stop_event.wait()

    logger.info("Termination intercept caught. Initiating clean application teardown...")
    server.should_exit = True
    await server_task

    if bot_app:
        await bot_app.bot.delete_webhook()
        await bot_app.stop()
        await bot_app.shutdown()

    logger.info("Sovereign execution loop successfully finalized. Machine offline.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process offline.")
