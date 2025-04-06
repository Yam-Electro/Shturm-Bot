import logging
from datetime import datetime, timedelta

# Настройка логирования
logger = logging.getLogger(__name__)

async def ban_user(bot, chat_id, user_id, full_name):
    """Банит пользователя на 30 секунд."""
    try:
        ban_until = datetime.now() + timedelta(seconds=30)
        await bot.ban_chat_member(chat_id, user_id, until_date=ban_until, revoke_messages=True)
        await bot.send_message(
            chat_id,
            f"Пользователь {full_name} теперь горит в аду"
        )
        logger.info(f"User {user_id} ({full_name}) was temporarily banned for 30 seconds.")
        
    except Exception as e:
        logger.error(f"Error banning user {user_id} ({full_name}): {str(e)}")
        raise