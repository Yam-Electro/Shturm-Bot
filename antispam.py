import random
import asyncio
import logging

# Настройка логирования
logger = logging.getLogger(__name__)

# Время на ответ (в секундах)
RESPONSE_TIMEOUT = 60

def generate_math_question():
    """Генерирует простой математический вопрос (сложение двух чисел от 1 до 10)."""
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    question = f"Сколько будет {num1} + {num2}?"
    answer = num1 + num2
    return question, answer

async def kick_user_if_no_response(bot, chat_id, user_id, full_name, timeout_message_id, task_container):
    """Удаляет пользователя из чата, если он не ответил вовремя."""
    try:
        await asyncio.sleep(RESPONSE_TIMEOUT)
        # Проверяем, всё ещё ли пользователь в чате
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ["member", "restricted"]:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.delete_message(chat_id, timeout_message_id)
            await bot.send_message(
                chat_id,
                f"Пользователь {full_name} не ответил на вопрос вовремя и был удалён из чата."
            )
            logger.info(f"User {user_id} ({full_name}) was kicked due to timeout.")
    except asyncio.CancelledError:
        logger.info(f"Timeout task for user {user_id} ({full_name}) was cancelled.")
    except Exception as e:
        logger.error(f"Error kicking user {user_id} ({full_name}): {str(e)}")
    finally:
        task_container["task"] = None  # Очищаем задачу после выполнения или отмены