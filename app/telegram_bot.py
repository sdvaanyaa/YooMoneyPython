import asyncio
import logging
from telegram import Bot
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)
bot = Bot(token=TELEGRAM_TOKEN)

async def send_telegram_message_async(message: str, retries: int = 3):
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            return
        except Exception as e:
            logger.error(f"Попытка {attempt + 1} отправки в Telegram провалилась: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error(f"Все попытки отправки сообщения в Telegram исчерпаны: {message}")