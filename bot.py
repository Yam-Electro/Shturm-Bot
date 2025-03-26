import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import whisper
import os
import tempfile
import requests
import sqlite3
from datetime import datetime
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback
import csv


BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "@shturm_23_bot"
LLM_API_URL = "http://llm:8000/generate"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

model = whisper.load_model("medium")

# Настройка базы данных SQLite
DB_PATH = '/app/data/users.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users
                  (user_id INTEGER PRIMARY KEY, full_name TEXT)''')
conn.commit()

def get_full_name(user_id):
    cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None

def set_full_name(user_id, full_name):
    cursor.execute("INSERT OR REPLACE INTO users (user_id, full_name) VALUES (?, ?)", (user_id, full_name))
    conn.commit()

CSV_FILE = '/app/data/trainings.csv'
def write_to_csv(timestamp, full_name, training_type, training_date):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, 'a', newline='') as csvfile:
        fieldnames = ['Отметка времени', 'ФИО', 'Вид тренировки', 'Дата тренировки']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow({
            'Отметка времени': timestamp,
            'ФИО': full_name,
            'Вид тренировки': training_type,
            'Дата тренировки': training_date
        })

# Определение состояний для FSM
class RecordTraining(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_training_type = State()
    waiting_for_date = State()

# Обработчик команды /start
@dp.message(Command("start"))
async def send_welcome(message: Message):
    record_button = InlineKeyboardButton("отметить тренировку", callback_data="record_training")
    keyboard = InlineKeyboardMarkup().add(record_button)
    await message.answer(
        f"Привет! Я могу:\n"
        f"- Распознавать голосовые сообщения и превращать их в текст.\n"
        f"- Отвечать на текстовые сообщения, если упомянуть меня: {BOT_NAME}\n"
        f"- Записывать тренировки",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

@dp.message(F.voice)
async def handle_voice(message: Message):
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

        await message.reply(f"Распознанный текст:\n{transcribed_text}", parse_mode=ParseMode.HTML)

        os.remove(temp_file_path)
        os.remove(wav_path)

    except Exception as e:
        await message.answer(f"Произошла ошибка: {str(e)}", parse_mode=ParseMode.HTML)

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

# Обработчик кнопки "отметить тренировку"
@dp.callback_query(F.data == "record_training")
async def start_record_training(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    full_name = get_full_name(user_id)
    if full_name is None:
        await RecordTraining.waiting_for_full_name.set()
        await callback_query.message.answer("Пожалуйста, введите ваше ФИО:")
    else:
        await state.update_data(full_name=full_name)
        await ask_training_type(callback_query.message, state)

async def ask_training_type(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("скалодром", callback_data="training_type:скалодром"))
    keyboard.add(InlineKeyboardButton("ОФП", callback_data="training_type:ОФП"))
    await message.answer("Выберите вид тренировки:", reply_markup=keyboard)
    await RecordTraining.waiting_for_training_type.set()

@dp.callback_query(F.data.startswith("training_type:"))
async def select_training_type(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    training_type = callback_query.data.split(":")[1]
    await state.update_data(training_type=training_type)
    await ask_date(callback_query.message, state)

async def ask_date(message: Message, state: FSMContext):
    calendar = SimpleCalendar()
    await message.answer("Выберите дату тренировки:", reply_markup=await calendar.start_calendar())
    await RecordTraining.waiting_for_date.set()

@dp.callback_query(SimpleCalendarCallback.filter())
async def process_date_selection(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    selected, date = await SimpleCalendar().process_selection(callback_query, callback_data)
    if selected:
        await state.update_data(training_date=date.strftime("%Y-%m-%d"))
        data = await state.get_data()
        full_name = data['full_name']
        training_type = data['training_type']
        training_date = data['training_date']
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            write_to_csv(timestamp, full_name, training_type, training_date)
            await callback_query.message.answer("Тренировка записана!")
        except Exception as e:
            await callback_query.message.answer(f"Произошла ошибка при записи: {str(e)}")

@dp.message(RecordTraining.waiting_for_full_name)
async def set_full_name(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if not full_name:
        await message.answer("ФИО не может быть пустым. Пожалуйста, введите ваше ФИО:")
        return
    user_id = message.from_user.id
    set_full_name(user_id, full_name)
    await state.update_data(full_name=full_name)
    await ask_training_type(message, state)

@dp.message(Command("setname"))
async def set_name_command(message: Message, state: FSMContext):
    await RecordTraining.waiting_for_full_name.set()
    await message.answer("Пожалуйста, введите ваше новое ФИО:")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())        