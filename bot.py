import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import whisper
import os
import tempfile
import requests
import asyncpg
from datetime import datetime, date
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "@shturm_23_bot"
LLM_API_URL = "http://llm:8000/generate"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# model = whisper.load_model("medium")

# Настройки подключения к PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "bot_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "bot_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "bot_db")

# Глобальная переменная для пула подключений
db_pool = None

# Инициализация базы данных PostgreSQL
async def init_db():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DB
        )
        async with db_pool.acquire() as conn:
            # Создаём таблицу users
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    full_name TEXT NOT NULL
                )
            ''')
            # Создаём таблицу trainings
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS trainings (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    user_id BIGINT NOT NULL,
                    full_name TEXT NOT NULL,
                    training_type TEXT NOT NULL,
                    training_date DATE NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
        logger.info("PostgreSQL database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL database: {str(e)}")
        raise

async def get_full_name(user_id):
    try:
        async with db_pool.acquire() as conn:
            logger.info(f"Executing SELECT for user_id {user_id}")
            result = await conn.fetchrow(
                "SELECT full_name FROM users WHERE user_id = $1", user_id
            )
            full_name = result['full_name'] if result else None
            logger.info(f"Retrieved full_name for user_id {user_id}: {full_name}")
            return full_name
    except Exception as e:
        logger.error(f"Error retrieving full_name for user_id {user_id}: {str(e)}")
        return None

async def set_full_name(user_id, full_name):
    try:
        async with db_pool.acquire() as conn:
            logger.info(f"Inserting full_name for user_id {user_id}: {full_name}")
            await conn.execute(
                "INSERT INTO users (user_id, full_name) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET full_name = $2",
                user_id, full_name
            )
            logger.info(f"Successfully set full_name for user_id {user_id}: {full_name}")
    except Exception as e:
        logger.error(f"Error setting full_name for user_id {user_id}: {str(e)}")
        raise

async def write_to_db(timestamp, user_id, full_name, training_type, training_date):
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO trainings (timestamp, user_id, full_name, training_type, training_date)
                VALUES ($1, $2, $3, $4, $5)
                ''',
                timestamp, user_id, full_name, training_type, training_date
            )
            logger.info(f"Training recorded for user_id {user_id}: {training_type} on {training_date}")
    except Exception as e:
        logger.error(f"Error recording training for user_id {user_id}: {str(e)}")
        raise

# Определение состояний для FSM
class RecordTraining(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_training_type = State()
    waiting_for_date = State()

@dp.message(Command("start"))
async def send_welcome(message: Message):
    record_button = InlineKeyboardButton(text="отметить тренировку", callback_data="record_training")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[record_button]])
    await message.answer(
        f"Привет! Я могу:\n"
        f"- Распознавать голосовые сообщения и превращать их в текст.\n"
        f"- Отвечать на текстовые сообщения, если упомянуть меня: {BOT_NAME}\n"
        f"- Записывать тренировки",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

# @dp.message(F.voice)
# async def handle_voice(message: Message):
#     try:
#         file_id = message.voice.file_id
#         file = await bot.get_file(file_id)
#         file_path = file.file_path
#         with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as temp_file:
#             temp_file_path = temp_file.name
#             await bot.download_file(file_path, temp_file_path)
#         wav_path = temp_file_path.replace('.ogg', '.wav')
#         os.system(f"ffmpeg -i {temp_file_path} -acodec pcm_s16le -ar 16000 {wav_path}")
#         result = model.transcribe(wav_path)
#         transcribed_text = result["text"]
#         await message.reply(f"Распознанный текст:\n{transcribed_text}", parse_mode=ParseMode.HTML)
#         os.remove(temp_file_path)
#         os.remove(wav_path)
#     except Exception as e:
#         await message.answer(f"Произошла ошибка: {str(e)}", parse_mode=ParseMode.HTML)

@dp.message((F.text.startswith(BOT_NAME)) | (F.reply_to_message.from_user.id == bot.id))
async def handle_text(message: Message):
    try:
        text = message.text.replace(BOT_NAME, "").strip()
        if not text:
            await message.reply("Пожалуйста, напиши что-нибудь после моего имени!", parse_mode=ParseMode.HTML)
            return
        prompt = f"[INST] <<SYS>> Ты полезный ассистент. Отвечай кратко и по делу. Предпочтительно на русском языке. <<SYS>> {text} [/INST]"
        response = requests.post(
            LLM_API_URL,
            json={"prompt": prompt, "max_tokens": 512, "temperature": 0.7, "top_p": 0.95}
        )
        response.raise_for_status()
        reply_text = response.json()["text"]
        await message.reply(reply_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply(f"Произошла ошибка: {str(e)}", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "record_training")
async def start_record_training(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    full_name = await get_full_name(user_id)
    if full_name is None:
        await state.set_state(RecordTraining.waiting_for_full_name)
        await callback_query.message.answer("Пожалуйста, введите ваше ФИО:")
    else:
        await state.update_data(full_name=full_name)
        await ask_training_type(callback_query.message, state)

async def ask_training_type(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="скалодром", callback_data="training_type:скалодром"),
            InlineKeyboardButton(text="ОФП", callback_data="training_type:ОФП"),
            InlineKeyboardButton(text="Техническая тренировка", callback_data="training_type:Техническая тренировка")
        ]
    ])
    await message.answer("Выберите вид тренировки:", reply_markup=keyboard)
    await state.set_state(RecordTraining.waiting_for_training_type)

