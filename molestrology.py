import os
import base64
import logging
from io import BytesIO
from datetime import datetime

import aiohttp
import filetype
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from gtts import gTTS

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
WEBHOOK_URL    = os.environ.get("WEBHOOK_URL", "").strip()

MAX_TTS_LENGTH    = 1000
MAX_IMAGE_SIZE_MB = 5


def get_mime_type(image_bytes: bytes) -> str:
    kind = filetype.guess(image_bytes)
    if kind and kind.mime.startswith("image/"):
        return kind.mime
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            if img.format:
                return f"image/{img.format.lower()}"
    except Exception:
        pass
    return "image/jpeg"


def truncate_for_tts(text: str, max_length: int = MAX_TTS_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    last_period = text.rfind(".", 0, max_length)
    if last_period > 0:
        return text[:last_period + 1]
    return text[:max_length] + "..."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_ua")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
    ]
    await update.message.reply_text(
        "🔮 Welcome to Molestrology!\n\nChoose your language:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "lang_ua":
        context.user_data["language"] = "ua"
        await query.edit_message_text(
            "📸 Надішли фото своїх родимок.\n\n"
            "Я знайду в них зоряну карту та розкажу, що вона означає прямо зараз! ✨"
        )
    elif query.data == "lang_en":
        context.user_data["language"] = "en"
        await query.edit_message_text(
            "📸 Send a photo of your moles.\n\n"
            "I will find a star map and tell you what it means right now! ✨"
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("language", "en")
    text = (
        "⚠️ Надішли *фото* своїх родимок."
        if lang == "ua" else
        "⚠️ Please send a *photo* of your moles."
    )
    await update.message.reply_text(text)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    lang = context.user_data.get("language", "en")

    if "language" not in context.user_data:
        await update.message.reply_text("Please use /start first")
        return

    processing_msg = await update.message.reply_text(
        "🔮 Reading your star map..." if lang == "en" else "🔮 Зчитую зоряну карту..."
    )

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        photo_bytes = bytes(photo_bytes)

        size_mb = len(photo_bytes) / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            error_text = (
                f"❌ Photo too large ({size_mb:.1f} MB). Max {MAX_IMAGE_SIZE_MB} MB."
                if lang == "en" else
                f"❌ Фото занадто велике ({size_mb:.1f} МБ). Макс {MAX_IMAGE_SIZE_MB} МБ."
            )
            await processing_msg.edit_text(error_text)
            return

        mime_type = get_mime_type(photo_bytes)
        image_base64 = base64.b64encode(photo_bytes).decode("utf-8")

        now = datetime.now()
        month_name_en = now.strftime("%B")
        month_name_ua = {
            1: "січень", 2: "лютий", 3: "березень", 4: "квітень",
            5: "травень", 6: "червень", 7: "липень", 8: "серпень",
            9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень"
        }[now.month]

        prompt_ua = (
            f"Ти — загадковий зоряний оракул. Сьогодні {now.strftime('%d.%m.%Y')}, місяць {month_name_ua}. "
            f"На фото тіла людини видно родимки. "
            f"Відповідай ОДНИМ коротким абзацом (макс. 120 слів), захоплююче, містично. "
            f"Скажи, яке сузір'я ти бачиш у розташуванні родимок. "
            f"Розкажи 1 реченням його стародавню легенду. "
            f"Скажи, де на реальному небі це сузір'я зараз (північна півкуля, {month_name_ua}). "
            f"Скажи, що це означає для людини — її зоряна доля. "
            f"Закликай перевірити інші ділянки тіла. "
            f"НЕ пиши списки, тире, розділи. Одним цікавим текстом."
        )

        prompt_en = (
            f"You are a mysterious star oracle. Today is {now.strftime('%d.%m.%Y')}, month of {month_name_en}. "
            f"You see a photo of moles on a person's body. "
            f"Answer in ONE short paragraph (max 120 words), captivating, mystical. "
            f"Tell what constellation you see in the moles. "
            f"Share its ancient legend in 1 sentence. "
            f"Tell where this constellation is on the real sky right now (Northern Hemisphere, {month_name_en}). "
            f"Tell what it means for the person — their star destiny. "
            f"Encourage checking other body areas. "
            f"NO lists, NO dashes, NO sections. One flowing text."
        )

        prompt = prompt_en if lang == "en" else prompt_ua

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "maxOutputTokens": 400,
                "temperature": 0.7
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                data = await resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            block_reason = data.get("promptFeedback", {}).get("blockReason", "Unknown")
            raise Exception(f"Content blocked by Gemini: {block_reason}")

        text = candidates[0]["content"]["parts"][0]["text"].strip()
        text = text.replace("**", "").replace("*", "").replace("## ", "").replace("# ", "")
        text = text.replace("1. ", "").replace("2. ", "").replace("3. ", "").replace("4. ", "")
        text = text.replace("• ", "").replace("- ", "").strip()

        await processing_msg.edit_text(text)

        tts_lang = "uk" if lang == "ua" else "en"
        tts_text = truncate_for_tts(text)
        tts = gTTS(text=tts_text, lang=tts_lang, slow=False)
        voice_buffer = BytesIO()
        tts.write_to_fp(voice_buffer)
        voice_buffer.seek(0)
        await update.message.reply_voice(voice=voice_buffer)

    except Exception as e:
        logger.exception(f"Error: {e}")
        error_text = (
            f"❌ Error: {str(e)[:200]}\nPlease try another photo."
            if lang == "en" else
            f"❌ Помилка: {str(e)[:200]}\nСпробуйте інше фото."
        )
        await processing_msg.edit_text(error_text)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception:", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ Error. Please try /start.")


def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN not set!")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set!")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_error_handler(error_handler)

    if WEBHOOK_URL:
        base_url = WEBHOOK_URL.rstrip("/").strip()
        webhook_url = f"{base_url}/webhook"
        port = int(os.environ.get("PORT", "10000"))

        try:
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path="/webhook",
                webhook_url=webhook_url
            )
        except Exception as e:
            logger.error(f"Webhook failed: {e}")
            application.run_polling()
    else:
        application.run_polling()


if __name__ == "__main__":
    main()
