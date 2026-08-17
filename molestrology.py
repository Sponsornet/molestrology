import os
import logging
from io import BytesIO
from datetime import datetime

import google.generativeai as genai
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
WEBHOOK_URL    = os.environ.get("WEBHOOK_URL", "").strip()

# ВАША ССЫЛКА НА MINI APP
MINI_APP_URL = "https://Sponsornet.github.io/molestrology/"

MAX_TTS_LENGTH = 1000

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def truncate_for_tts(text: str, max_length: int = MAX_TTS_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    last_period = text.rfind(".", 0, max_length)
    if last_period > 0:
        return text[:last_period + 1]
    return text[:max_length] + "..."

async def generate_soft_voice(text: str, lang: str) -> BytesIO:
    """Генерация мягкого женского голоса (Светлана)"""
    voice = "ru-RU-SvetlanaNeural" if lang == "ru" else "en-US-AvaNeural"
    tts_text = truncate_for_tts(text)
    
    communicate = edge_tts.Communicate(tts_text, voice)
    voice_buffer = BytesIO()
    
    async for chunk in communicate.stream():
        if chunk["type"] == "data":
            voice_buffer.write(chunk["data"])
            
    voice_buffer.seek(0)
    return voice_buffer

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔮 Открыть Оракул (Mini App)", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
    ]
    await update.message.reply_text(
        "🔮 **Добро пожаловать в Molestrology!**\n\n"
        "Нажмите кнопку **«Открыть Оракул»** ниже, чтобы запустить интерактивную карту звезд, "
        "или просто отправьте фото ваших родинок в этот чат.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "lang_ru":
        context.user_data["language"] = "ru"
        await query.edit_message_text(
            "📸 Отправь фото своих родимок.\n\n"
            "Я найду в них звездную карту и расскажу, что она означает прямо сейчас! ✨"
        )
    elif query.data == "lang_en":
        context.user_data["language"] = "en"
        await query.edit_message_text(
            "📸 Send a photo of your moles.\n\n"
            "I will find a star map and tell you what it means right now! ✨"
        )

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("language", "ru")
    processing_msg = await update.message.reply_text(
        "🔮 Считываю звездную карту..." if lang == "ru" else "🔮 Reading your star map..."
    )

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        prompt = (
            f"Ты — загадочный звездный оракул. На фото тела человека видны родинки. "
            f"Отвечай ОДНИМ коротким абзацем (макс. 120 слов), увлекательно, мистически. "
            f"Скажи, какое созвездие ты видишь в расположении родинок. "
            f"Расскажи его древнюю легенду в 1 предложении. "
            f"Что это означает для человека — его звездная судьба. "
            f"Никаких списков, пиши одним связным текстом."
            if lang == "ru" else
            f"You are a mysterious star oracle. You see a photo of moles. "
            f"Answer in ONE short paragraph (max 120 words), captivating, mystical. "
            f"Tell what constellation you see. "
            f"Share its ancient legend in 1 sentence. "
            f"Tell what it means for the person — their star destiny. "
            f"No lists, write in one flowing text."
        )

        image_part = {"mime_type": "image/jpeg", "data": bytes(photo_bytes)}
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        response = model.generate_content([prompt, image_part])
        text = response.text.strip()

        await processing_msg.edit_text(text)
        
        voice_buffer = await generate_soft_voice(text, lang)
        await update.message.reply_voice(voice=voice_buffer)

    except Exception as e:
        logger.exception(e)
        await processing_msg.edit_text("❌ Ошибка при анализе. Попробуйте другое фото.")

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    if WEBHOOK_URL:
        application.run_webhook(listen="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
                                url_path="/webhook", webhook_url=f"{WEBHOOK_URL.rstrip('/')}/webhook")
    else:
        application.run_polling()

if __name__ == "__main__":
    main()
