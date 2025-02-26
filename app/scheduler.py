from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import uuid
from yookassa import Payment
from database import get_db
from models import Payment as PaymentModel
from telegram_bot import send_telegram_message_async
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def retry_payments():
    db = next(get_db())
    now = datetime.now()
    pending_retries = db.query(PaymentModel).filter(
        PaymentModel.retry_at <= now,
        PaymentModel.status == "canceled"
    ).all()

    for payment in pending_retries:
        if payment.attempts < 3:
            payment.attempts += 1
            new_payment = Payment.create({
                "amount": {"value": f"{payment.amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://example.com"},
                "capture": True,
                "description": f"{payment.description} (попытка {payment.attempts})"
            }, uuid.uuid4())

            payment.payment_id = new_payment.id
            payment.status = "pending"
            payment.retry_at = None
            db.commit()
            await send_telegram_message_async(
                f"🔄 Повторная попытка платежа\n"
                f"ID: {new_payment.id}\n"
                f"Покупка: {payment.description}\n"
                f"Сумма: {payment.amount:.2f} RUB\n"
                f"Статус: Ожидает оплаты ⚡\n"
                f"Попытка: {payment.attempts}/3\n"
                f"Ссылка: {new_payment.confirmation.confirmation_url}"
            )
        else:
            logger.info(f"Все попытки для {payment.payment_id} исчерпаны")
            payment.retry_at = None
            db.commit()
            await send_telegram_message_async(
                f"⛔ Все попытки исчерпаны\n"
                f"ID: {payment.payment_id}\n"
                f"Покупка: {payment.description}\n"
                f"Статус: Отменён окончательно"
            )

    db.close()

def start_scheduler():
    scheduler.add_job(retry_payments, "interval", seconds=10)
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown()