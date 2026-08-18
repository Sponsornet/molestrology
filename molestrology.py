import os
import logging
from io import BytesIO

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
    """Генерация мягкого женского голоса с поддержкой UA, RU, EN"""
    voices = {
        "uk": "uk-UA-PolinaNeural",
        "ru": "ru-RU-SvetlanaNeural",
        "en": "en-US-AvaNeural"
    }
    voice = voices.get(lang, "uk-UA-PolinaNeural")
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
        [InlineKeyboardButton("🔮 Відкрити Оракул (Mini App)", web_app=WebAppInfo(url=MINI_APP_URL))],
        [
            InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")
        ]
    ]
    await update.message.reply_text(
        "🔮 **Ласкаво просимо до Molestrology!**\n\n"
        "Оберіть мову або натисніть **«Відкрити Оракул»**, щоб запустити інтерактивну карту зорей. "
        "Також ви можете просто надіслати фото своїх родимок у цей чат.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "lang_uk":
        context.user_data["language"] = "uk"
        await query.edit_message_text(
            "📸 Надішли фото своїх родимок.\n\n"
            "Я знайду в них зоряну карту та розповім її таємницю! ✨"
        )
    elif query.data == "lang_ru":
        context.user_data["language"] = "ru"
        await query.edit_message_text(
            "📸 Отправь фото своих родинок.\n\n"
            "Я найду в них звездную карту и расскажу, что она означает! ✨"
        )
    elif query.data == "lang_en":
        context.user_data["language"] = "en"
        await query.edit_message_text(
            "📸 Send a photo of your moles.\n\n"
            "I will find a star map and reveal its mystery! ✨"
        )

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("language", "uk")
    
    status_messages = {
        "uk": "🔮 Зчитую зоряну карту...",
        "ru": "🔮 Считываю звездную карту...",
        "en": "🔮 Reading your star map..."
    }
    processing_msg = await update.message.reply_text(status_messages.get(lang, status_messages["uk"]))

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Системный промпт с жесткой привязкой к выбранному языку
        prompts = {
            "uk": (
                "Ти — таємничий зоряний оракул. На фото тіла людини видно родимки. "
                "Відповідай СУВОРO УКРАЇНСЬКОЮ МОВОЮ одним коротким абзацем (макс. 100 слів). "
                "Знайди прадавнє созв'яззя в родимках, розкажи його легенду в 1 реченні "
                "та пророкуй долю людини. Пиши суцільним художнім текстом без списків."
            ),
            "ru": (
                "Ты — мистический звездный оракул. На фото видны родинки. "
                "Отвечай СТРОГО НА РУССКОМ языке одним коротким абзацем (макс. 100 слов). "
                "Назови созвездие, опиши легенду в 1 предложении и предскажи судьбу. Без списков."
            ),
            "en": (
                "You are a mystical star oracle. Look at the moles on the skin. "
                "Answer STRICTLY IN ENGLISH in ONE short paragraph (max 100 words). "
                "Name the constellation, tell its legend in 1 sentence, and predict destiny. Flowing text only."
            )
        }

        image_part = {"mime_type": "image/jpeg", "data": bytes(photo_bytes)}
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        response = model.generate_content([prompts.get(lang, prompts["uk"]), image_part])
        text = response.text.strip()

        await processing_msg.edit_text(text)
        
        # Попытка генерации и отправки аудио в изоляции от основного текста
        try:
            voice_buffer = await generate_soft_voice(text, lang)
            await update.message.reply_voice(voice=voice_buffer)
        except Exception as tts_err:
            logger.error(f"Ошибка генерации TTS: {tts_err}")

    except Exception as e:
        logger.exception(e)
        error_msg = {
            "uk": "❌ Помилка при аналізі. Спробуйте інше фото.",
            "ru": "❌ Ошибка при анализе. Попробуйте другое фото.",
            "en": "❌ Analysis error. Please try another photo."
        }
        await processing_msg.edit_text(error_msg.get(lang, error_msg["uk"]))

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            url_path="/webhook",
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}/webhook"
        )
    else:
        application.run_polling()

if __name__ == "__main__":
    main()
