import io
import json
import os
import re
import asyncio
from PIL import Image, ImageDraw
import edge_tts
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

# --- ВЕБ-СЕРВЕР ДЛЯ РЕНДЕРА ---
async def handle_ping(request):
    return web.Response(text="Molestrology Bot is active!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

def clean_text_for_tts(text: str) -> str:
    """Очищає текст від емодзі, спецсимволів та латини для чистого озвучення"""
    text = re.sub(r'[^\w\s,.!?-А-Яа-яЄєІіЇїҐґ]', '', text)
    text = re.sub(r'[a-zA-Z]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- ЛОГІКА БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔮 **Molestrology Bot**\n\n"
        "Надішли мені фотографію шкіри з родимками, і я прочитаю твоє астрологічне сузір'я!"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("✨ Зчитую розташування зірок та родимок (зачекайте 15-20 сек)...")
    temp_audio_path = f"voice_{update.message.message_id}.mp3"
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        width, height = image.size

        prompt = """
        Проаналізуй це фото для гумористичного додатка Molestrology. 
        1. Знайди всі родимки, ластовиння або помітні цятки на шкірі. Поверни їх координати [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
        2. Придумай СУПЕР ВЕСЕЛИЙ, комічний та іронічний астрологічний прогноз (3-4 речення). 
           Обов'язково додавай емоційні вигуки українською мовою (наприклад: "Ого!", "Нічого собі!", "Ага!", "Охо-хо!", "Увага!"), більше знаків оклику (!) та питальних речень, щоб озвучка звучала максимально весело та емоційно!
        
        Поверни відповідь СУВОРО у форматі JSON:
        {
          "moles": [[ymin, xmin, ymax, xmax]],
          "prediction": "Текст прогнозу українською мовою..."
        }
        """

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[image, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        data = json.loads(response.text)
        moles = data.get("moles", [])
        prediction_text = data.get("prediction", "Ого! Зірки мовчать, але ваші родимки утворюють дивовижне сузір'я!")

        # Малюємо точки та сузір'я
        draw = ImageDraw.Draw(image)
        centers = []

        for mole in moles:
            ymin, xmin, ymax, xmax = mole
            cx = int(((xmin + xmax) / 2) / 1000 * width)
            cy = int(((ymin + ymax) / 2) / 1000 * height)
            centers.append((cx, cy))
            draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill="red", outline="yellow", width=2)

        if len(centers) > 1:
            draw.line(centers, fill="cyan", width=4)
            if len(centers) > 2:
                draw.line([centers[-1], centers[0]], fill="cyan", width=4)

        img_buffer = io.BytesIO()
        image.save(img_buffer, format="JPEG")
        img_buffer.seek(0)

        # Очищаємо текст для озвучення
        clean_speech_text = clean_text_for_tts(prediction_text)

        # Стабільний запуск PolinaNeural з прискоренням та тоном без обгортки в SSML
        voice = "uk-UA-PolinaNeural"
        communicate = edge_tts.Communicate(clean_speech_text, voice, rate="+6%", pitch="+4Hz")
        await communicate.save(temp_audio_path)

        # Відправка фото та голосового повідомлення
        await update.message.reply_photo(photo=img_buffer, caption=f"🔮 **Твій астропрогноз:**\n\n{prediction_text}")
        
        with open(temp_audio_path, "rb") as audio_file:
            await update.message.reply_voice(voice=audio_file, filename="voice.ogg")
        
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Сталася помилка під час обробки: {e}")

    finally:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

async def main():
    await start_web_server()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