@dp.callback_query(F.data.startswith("training_type:"))
async def select_training_type(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    training_type = callback_query.data.split(":")[1]
    await state.update_data(training_type=training_type)
    await ask_date(callback_query.message, state)

async def ask_date(message: Message, state: FSMContext):
    calendar = SimpleCalendar()
    await message.answer("Выберите дату тренировки:", reply_markup=await calendar.start_calendar())
    await state.set_state(RecordTraining.waiting_for_date)

@dp.callback_query(SimpleCalendarCallback.filter())
async def process_date_selection(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    selected, date = await SimpleCalendar().process_selection(callback_query, callback_data)
    if selected:
        # Сохраняем date как объект datetime.date, а не строку
        await state.update_data(training_date=date)
        data = await state.get_data()
        logger.info(f"State data: {data}")
        full_name = data['full_name']
        training_type = data['training_type']
        training_date = data['training_date']
        user_id = callback_query.from_user.id
        timestamp = datetime.now()
        try:
            await write_to_db(timestamp, user_id, full_name, training_type, training_date)
            await callback_query.message.answer("Тренировка записана!")
        except Exception as e:
            await callback_query.message.answer(f"Произошла ошибка при записи: {str(e)}")
        await state.clear()  # Завершаем состояние после записи тренировки

@dp.message(RecordTraining.waiting_for_full_name)
async def process_full_name(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if not full_name:
        await message.answer("ФИО не может быть пустым. Пожалуйста, введите ваше ФИО:")
        return
    user_id = message.from_user.id
    try:
        await set_full_name(user_id, full_name)
        # Проверяем, что ФИО действительно сохранено
        saved_full_name = await get_full_name(user_id)
        if saved_full_name != full_name:
            await message.answer("Произошла ошибка при сохранении ФИО. Попробуйте снова.")
            return
        await state.update_data(full_name=full_name)
        await ask_training_type(message, state)
    except Exception as e:
        await message.answer(f"Произошла ошибка при сохранении ФИО: {str(e)}")
        logger.error(f"Failed to set full_name for user_id {user_id}: {str(e)}")

@dp.message(Command("setname"))
async def set_name_command(message: Message, state: FSMContext):
    await state.set_state(RecordTraining.waiting_for_full_name)
    await message.answer("Пожалуйста, введите ваше новое ФИО:")

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Я бот для записи тренировок и общения!\n"
        "Доступные команды:\n"
        "/start - Начать работу\n"
        "/setname - Изменить ФИО\n"
        "/help - Показать справку\n"
        "/info - Информация о боте\n"
        "/stats - Показать статистику тренировок\n"
        f"Или упомяни меня: {BOT_NAME} <твой вопрос>",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("info"))
async def info_command(message: Message):
    await message.answer(
        "Я бот Shturm, создан для помощи в записи тренировок.\n"
        "Могу:\n"
        "- Записывать тренировки (скалодром, ОФП, техническая тренировка)\n"
        "- Распознавать голосовые сообщения\n"
        "- Отвечать на вопросы\n"
        "Версия: 1.0",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("stats"))
async def stats_command(message: Message):
    user_id = message.from_user.id
    full_name = await get_full_name(user_id)
    
    if full_name is None:
        await message.answer(
            "У вас не указано ФИО. Пожалуйста, установите его с помощью команды /setname.",
            parse_mode=ParseMode.HTML
        )
        return

    # Подсчитываем тренировки из базы данных
    training_stats = {"скалодром": 0, "ОФП": 0, "Техническая тренировка": 0}
    total_trainings = 0
    
    try:
        async with db_pool.acquire() as conn:
            records = await conn.fetch(
                "SELECT training_type FROM trainings WHERE user_id = $1", user_id
            )
            if not records:
                await message.answer(
                    f"У вас пока нет записанных тренировок, {full_name}.",
                    parse_mode=ParseMode.HTML
                )
                return

            for record in records:
                training_type = record['training_type']
                if training_type in training_stats:
                    training_stats[training_type] += 1
                total_trainings += 1

        # Формируем сообщение со статистикой
        stats_message = f"📊 Статистика тренировок для {full_name}:\n"
        stats_message += f"Всего тренировок: {total_trainings}\n"
        for training_type, count in training_stats.items():
            stats_message += f"{training_type}: {count}\n"

        await message.answer(stats_message, parse_mode=ParseMode.HTML)

    except Exception as e:
        await message.answer(
            f"Произошла ошибка при получении статистики: {str(e)}",
            parse_mode=ParseMode.HTML
        )

async def main():
    await init_db()  # Инициализируем базу данных
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())