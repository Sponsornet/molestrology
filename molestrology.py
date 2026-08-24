import io
import json
import os
import re
import asyncio
from PIL import Image, ImageDraw
import edge_tts
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import Conflict
from aiohttp import web

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 🔗 Вставте сюди ваше посилання на банку Monobank!
MONO_BANK_URL = "https://send.monobank.ua/"

client = genai.Client(api_key=GEMINI_API_KEY)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (HEALTH CHECK) ---
async def handle_ping(request):
    return web.Response(text="Molestrology UA is running!")

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

# --- ПЕРСОНАЛІЗОВАНІ ПРОМПТИ ПІД РІЗНІ РЕЖИМИ ---
PROMPTS = {
    "love": """
        Ти — грайлива, дуже дотепна та кумедна українська астрологиня-сваха з додатка Molestrology. 
        Проаналізуй це фото шкіри:
        1. Знайди всі родимки або цятки [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
        2. Напиши ГЛИБОКО ПЕРСОНАЛЬНИЙ ЛЮБОВНИЙ ГОРОСКОП (3 короткі речення). 
        
        Вимоги: 
        - Обов'язково згадай ПЕРСОНАЛЬНІ геометричні особливості цього візерунка (наприклад: "Кут між першими родимками вказує на...", "Ця унікальна трикутна формація точок на вашій шкірі означає...").
        - Вигадай свіжу унікальну назву для сузір'я кохання.
        - Дай 2 кумедні порадоньки для зваблювання (що оригінального одягти і куди конкретно піти).
        - Звертайся до людини на "Ви".
        
        Поверни відповідь СУВОРО у JSON: {"moles": [[ymin, xmin, ymax, xmax]], "prediction": "Текст..."}
    """,
    "money": """
        Ти — ексцентричний, дотепний та глибокий фінансовий астролог з додатка Molestrology. 
        Проаналізуй це фото шкіри/долоні:
        1. Знайди всі родимки або цятки [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
        2. Напиши ПЕРСОНАЛЬНИЙ ФІНАНСОВИЙ ГОРОСКОП БАГАТСТВА ТА ЩЕДРОСТІ (3 короткі речення).
        
        Вимоги:
        - Підкресли УНІКАЛЬНІСТЬ саме цієї геометрії точок (наприклад: "Вектор між цими цятками утворює сакральний канал достатку...").
        - Справжнє багатство — це не лише прибуток, а й КРУГОВОРОТ ГРОШЕЙ ТА ЩЕДРІСТЬ! Поясни, що чим більше людина ділиться (донатить, підтримує інших, робить подарунки), тим більше Всесвіт повертає їй у формі несподіваного грошового потоку.
        - Дай 1 кумедну пораду щодо інвестицій і 1 пораду про щедрий вчинок, який активує багатство.
        
        Поверни відповідь СУВОРО у JSON: {"moles": [[ymin, xmin, ymax, xmax]], "prediction": "Текст..."}
    """,
    "pet": """
        Ти — космічний КІТ-АСТРОЛОГ з додатка Molestrology. 
        Проаналізуй це фото шерсті, лапки або носа тваринки:
        1. Знайди всі цятки або родимки [ymin, xmin, ymax, xmax] від 0 до 1000.
        2. Напиши ПЕРСОНАЛЬНИЙ ГОРОСКОП ДЛЯ ЦІЄЇ ТВАРИНКИ (3 короткі речення).
        
        Вимоги:
        - Розтлумач унікальну формацію точок на лапці/носі.
        - Передай сакральні вимоги зірок до господарів (+3 смаколики, щедрість на ласку та обійми).
        
        Поверни відповідь СУВОРО у JSON: {"moles": [[ymin, xmin, ymax, xmax]], "prediction": "Текст..."}
    """
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "love"
    
    keyboard = [
        [InlineKeyboardButton("💘 Любовний гороскоп", callback_data="mode_love")],
        [InlineKeyboardButton("💰 Фінансовий (Багатство та Щедрість)", callback_data="mode_money")],
        [InlineKeyboardButton("🐾 Папстрологія (Для улюбленців)", callback_data="mode_pet")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    user_name = update.effective_user.first_name or "Шукач Долі"

    await update.message.reply_text(
        f"✨ **Вітаю, {user_name}! Ласкаво просимо до Molestrology UA!** ✨\n\n"
        "Оберіть режим персонального гороскопу та надішліть мені фото (шкіри з родимками, долоні або лапки/носа тваринки):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "mode_love":
        context.user_data["mode"] = "love"
        text = "💘 Обрано **Любовний режим**! Надішліть фото шкіри з родимками."
    elif query.data == "mode_money":
        context.user_data["mode"] = "money"
        text = "💰 Обрано **Фінансовий режим (Багатство та Щедрість)**! Надішліть фото долоні або шкіри."
    elif query.data == "mode_pet":
        context.user_data["mode"] = "pet"
        text = "🐾 Обрано **Папстрологію**! Надішліть фото носа, лапки чи шерсті улюбленця."

    await query.edit_message_text(text=text, parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode", "love")
    user_name = update.effective_user.first_name or "Шукач Долі"
    
    msg = await update.message.reply_text("🔮 Сканую сакральну геометрію точок (10-15 сек)...")
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        width, height = image.size

        prompt = PROMPTS.get(mode, PROMPTS["love"])

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[image, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=1.0
            )
        )

        data = json.loads(response.text)
        moles = data.get("moles", [])
        prediction_text = data.get("prediction", "Зірки бачать шалений магнетизм!")

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

        # Кнопка донату
        keyboard = [
            [InlineKeyboardButton("☕ Пригостити астролога кавою (Monobank)", url=MONO_BANK_URL)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Відправка фото з персоналізованим текстом
        caption_text = f"✨ **Персональний астропрогноз для {user_name}:**\n\n{prediction_text}"

        await update.message.reply_photo(
            photo=img_buffer, 
            caption=caption_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        # Озвучка жіночим голосом (Polina)
        clean_speech = clean_text_for_tts(prediction_text)
        if clean_speech:
            try:
                female_voice = "uk-UA-PolinaNeural"
                communicate = edge_tts.Communicate(clean_speech, female_voice)
                
                audio_stream = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_stream.write(chunk["data"])

                audio_stream.seek(0)
                if audio_stream.getbuffer().nbytes > 0:
                    audio_stream.name = "voice.ogg"
                    await update.message.reply_voice(voice=audio_stream)
            except Exception as tts_err:
                print(f"Помилка TTS: {tts_err}")

        await msg.delete()

    except Exception as e:
        print(f"Помилка обробки: {e}")
        try:
            await msg.edit_text(f"❌ Помилка аналізу: {e}")
        except:
            pass

async def main():
    await start_web_server()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^mode_"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    await app.initialize()
    await app.start()

    while True:
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.updater.start_polling(drop_pending_updates=True)
            print("UA Бот успішно запущено!")
            break
        except Conflict:
            print("Виявлено старий процес Render. Чекаємо 15 секунд...")
            await asyncio.sleep(15)
        except Exception as e:
            print(f"Помилка запуску: {e}")
            await asyncio.sleep(5)

    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
