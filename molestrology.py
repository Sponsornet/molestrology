import os
import logging
import json
from io import BytesIO
from PIL import Image, ImageDraw
import google.generativeai as genai
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
genai.configure(api_key=GEMINI_API_KEY)

async def generate_soft_voice(text: str, lang: str) -> BytesIO:
    voices = {"uk": "uk-UA-PolinaNeural", "ru": "ru-RU-SvetlanaNeural", "en": "en-US-AvaNeural"}
    voice = voices.get(lang, "uk-UA-PolinaNeural")
    communicate = edge_tts.Communicate(text[:800], voice)
    voice_buffer = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "data": voice_buffer.write(chunk["data"])
    voice_buffer.seek(0)
    return voice_buffer

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("language", "uk")
    msg = await update.message.reply_text("🔮 Аналізую зірки та малюю карту...")
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # 1. Анализ через Gemini (просим текст + JSON координат)
        model = genai.GenerativeModel("gemini-3.6-flash")
        prompt = (
            "Ты — звездный оракул. Проанализируй родинки. "
            "Верни ответ в формате JSON: "
            "{ \"text\": \"твой мистический текст...\", \"coords\": [[x1,y1], [x2,y2], ...] } "
            "где координаты — это точки родинок (от 0 до 1000)."
        )
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": bytes(photo_bytes)}])
        data = json.loads(response.text.replace("```json", "").replace("```", ""))
        
        # 2. Рисование линий
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        coords = data.get("coords", [])
        w, h = img.size
        pixel_coords = [(c[0]*w/1000, c[1]*h/1000) for c in coords]
        
        for i in range(len(pixel_coords) - 1):
            draw.line([pixel_coords[i], pixel_coords[i+1]], fill="yellow", width=5)
            draw.ellipse([pixel_coords[i][0]-10, pixel_coords[i][1]-10, pixel_coords[i][0]+10, pixel_coords[i][1]+10], outline="yellow")

        # Сохраняем результат
        out_img = BytesIO()
        img.save(out_img, format="JPEG")
        out_img.seek(0)

        # 3. Отправка
        await update.message.reply_photo(photo=out_img, caption=data["text"])
        voice = await generate_soft_voice(data["text"], lang)
        await update.message.reply_voice(voice=voice)
        await msg.delete()

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text("❌ Помилка: спробуйте інше фото.")

# Остальные функции (start, main) оставьте как были
