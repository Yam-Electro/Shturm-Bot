import asyncio
import sys
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.enums import ParseMode, ChatMemberStatus, UpdateType
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import whisper
from datetime import datetime, date, timedelta
import logging
import functions as f
import antispam

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

class AntiSpam(StatesGroup):
    waiting_for_admin_decision = State()

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

@dp.chat_member()
async def handle_new_member(update: ChatMemberUpdated, state: FSMContext):
    # Проверяем, что это новый пользователь, который присоединился к чату
    if update.new_chat_member.status == ChatMemberStatus.MEMBER and update.old_chat_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
        user = update.new_chat_member.user
        user_id = user.id
        full_name = user.full_name or user.username or "Неизвестный пользователь"
        chat_id = update.chat.id

        # Пропускаем, если пользователь — бот
        if user.is_bot:
            try:
                ban_until = datetime.now() + timedelta(seconds=30)
                await bot.ban_chat_member(chat_id, user_id, until_date=ban_until)
                await bot.send_message(
                    chat_id,
                    f"Бот {full_name} был временно забанен на 30 секунд."
                )
                logger.info(f"Bot {user_id} ({full_name}) was temporarily banned for 30 seconds from chat {chat_id}.")
            except Exception as e:
                logger.error(f"Error kicking bot {user_id} ({full_name}): {str(e)}")
            return

        # Добавляем пользователя в таблицу new_users
        try:
            await f.add_new_user(user_id, chat_id)
            logger.info(f"New user {user_id} ({full_name}) joined chat {chat_id} and was added to new_users.")
        except Exception as e:
            logger.error(f"Error adding new user {user_id} to new_users in chat {chat_id}: {str(e)}")

@dp.callback_query(F.data.startswith("antispam:"))
async def handle_antispam_decision(callback_query: CallbackQuery, state: FSMContext):
    # Проверяем, является ли пользователь администратором
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await callback_query.answer("Только администраторы могут принимать решение!", show_alert=True)
            logger.info(f"User {user_id} tried to make an antispam decision but is not an admin in chat {chat_id}.")
            return
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id} in chat {chat_id}: {str(e)}")
        await callback_query.answer("Произошла ошибка при проверке вашего статуса.", show_alert=True)
        return

    await callback_query.answer()
    data = callback_query.data.split(":")
    action = data[1]  # "allow" или "ban"
    target_user_id = int(data[2])
    full_name = data[3]

    # Удаляем сообщение с кнопками
    await bot.delete_message(chat_id, callback_query.message.message_id)

    # Удаляем пользователя из таблицы new_users после принятия решения
    try:
        await f.remove_new_user(target_user_id, chat_id)
        logger.info(f"User {target_user_id} ({full_name}) removed from new_users after decision in chat {chat_id}.")
    except Exception as e:
        logger.error(f"Error removing user {target_user_id} from new_users in chat {chat_id}: {str(e)}")
        await bot.send_message(
            chat_id,
            f"Произошла ошибка при удалении пользователя {full_name} из списка новых пользователей: {str(e)}"
        )

    if action == "allow":
        try:
            # Удаляем записи о сообщениях пользователя из user_messages, так как он остаётся
            await f.remove_user_messages(target_user_id, chat_id)
            logger.info(f"User {target_user_id} ({full_name}) was allowed to stay in chat {chat_id}.")
        except Exception as e:
            await bot.send_message(
                chat_id,
                f"Произошла ошибка при обработке решения для пользователя {full_name}: {str(e)}"
            )
            logger.error(f"Error processing allow decision for user {target_user_id} in chat {chat_id}: {str(e)}")
    elif action == "ban":
        try:
            # Баним пользователя
            await antispam.ban_user(bot, chat_id, target_user_id, full_name)

            # Получаем список message_id из базы данных
            user_messages = await f.get_user_messages(target_user_id, chat_id)

            # Удаляем все сообщения пользователя
            deleted_count = 0
            for message_id in user_messages:
                try:
                    await bot.delete_message(chat_id, message_id)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete message {message_id} from user {target_user_id} in chat {chat_id}: {str(e)}")

            # Удаляем записи о сообщениях из базы данных
            await f.remove_user_messages(target_user_id, chat_id)

            logger.info(f"User {target_user_id} ({full_name}) was banned, deleted {deleted_count} messages in chat {chat_id}.")
        except Exception as e:
            await bot.send_message(
                chat_id,
                f"Произошла ошибка при бане пользователя {full_name}: {str(e)}"
            )

    # Очищаем состояние
    await state.clear()

@dp.message(F.text | F.voice | F.photo | F.video | F.document)  # Обрабатываем любые сообщения
async def handle_first_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    full_name = message.from_user.full_name or message.from_user.username or "Неизвестный пользователь"

    # Пропускаем, если это сообщение от бота
    if message.from_user.is_bot:
        return

    # Проверяем, есть ли пользователь в таблице new_users
    try:
        if not await f.is_new_user(user_id, chat_id):
            return
    except Exception as e:
        logger.error(f"Error checking if user {user_id} is in new_users in chat {chat_id}: {str(e)}")
        await message.answer(f"Произошла ошибка при проверке пользователя: {str(e)}")
        return

    # Сохраняем message_id в базе данных
    try:
        await f.add_user_message(user_id, chat_id, message.message_id)
    except Exception as e:
        logger.error(f"Error saving message {message.message_id} for user {user_id} in chat {chat_id}: {str(e)}")
        await message.answer(f"Произошла ошибка при сохранении сообщения: {str(e)}")
        return

    # Создаём клавиатуру с кнопками "Да" и "Баним"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data=f"antispam:allow:{user_id}:{full_name}"),
            InlineKeyboardButton(text="Баним", callback_data=f"antispam:ban:{user_id}:{full_name}")
        ]
    ])

    # Отправляем сообщение с вопросом
    sent_message = await bot.send_message(
        chat_id,
        f"Это сообщение от нового пользователя {full_name}. Оставляем?",
        reply_markup=keyboard
    )

    # Сохраняем данные в состоянии
    await state.set_state(AntiSpam.waiting_for_admin_decision)
    await state.update_data(
        user_id=user_id,
        chat_id=chat_id,
        full_name=full_name,
        decision_message_id=sent_message.message_id
    )

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

@dp.callback_query(lambda c: c.data and c.data.startswith('WEEKDAYS_') or c.data.startswith('DAY_') or c.data.startswith('MONTH_') or c.data.startswith('YEAR_'))
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

    # Проверяем, попадает ли выбранная дата в допустимый диапазон
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
        "- Проверять новых пользователей на ботов\n"
        "Версия: 1.1",
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
    try:
        await f.init_db()  # Инициализируем базу данных
        logger.info("Database initialization completed.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise

    # Указываем типы обновлений, которые бот должен обрабатывать
    allowed_updates = [
        UpdateType.MESSAGE,
        UpdateType.CALLBACK_QUERY,
        UpdateType.CHAT_MEMBER
    ]
    await dp.start_polling(bot, allowed_updates=allowed_updates)

if __name__ == '__main__':
    asyncio.run(main())