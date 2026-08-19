import io
import json
import os
import asyncio
from PIL import Image, ImageDraw
from gtts import gTTS
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web

# Отримання ключів зі змінних оточення (Environment Variables)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Ініціалізація клієнта Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

# --- ВЕБ-СЕРВЕР ДЛЯ ПІДТРИМКИ ПОРТУ RENDER ---
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

# --- ЛОГІКА ТЕЛЕГРАМ-БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔮 **Molestrology Bot**\n\n"
        "Надішли мені фотографію шкіри з родимками, і я прочитаю твоє астрологічне сузір'я!"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("✨ Зчитую розташування зірок та родимок (зачекайте 15-20 сек)...")
    
    try:
        # Завантаження фото від користувача
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        width, height = image.size

        # Запит до Gemini
        prompt = """
        Проаналізуй це фото для гумористичного додатка Molestrology. 
        1. Знайди всі родимки, ластовиння або помітні цятки на шкірі. Поверни їх координати [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
        2. Придумай короткий, кумедний, іронічний та містичний астрологічний прогноз (3-4 речення) на основі з'єднаних родимок-сузір'їв.
        
        Поверни відповідь СУВОРО у форматі JSON:
        {
          "moles": [[ymin, xmin, ymax, xmax]],
          "prediction": "Текст прогнозу українською мовою..."
        }
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[image, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        data = json.loads(response.text)
        moles = data.get("moles", [])
        prediction_text = data.get("prediction", "Зірки мовчать, але ваші родимки утворюють дивовижне сузір'я!")

        # Малювання точок та ліній між родимками
        draw = ImageDraw.Draw(image)
        centers = []

        for mole in moles:
            ymin, xmin, ymax, xmax = mole
            cx = int(((xmin + xmax) / 2) / 1000 * width)
            cy = int(((ymin + ymax) / 2) / 1000 * height)
            centers.append((cx, cy))
            # Малюємо червоний круг з жовтою обводкою
            draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill="red", outline="yellow", width=2)

        # З'єднуємо родимки блакитними лініями сузір'я
        if len(centers) > 1:
            draw.line(centers, fill="cyan", width=4)
            if len(centers) > 2:
                draw.line([centers[-1], centers[0]], fill="cyan", width=4)

        # Збереження картинки в буфер
        img_buffer = io.BytesIO()
        image.save(img_buffer, format="JPEG")
        img_buffer.seek(0)

        # Озвучка через gTTS
        tts = gTTS(text=prediction_text, lang='uk')
        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)
        audio_buffer.name = "molestrology_voice.mp3"

        # Відправка фото та аудіо в Telegram
        await update.message.reply_photo(photo=img_buffer, caption=f"🔮 **Твій астропрогноз:**\n\n{prediction_text}")
        await update.message.reply_voice(voice=audio_buffer)
        
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Сталася помилка під час обробки: {e}")

async def main():
    # Запуск веб-сервера для Render
    await start_web_server()
    
    # Запуск Telegram-бота
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
