import asyncio
import sys
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import whisper
from datetime import datetime, date, timedelta
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import logging
import functions as f

# Добавляем отладочный вывод для проверки путей
print("Current working directory:", os.getcwd())
print("sys.path:", sys.path)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "@shturm_23_bot"
LLM_API_URL = "http://llm:8000/generate"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# model = whisper.load_model("medium")

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

@dp.message(F.voice)
async def handle_voice(message: Message):
    transcribed_text, error = await f.handle_voice_message(message, bot, model)
    if error:
        await message.answer(f"Произошла ошибка: {error}", parse_mode=ParseMode.HTML)
    else:
        await message.reply(f"Распознанный текст:\n{transcribed_text}", parse_mode=ParseMode.HTML)

@dp.message((F.text.startswith(BOT_NAME)) | (F.reply_to_message.from_user.id == bot.id))
async def handle_text(message: Message):
    reply_text, error = await f.handle_text_message(message, BOT_NAME, LLM_API_URL)
    if error:
        await message.reply(f"Произошла ошибка: {error}", parse_mode=ParseMode.HTML)
    else:
        await message.reply(reply_text, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "record_training")
async def start_record_training(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    full_name = await f.get_full_name(user_id)
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
    # Сохраняем сообщение с выбором тренировки
    sent_message = await message.answer("Выберите вид тренировки:", reply_markup=keyboard)
    # Сохраняем message_id в состоянии
    await state.update_data(training_type_message_id=sent_message.message_id)
    await state.set_state(RecordTraining.waiting_for_training_type)

@dp.callback_query(F.data.startswith("training_type:"))
async def select_training_type(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    training_type = callback_query.data.split(":")[1]
    await state.update_data(training_type=training_type)
    await ask_date(callback_query.message, state)

async def ask_date(message: Message, state: FSMContext):
    calendar = f.create_calendar()
    keyboard = f.get_calendar_keyboard(calendar)
    # Сохраняем сообщение с календарем
    sent_message = await message.answer("Выберите дату тренировки:", reply_markup=keyboard)
    # Сохраняем message_id в состоянии
    await state.update_data(date_message_id=sent_message.message_id)
    await state.set_state(RecordTraining.waiting_for_date)

@dp.callback_query(lambda c: c.data and c.data.startswith('cbcal_'))  # Обрабатываем callback от календаря
async def process_date_selection(callback_query: CallbackQuery, state: FSMContext):
    today = date.today()
    min_date = today - timedelta(days=14)
    max_date = today
    selected_date, keyboard = f.process_calendar_selection(callback_query.data, min_date, max_date)
    
    if not selected_date:  # Если дата ещё не выбрана, обновляем календарь
        await callback_query.message.edit_reply_markup(reply_markup=keyboard)
        await callback_query.answer()
        return

    # Дата выбрана
    logger.info(f"Selected date: {selected_date}")

    # Проверяем, попадает ли выбранная дата в допустимый диапазон (хотя календарь уже ограничивает выбор)
    if selected_date > today:
        await callback_query.message.answer(
            "Вы не можете выбрать дату в будущем. Пожалуйста, выберите дату не новее сегодняшнего дня."
        )
        await ask_date(callback_query.message, state)
        return
    if selected_date < min_date:
        await callback_query.message.answer(
            f"Вы не можете выбрать дату старше 14 дней ({min_date}). Пожалуйста, выберите более позднюю дату."
        )
        await ask_date(callback_query.message, state)
        return

    # Если дата в допустимом диапазоне, продолжаем
    await state.update_data(training_date=selected_date)
    data = await state.get_data()
    logger.info(f"State data: {data}")
    full_name = data['full_name']
    training_type = data['training_type']
    training_date = data['training_date']
    user_id = callback_query.from_user.id
    date_message_id = data.get('date_message_id')
    training_type_message_id = data.get('training_type_message_id')
    timestamp = datetime.now()
    try:
        await f.write_to_db(timestamp, user_id, full_name, training_type, training_date)
        await callback_query.message.answer("Тренировка записана!")
        # Удаляем сообщение с выбором даты
        if date_message_id:
            await bot.delete_message(chat_id=callback_query.message.chat.id, message_id=date_message_id)
            logger.info(f"Deleted date selection message with message_id {date_message_id}")
        # Удаляем сообщение с выбором типа тренировки
        if training_type_message_id:
            await bot.delete_message(chat_id=callback_query.message.chat.id, message_id=training_type_message_id)
            logger.info(f"Deleted training type selection message with message_id {training_type_message_id}")
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
        await f.set_full_name(user_id, full_name)
        # Проверяем, что ФИО действительно сохранено
        saved_full_name = await f.get_full_name(user_id)
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
    full_name = await f.get_full_name(user_id)
    
    if full_name is None:
        await message.answer(
            "У вас не указано ФИО. Пожалуйста, установите его с помощью команды /setname.",
            parse_mode=ParseMode.HTML
        )
        return

    training_stats, total_trainings, error = await f.get_training_stats(user_id)
    if error:
        await message.answer(
            f"Произошла ошибка при получении статистики: {error}",
            parse_mode=ParseMode.HTML
        )
        return
    if training_stats is None:
        await message.answer(
            f"У вас пока нет записанных тренировок, {full_name}.",
            parse_mode=ParseMode.HTML
        )
        return

    # Формируем сообщение со статистикой
    stats_message = f"📊 Статистика тренировок для {full_name}:\n"
    stats_message += f"Всего тренировок: {total_trainings}\n"
    for training_type, count in training_stats.items():
        stats_message += f"{training_type}: {count}\n"
    await message.answer(stats_message, parse_mode=ParseMode.HTML)

async def main():
    await f.init_db()  # Инициализируем базу данных
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())