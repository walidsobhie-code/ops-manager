import os
import logging
import asyncio
import base64
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from src.ingestion_v2.engine import DeepThinkIngestor, DurableStore, StorageManager
from brain.db_handler import StoreDB

logger = logging.getLogger(__name__)

# --- New Multimodal Handler ---
async def handle_multimodal_message(update: Update, context: ContextTypes.DEFAULT_TYPE, ingestor: DeepThinkIngestor, store: DurableStore):
    user = update.message.from_user
    msg = update.message
    
    # 0. Prevent Disk Saturation before processing
    StorageManager.cleanup_old_files()
    
    # 1. Collect all modalities in the message
    # Telegram messages can contain text and a photo, or text and a voice note (usually separately, but we want to be ready)
    inputs = []
    
    # Handle Photo
    if msg.photo:
        photo = msg.photo[-1]
        file = await photo.get_file()
        async with httpx.AsyncClient() as client:
            resp = await client.get(file.file_path)
            img_b64 = base64.b64encode(resp.content).decode('utf-8')
            inputs.append((img_b64, "image"))
            
    # Handle Voice
    if msg.voice:
        voice_file = await msg.voice.get_file()
        path = f"downloads/{voice_file.file_id}.ogg"
        await voice_file.download_to_drive(path)
        inputs.append((path, "voice"))
        
    # Handle Text
    if msg.text or msg.caption:
        text = msg.text or msg.caption
        inputs.append((text, "text"))

    if not inputs:
        await msg.reply_text("Unsupported message format.")
        return

    try:
        # 2. Parallelized Processing
        metadata = {"user_id": user.id, "username": user.username}
        
        # Trigger all modality processors in parallel via the new batch method
        results = await ingestor.ingest_multimodal_batch(inputs, metadata)
        
        # 3. Durable Flush for all results
        for triad_payload in results:
            await store.flush(triad_payload)
        
        # 4. Response
        # Synthesize summary from all processed modalities
        summary_parts = []
        for p in results:
            summary_parts.append(f"**{p.source_type.capitalize()}**: {p.metadata.get('analysis', 'N/A')}")
            
        response_text = "✅ Multimodal reports processed.\n\n" + "\n".join(summary_parts)
        await msg.reply_text(response_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Multimodal pipeline error: {e}")
        await msg.reply_text("❌ Failed to process multimodal report. Please try again.")
