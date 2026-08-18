import os
import logging
import json
from io import BytesIO
from PIL import Image, ImageDraw

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
        "uk": "🔮 Зчитую зоряну карту та малюю созвездия...",
        "ru": "🔮 Считываю звездную карту и рисую созвездия...",
        "en": "🔮 Reading your star map and drawing constellations..."
    }
    processing_msg = await update.message.reply_text(status_messages.get(lang, status_messages["uk"]))

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # 1. Запрос к Gemini 3.6 Flash
        model = genai.GenerativeModel("gemini-3.6-flash")
        
        lang_instructions = {
            "uk": "Відповідай СУВОРO УКРАЇНСЬКОЮ МОВОЮ.",
            "ru": "Отвечай СТРОГО НА РУССКОМ языке.",
            "en": "Answer STRICTLY IN ENGLISH."
        }
        
        prompt = (
            f"Ты — мистический звездный оракул. Проанализируй родинки на фото. "
            f"{lang_instructions.get(lang, lang_instructions['uk'])} "
            f"Верни ответ STRICTLY в формате валидного JSON без разметки markdown: "
            f"{{\"text\": \"мистическое пророчество одним текстом (макс 90 слов)...\", \"coords\": [[x1, y1], [x2, y2], ...]}} "
            f"где coords — массив координат родинок от 0 до 1000 по оси X и Y."
        )
        
        image_part = {"mime_type": "image/jpeg", "data": bytes(photo_bytes)}
        response = model.generate_content([prompt, image_part])
        
        # Очистка и парсинг JSON
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
        
        prediction_text = data.get("text", "Зірки зберігають мовчання...")
        coords = data.get("coords", [])
        
        # 2. Отрисовка линий и узлов звезд поверх фото
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        
        if coords:
            pixel_coords = [(c[0] * w / 1000, c[1] * h / 1000) for c in coords]
            
            # Соединяем родинки жёлтыми линиями
            for i in range(len(pixel_coords) - 1):
                draw.line([pixel_coords[i], pixel_coords[i+1]], fill="yellow", width=6)
                
            # Отрисовываем узлы-звёзды вокруг родинок
            for pt in pixel_coords:
                draw.ellipse([pt[0]-12, pt[1]-12, pt[0]+12, pt[1]+12], outline="yellow", width=4)

        # Сохранение обработанного фото в буфер
        out_img = BytesIO()
        img.save(out_img, format="JPEG")
        out_img.seek(0)

        # 3. Отправка картинки с текстом
        await update.message.reply_photo(photo=out_img, caption=prediction_text)
        
        # 4. Безопасная отправка звука (не ломает бота при сбое TTS)
        try:
            voice_buffer = await generate_soft_voice(prediction_text, lang)
            if voice_buffer and voice_buffer.getbuffer().nbytes > 100:
                await update.message.reply_voice(voice=voice_buffer)
        except Exception as tts_err:
            logger.warning(f"Голосовая озвучка пропущена из-за ошибки: {tts_err}")

        await processing_msg.delete()

    except Exception as e:
        logger.error(f"Ошибка в photo_handler: {e}")
        error_msg = {
            "uk": "❌ Помилка обробки. Спробуйте інше фото.",
            "ru": "❌ Ошибка обработки. Попробуйте другое фото.",
            "en": "❌ Processing error. Please try another photo."
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
