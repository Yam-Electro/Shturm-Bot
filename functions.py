import json
import os
import tempfile
import requests
import asyncpg
from datetime import datetime, date, timedelta
import whisper
import logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from telegram_bot_calendar import DetailedTelegramCalendar

# Настройка логирования
logger = logging.getLogger(__name__)

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
            logger.info("Table 'users' created or already exists.")

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
            logger.info("Table 'trainings' created or already exists.")

            # Создаём таблицу new_users для хранения новых пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS new_users (
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    PRIMARY KEY (user_id, chat_id)
                )
            ''')
            logger.info("Table 'new_users' created or already exists.")

        logger.info("PostgreSQL database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL database: {str(e)}")
        raise

async def add_new_user(user_id: int, chat_id: int):
    """Добавляет пользователя в список новых пользователей в базе данных."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO new_users (user_id, chat_id) VALUES ($1, $2) ON CONFLICT (user_id, chat_id) DO NOTHING",
                user_id, chat_id
            )
            logger.info(f"User {user_id} added to new_users in chat {chat_id}.")
    except Exception as e:
        logger.error(f"Error adding user {user_id} to new_users in chat {chat_id}: {str(e)}")
        raise

async def is_new_user(user_id: int, chat_id: int) -> bool:
    """Проверяет, есть ли пользователь в списке новых пользователей."""
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT 1 FROM new_users WHERE user_id = $1 AND chat_id = $2",
                user_id, chat_id
            )
            logger.info(f"Checked if user {user_id} is in new_users in chat {chat_id}: {'Yes' if result else 'No'}")
            return result is not None
    except Exception as e:
        logger.error(f"Error checking if user {user_id} is in new_users in chat {chat_id}: {str(e)}")
        raise

async def remove_new_user(user_id: int, chat_id: int):
    """Удаляет пользователя из списка новых пользователей."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM new_users WHERE user_id = $1 AND chat_id = $2",
                user_id, chat_id
            )
            logger.info(f"User {user_id} removed from new_users in chat {chat_id}.")
    except Exception as e:
        logger.error(f"Error removing user {user_id} from new_users in chat {chat_id}: {str(e)}")
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

async def get_training_stats(user_id):
    training_stats = {"скалодром": 0, "ОФП": 0, "Техническая тренировка": 0}
    total_trainings = 0
    try:
        async with db_pool.acquire() as conn:
            records = await conn.fetch(
                "SELECT training_type FROM trainings WHERE user_id = $1", user_id
            )
            if not records:
                return None, 0, training_stats
            for record in records:
                training_type = record['training_type']
                if training_type in training_stats:
                    training_stats[training_type] += 1
                total_trainings += 1
        return training_stats, total_trainings, None
    except Exception as e:
        logger.error(f"Error retrieving stats for user_id {user_id}: {str(e)}")
        return None, 0, str(e)

# Функция для обработки голосовых сообщений
async def handle_voice_message(message, bot, model):
    try:
        file_id = message.voice.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as temp_file:
            temp_file_path = temp_file.name
            await bot.download_file(file_path, temp_file_path)
        wav_path = temp_file_path.replace('.ogg', '.wav')
        os.system(f"ffmpeg -i {temp_file_path} -acodec pcm_s16le -ar 16000 {wav_path}")
        result = model.transcribe(wav_path)
        transcribed_text = result["text"]
        os.remove(temp_file_path)
        os.remove(wav_path)
        return transcribed_text, None
    except Exception as e:
        logger.error(f"Error handling voice message: {str(e)}")
        return None, str(e)

# Функция для обработки текстовых сообщений
async def handle_text_message(message, bot_name, llm_api_url):
    try:
        text = message.text.replace(bot_name, "").strip()
        if not text:
            return "Пожалуйста, напиши что-нибудь после моего имени!", None
        prompt = f"[INST] <<SYS>> Ты полезный ассистент. Отвечай кратко и по делу. Предпочтительно на русском языке. <<SYS>> {text} [/INST]"
        response = requests.post(
            llm_api_url,
            json={"prompt": prompt, "max_tokens": 512, "temperature": 0.7, "top_p": 0.95}
        )
        response.raise_for_status()
        reply_text = response.json()["text"]
        return reply_text, None
    except Exception as e:
        logger.error(f"Error handling text message: {str(e)}")
        return None, str(e)

# Функция для преобразования значений text в строковый формат
def ensure_text_is_string(keyboard_dict):
    if "inline_keyboard" not in keyboard_dict:
        return keyboard_dict
    for row in keyboard_dict["inline_keyboard"]:
        for button in row:
            if "text" in button:
                button["text"] = str(button["text"])
    return keyboard_dict

# Функция для создания календаря
def create_calendar():
    today = date.today()
    min_date = today - timedelta(days=14)  # Минимальная дата — 14 дней назад
    max_date = today  # Максимальная дата — сегодня
    calendar = DetailedTelegramCalendar(
        calendar_id=1,
        locale='ru',  # Устанавливаем русский язык
        min_date=min_date,
        max_date=max_date
    )
    return calendar

# Функция для получения клавиатуры календаря
def get_calendar_keyboard(calendar):
    keyboard_data, _ = calendar.build()
    keyboard_dict = json.loads(keyboard_data)
    keyboard_dict = ensure_text_is_string(keyboard_dict)
    keyboard = InlineKeyboardMarkup(**keyboard_dict)
    return keyboard

# Функция для обработки выбора даты
def process_calendar_selection(callback_data, min_date, max_date):
    calendar = DetailedTelegramCalendar(
        calendar_id=1,
        locale='ru',
        min_date=min_date,
        max_date=max_date
    )
    result, keyboard_data, step = calendar.process(callback_data)
    if not result:
        keyboard_dict = json.loads(keyboard_data)
        keyboard_dict = ensure_text_is_string(keyboard_dict)
        keyboard = InlineKeyboardMarkup(**keyboard_dict)
        return None, keyboard
    return result, None