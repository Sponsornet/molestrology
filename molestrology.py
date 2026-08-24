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
    text = text.replace('*', '').replace('«', '').replace('»', '').replace('"', '')
    text = re.sub(r'[^\w\s,.!?-А-Яа-яЄєІіЇїҐґ]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- ДИНАМІЧНІ ПРОМПТИ ---
def get_prompt(mode: str, gender: str = "не вказано") -> str:
    gender_context = ""
    if mode == "love":
        if gender == "male":
            gender_context = "Користувач — ЧОЛОВІК. Враховуй це при підборі порад зваблювання, стиля та одягу (пропонуй чоловічий стиль)."
        elif gender == "female":
            gender_context = "Користувач — ЖІНКА. Враховуй це при підборі порад зваблювання, стиля та одягу (пропонуй жіночий стиль)."

    prompts = {
        "love": f"""
            Ти — грайлива, дуже дотепна та кумедна українська астрологиня-сваха з додатка Molestrology. 
            {gender_context}
            
            Проаналізуй це фото шкіри:
            1. Знайди всі родимки або цятки [ymin, xmin, ymax, xmax] у діапазоні від 0 до 1000.
            2. Напиши ПЕРСОНАЛЬНИЙ ЛЮБОВНИЙ ГОРОСКОП (3 короткі речення). 
            
            Вимоги: 
            - Згадай геометричні особливості цього унікального візерунка (кути між точками, формацію).
            - Вигадай кумедну назву для сузір'я кохання.
            - Дай 2 кумедні порадоньки для зваблювання (що одягти і куди піти), адаптовані під стать користувача.
            - Звертайся до людини на "Ви".
            
            Поверни відповідь СУВОРО у JSON: {{"moles": [[ymin, xmin, ymax, xmax]], "prediction": "Текст..."}}
        """,
        "money": """
            Ти — дотепний фінансовий астролог з додатка Molestrology. 
            Проаналізуй це фото шкіри/долоні:
            1. Знайди всі родимки або цятки [ymin, xmin, ymax, xmax] від 0 до 1000.
            2. Напиши ПЕРСОНАЛЬНИЙ ФІНАНСОВИЙ ГОРОСКОП.
            
            Вимоги (структура з 3 коротких речень):
            - 1 речення: Опис геометрії точок (наприклад, "Цей сакральний вектор цяток відкриває квантовий портал грошового потоку...").
            - 2 речення: Весела порада про інвестиції чи кар'єру (у що інвестувати або яке рішення принесе прибуток).
            - 3 речення (В САМОМУ КІНЦІ): Легкий філософський підсумок про щедрість без нав'язування.
            
            Поверни відповідь СУВОРО у JSON: {"moles": [[ymin, xmin, ymax, xmax]], "prediction": "Текст..."}
        """,
        "pet": """
            Ти — космічний КІТ-АСТРОЛОГ з додатка Molestrology. 
            Проаналізуй це фото тваринки:
            1. Знайди всі цятки або родимки [ymin, xmin, ymax, xmax] від 0 до 1000.
            2. Напиши ПЕРСОНАЛЬНИЙ ГОРОСКОП ДЛЯ ТВАРИНКИ (3 короткі речення).
            
            Вимоги: розтлумач формацію точок на лапці/носі та вимоги зірок до господарів.
            Поверни відповідь СУВОРО у JSON: {"moles": [[ymin, xmin, ymax, xmax]], "prediction": "Текст..."}
        """
    }
    return prompts.get(mode, prompts["love"])

def get_mode_keyboard():
    keyboard = [
        [InlineKeyboardButton("💘 Любовний гороскоп", callback_data="mode_love")],
        [InlineKeyboardButton("💰 Фінансовий (Багатство)", callback_data="mode_money")],
        [InlineKeyboardButton("🐾 Папстрологія (Для улюбленців)", callback_data="mode_pet")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_gender_keyboard():
    keyboard = [
        [InlineKeyboardButton("👨 Чоловіча", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Жіноча", callback_data="gender_female")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = context.user_data.get("mode", "love")
    user_name = update.effective_user.first_name or "Шукач Долі"

    await update.message.reply_text(
        f"✨ **Вітаю, {user_name}! Ласкаво просимо до Molestrology UA!** ✨\n\n"
        "Оберіть режим гороскопу та надішліть мені фото (шкіри з родимками, долоні або улюбленця):",
        reply_markup=get_mode_keyboard(),
        parse_mode="Markdown"
    )

async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "mode_love":
        context.user_data["mode"] = "love"
        text = "💘 Обрано **Любовний режим**!\nБудь ласка, вкажіть вашу стать для точного гороскопу:"
        try:
            await query.edit_message_text(text=text, reply_markup=get_gender_keyboard(), parse_mode="Markdown")
        except:
            await query.message.reply_text(text=text, reply_markup=get_gender_keyboard(), parse_mode="Markdown")
        return

    elif query.data == "mode_money":
        context.user_data["mode"] = "money"
        text = "💰 Обрано **Фінансовий режим**! Надішліть фото долоні або шкіри."
    elif query.data == "mode_pet":
        context.user_data["mode"] = "pet"
        text = "🐾 Обрано **Папстрологію**! Надішліть фото носа, лапки чи шерсті улюбленця."

    try:
        await query.edit_message_text(text=text, parse_mode="Markdown")
    except:
        await query.message.reply_text(text=text, parse_mode="Markdown")

async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "gender_male":
        context.user_data["gender"] = "male"
        gender_text = "чоловічу"
    else:
        context.user_data["gender"] = "female"
        gender_text = "жіночу"

    text = f"✅ Обрано **{gender_text} стать**. Тепер надішліть фото шкіри з родимками!"
    
    try:
        await query.edit_message_text(text=text, parse_mode="Markdown")
    except:
        await query.message.reply_text(text=text, parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode", "love")
    gender = context.user_data.get("gender", "не вказано")
    user_name = update.effective_user.first_name or "Шукач Долі"
    
    msg = await update.message.reply_text("🔮 Зчитую сакральну геометрію точок (10-15 сек)...")
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        width, height = image.size

        prompt = get_prompt(mode, gender)

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

        # 🧠 ЗБЕРІГАЄМО ПРОГНОЗ ТА КІЛЬКІСТЬ РОДИМОК У КОНТЕКСТ КОРИСТУВАЧА
        context.user_data["last_prediction"] = prediction_text
        context.user_data["moles_count"] = len(moles)

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

        keyboard = [
            [InlineKeyboardButton("☕ Пригостити астролога (Monobank)", url=MONO_BANK_URL)],
            [InlineKeyboardButton("🔄 Змінити режим гороскопу", callback_data="show_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption_text = (
            f"✨ **Персональний астропрогноз для {user_name}:**\n\n{prediction_text}\n\n"
            f"💬 *Можете поставити мені будь-яке запитання щодо ваших родимок або поради у чаті!*"
        )

        await update.message.reply_photo(
            photo=img_buffer, 
            caption=caption_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
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

# --- ОБРОБНИК ТЕКСТОВИХ ПИТАНЬ З ПРИВ'ЯЗКОЮ ДО РОДИМОК ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_name = update.effective_user.first_name or "Шукач Долі"
    gender = context.user_data.get("gender", "не вказано")
    last_prediction = context.user_data.get("last_prediction", "Фото ще не надсилалося.")
    moles_count = context.user_data.get("moles_count", 0)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    prompt = f"""
        Ти — грайлива, дотепна, але мудра та підтримлива українська астрологиня з додатка Molestrology.
        
        Контекст користувача:
        - Ім'я: {user_name}
        - Стать: {gender}
        - Кількість виявлених родимок/точок на останньому фото: {moles_count}
        - Останній згенерований аналіз родимок/гороскоп: "{last_prediction}"

        Користувач запитує: "{user_text}"

        Твоє завдання:
        - Дай відповідь або пораду, ОБОРОЗ'ЯЗКОВО посилаючись на родимки користувача, їх формацію або попередній опис сузір'я з аналізу.
        - Відповідай дотепно, із гумором та астрологічним шармом.
        - Тримай відповідь у межах 2-4 речень.
    """

    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )
        await update.message.reply_text(response.text, parse_mode="Markdown")
    except Exception as e:
        print(f"Помилка текстового обробника: {e}")
        await update.message.reply_text("Зірки трохи збилися з ритму. Спробуйте поставити питання ще раз! ✨")

async def show_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Оберіть бажаний режим для наступного фото:",
        reply_markup=get_mode_keyboard()
    )

async def main():
    await start_web_server()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(set_gender, pattern="^gender_"))
    app.add_handler(CallbackQueryHandler(show_menu_callback, pattern="^show_menu$"))
    
    # Обробка фото та текстів
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
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
