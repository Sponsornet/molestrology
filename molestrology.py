import os
import logging
import json
import base64
from io import BytesIO
from PIL import Image, ImageDraw

import google.generativeai as genai
import edge_tts
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# Логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Змінні середовища
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
WEBHOOK_URL    = os.environ.get("WEBHOOK_URL", "").strip()
PORT           = int(os.environ.get("PORT", "10000"))

MINI_APP_URL = "https://Sponsornet.github.io/molestrology/"

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Ініціалізація Telegram Bot Application
ptb_app = Application.builder().token(TELEGRAM_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔮 Відкрити Оракул (Mini App)", web_app=WebAppInfo(url=MINI_APP_URL))]]
    await update.message.reply_text(
        "🔮 **Ласкаво просимо до Molestrology!**\n\n"
        "Натисніть кнопку нижче, щоб відкрити Mini App та дізнатися таємницю своїх зорей.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

ptb_app.add_handler(CommandHandler("start", start))

# Генерація голосу
async def generate_soft_voice(text: str, lang: str = "uk") -> BytesIO:
    voices = {"uk": "uk-UA-PolinaNeural", "ru": "ru-RU-SvetlanaNeural", "en": "en-US-AvaNeural"}
    voice = voices.get(lang, "uk-UA-PolinaNeural")
    communicate = edge_tts.Communicate(text[:800], voice)
    voice_buffer = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "data":
            voice_buffer.write(chunk["data"])
    voice_buffer.seek(0)
    return voice_buffer

# Обробка запиту від Mini App
async def handle_api_process(request):
    try:
        reader = await request.multipart()
        field = await reader.next()
        photo_bytes = await field.read()

        model = genai.GenerativeModel("gemini-3.6-flash")
        prompt = (
            "Ты — мистический оракул. Проанализируй родинки. "
            "Верни STRICTLY JSON: {\"text\": \"пророчество на украинском...\", \"coords\": [[x1,y1], [x2,y2]]}"
        )
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": photo_bytes}])
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)

        # Малювання сузір'їв
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        coords = data.get("coords", [])
        
        if coords:
            pts = [(c[0] * w / 1000, c[1] * h / 1000) for c in coords]
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i+1]], fill="yellow", width=6)
            for pt in pts:
                draw.ellipse([pt[0]-10, pt[1]-10, pt[0]+10, pt[1]+10], outline="yellow", width=4)

        out_img = BytesIO()
        img.save(out_img, format="JPEG")
        img_b64 = base64.b64encode(out_img.getvalue()).decode('utf-8')

        # Генерація голосу
        audio_b64 = ""
        try:
            voice_buf = await generate_soft_voice(data.get("text", ""), "uk")
            if voice_buf:
                audio_b64 = base64.b64encode(voice_buf.getvalue()).decode('utf-8')
        except Exception as e:
            logger.warning(f"TTS Error: {e}")

        return web.json_response({
            "text": data.get("text", ""),
            "image": img_b64,
            "audio": audio_b64
        }, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers={"Access-Control-Allow-Origin": "*"})

# Обробник вебхуків Telegram
async def handle_telegram_webhook(request):
    data = await request.json()
    await ptb_app.process_update(Update.de_json(data, ptb_app.bot))
    return web.Response()

async def on_startup(app):
    await ptb_app.initialize()
    await ptb_app.start()
    if WEBHOOK_URL:
        await ptb_app.bot.set_webhook(url=f"{WEBHOOK_URL.rstrip('/')}/webhook")
    logger.info("Бот успішно ініціалізовано!")

async def on_cleanup(app):
    await ptb_app.stop()
    await ptb_app.shutdown()

def main():
    app = web.Application()
    app.router.add_post("/api/process", handle_api_process)
    app.router.add_post("/webhook", handle_telegram_webhook)
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
