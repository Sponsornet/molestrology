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
    """Очищення тексту від спецсимволів для стійкості TTS"""
    text = text.replace('*', '').replace('«', '').replace('»', '').replace('"', '')
    text = re.sub(r'[^\w\s,.!?-А-Яа-яЄєІіЇїҐґ]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- ЛОГІКА БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💘 **Molestrology Love Edition**\n\n"
        "Надішли мені фото шкіри з родимками, і я розкрию твоє сузір'я кохання, підкажу в чому йти на побачення та куди вести другу половинку!"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("✨ Зчитую любовні флюїди та родимки (зачекайте 10-15 сек)...")
    temp_audio_path = f"voice_{update.message.message_id}.mp3"
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        width, height = image.size

        prompt = """
        Ти — грайлива, дерзка, дотепна та кумедна астрологиня-сваха з додатка Molestrology. 
        Проаналізуй це фото шкіри:
        1. Знайди всі родимки або цятки. Поверни їх координати [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
        2. Напиши ВЕСЕЛИЙ, легкий і грайливий ЛЮБОВНИЙ гороскоп (3 короткі речення). 

        Вимоги до тексту:
        - ЖОДНИХ згадок про "диван", "каструлі" та "3-тю годину ночі"!
        - Придумай смішну назву для сузір'я на тему любовного вайбу (наприклад: «Сузір'я Фатального Звабника», «Марс у Гаражі», «Пікап-Майстер 3000»).
        - Дай 2 конкретні кумедні поради для побачення: у чому піти (наприклад: "одягни парадні шкарпетки", "натягни кращий штормовник", "вдягни куртку з чистими кишенями") та КУДИ запросити/піти (наприклад: "на шаурму під ліхтарем", "на романтичну заміну мастила", "у будівельний гіпермаркет", "на каву біля гаражів").
        - Подача має бути бадьорою, грайливою, з гумором і впевненим пікап-підколом.

        Поверни відповідь СУВОРО у форматі JSON:
        {
          "moles": [[ymin, xmin, ymax, xmax]],
          "prediction": "Текст прогнозу..."
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
        prediction_text = data.get("prediction", "Ого, які флюїди! Зірки радять вдягти парадні шкарпетки й вести її на шаурму — успіх гарантовано!")

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

        # 1. Фото з текстом
        await update.message.reply_photo(photo=img_buffer, caption=f"💘 **Любовний астропрогноз:**\n\n{prediction_text}")
        
        # 2. Озвучка жіночим голосом через файл (найстабільніший спосіб)
        clean_speech = clean_text_for_tts(prediction_text)
        if clean_speech:
            try:
                female_voice = "uk-UA-LadaNeural"
                communicate = edge_tts.Communicate(clean_speech, female_voice)
                
                # Запис у файл на диску
                await communicate.save(temp_audio_path)

                if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 0:
                    with open(temp_audio_path, "rb") as audio_file:
                        await update.message.reply_voice(voice=audio_file)
            except Exception as tts_error:
                print(f"Помилка TTS: {tts_error}")

        await msg.delete()

    except Exception as e:
        print(f"Помилка обробки: {e}")
        try:
            await msg.edit_text(f"❌ Сталася помилка під час обробки: {e}")
        except:
            pass

    finally:
        # Видаляємо тимчасовий аудіофайл після відправки
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
