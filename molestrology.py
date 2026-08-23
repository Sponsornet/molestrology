import io
import json
import os
import re
import asyncio
import random
from PIL import Image, ImageDraw
import edge_tts
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Conflict
from aiohttp import web

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (HEALTH CHECK) ---
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
    """Очищення тексту від спецсимволів та лапок для стійкості TTS"""
    text = text.replace('*', '').replace('**', '').replace('«', '').replace('»', '').replace('"', '')
    text = re.sub(r'[^\w\s,.!?-А-Яа-яЄєІіЇїҐґ]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- ЛОГІКА БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔮 **Molestrology Bot**\n\n"
        "Надішли мені фотографію шкіри з родимками, і я прочитаю твоє астрологічне сузір'я!"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("✨ Зчитую розташування зірок та родимок (зачекайте 10-15 сек)...")
    temp_audio_path = f"voice_{update.message.message_id}.mp3"
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        width, height = image.size

        prompt = """
        Проаналізуй це фото для гумористичного додатка Molestrology. 
        1. Знайди всі родимки, ластовиння або помітні цятки на шкірі. Поверни їх координати [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
        2. Придумай неймовірно смішний, сатиричний та живий астрологічний прогноз (3-4 речення). 
           Пиши так, ніби це говорить стендап-комік або ексцентрична ворожка. Використовуй розмовні слова, жарти, окличні та питальні знаки.
        
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
        prediction_text = data.get("prediction", "Ой, та тут ціле сузір'я хаосу! Зірки радять триматися за каструлі й не вірити обіцянкам котів.")

        # Малювання сузір'я
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

        # 1. Надсилаємо підготовлене фото з текстом
        await update.message.reply_photo(photo=img_buffer, caption=f"🔮 **Твій астропрогноз:**\n\n{prediction_text}")
        
        # 2. Озвучка Edge-TTS
        clean_speech = clean_text_for_tts(prediction_text)
        if clean_speech:
            voices = ["uk-UA-LadaNeural", "uk-UA-OstapNeural"]
            chosen_voice = random.choice(voices)

            communicate = edge_tts.Communicate(clean_speech, chosen_voice, rate="+5%", pitch="+0Hz")
            
            # ВАЖЛИВО: Обов'язково з await!
            await communicate.save(temp_audio_path)

            if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 0:
                with open(temp_audio_path, "rb") as audio_file:
                    # Надсилаємо як голосове повідомлення або як аудіофайл
                    await update.message.reply_voice(voice=audio_file)

        await msg.delete()

    except Exception as e:
        print(f"Помилка обробки: {e}")
        try:
            await msg.edit_text(f"❌ Сталася помилка під час обробки: {e}")
        except:
            pass

    finally:
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception:
                pass

async def main():
    await start_web_server()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    await app.initialize()
    await app.start()

    while True:
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.updater.start_polling(drop_pending_updates=True)
            print("Бот успішно запустився і слухає повідомлення!")
            break
        except Conflict:
            print("Старий процес Render ще працює. Чекаємо 10 секунд...")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Помилка запуску: {e}")
            await asyncio.sleep(5)

    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
