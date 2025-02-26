from fastapi import FastAPI, Depends, HTTPException
from yookassa import Configuration, Payment, Refund
from telegram import Bot
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid
import asyncio
from config import YKASSA_SHOP_ID, YKASSA_SECRET_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from database import get_db, engine
from models import Base, Payment as PaymentModel
from pydantic import BaseModel
import logging

app = FastAPI()
Configuration.account_id = YKASSA_SHOP_ID
Configuration.secret_key = YKASSA_SECRET_KEY

# Создаем экземпляр Bot без кастомного http_client
bot = Bot(token=TELEGRAM_TOKEN)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Асинхронная функция отправки сообщений с повторными попытками
async def send_telegram_message_async(message: str, retries: int = 3):
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            return  # Успешно отправлено
        except Exception as e:
            logger.error(f"Попытка {attempt + 1} отправки в Telegram провалилась: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
            else:
                logger.error(f"Все попытки отправки сообщения в Telegram исчерпаны: {message}")

class WebhookEvent(BaseModel):
    event: str
    object: dict

# Создание платежа
@app.post("/create_payment")
async def create_payment(amount: float, description: str, db: Session = Depends(get_db)):
    payment = Payment.create({
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://example.com"},
        "capture": True,
        "description": description
    }, uuid.uuid4())

    db_payment = PaymentModel(
        payment_id=payment.id,
        amount=amount,
        description=description,
        status="pending",
        attempts=1
    )
    db.add(db_payment)
    db.commit()

    await send_telegram_message_async(f"Создан платеж {payment.id}: {payment.confirmation.confirmation_url}")
    return {"payment_id": payment.id, "confirmation_url": payment.confirmation.confirmation_url}

# Обработка вебхука
@app.post("/webhook")
async def webhook(event: WebhookEvent, db: Session = Depends(get_db)):
    logger.info(f"Получен вебхук: {event}")
    event_type = event.event

    if event_type == "refund.succeeded":
        payment_id = event.object["payment_id"]
    else:
        payment_id = event.object["id"]

    db_payment = db.query(PaymentModel).filter(PaymentModel.payment_id == payment_id).first()
    if not db_payment:
        logger.error(f"Платеж {payment_id} не найден")
        raise HTTPException(status_code=404, detail="Payment not found")

    if event_type == "payment.succeeded":
        db_payment.status = "succeeded"
        db.commit()
        await send_telegram_message_async(f"Платеж {payment_id} успешен! Сумма: {db_payment.amount} RUB")

    elif event_type == "payment.canceled":
        reason = event.object.get("cancellation_details", {}).get("reason", "неизвестно")
        db_payment.status = "canceled"
        db.commit()
        await send_telegram_message_async(f"Платеж {payment_id} неуспешен, причина: {reason}")

        if db_payment.attempts < 3:
            db_payment.attempts += 1
            # db_payment.retry_at = datetime.now() + timedelta(days=1)
            db_payment.retry_at = datetime.now() + timedelta(seconds=30)
            db.commit()
            await send_telegram_message_async(f"Запланирован повтор для {payment_id} через день")
        else:
            await send_telegram_message_async(f"Все попытки для {payment_id} исчерпаны")

    elif event_type == "refund.succeeded":
        amount = event.object["amount"]["value"]
        db_payment.status = "refunded"  # Обновляем статус платежа на "refunded"
        db.commit()  # Фиксируем изменения в базе данных
        await send_telegram_message_async(f"Возврат {payment_id} успешен! Сумма: {amount} RUB")

    return {"status": "ok"}

# Создание возврата
@app.post("/refund/{payment_id}")
async def refund_payment(payment_id: str, db: Session = Depends(get_db)):
    db_payment = db.query(PaymentModel).filter(PaymentModel.payment_id == payment_id).first()
    if not db_payment or db_payment.status != "succeeded":
        raise HTTPException(status_code=400, detail="Payment not succeeded or not found")

    refund = Refund.create({
        "amount": {"value": f"{db_payment.amount:.2f}", "currency": "RUB"},
        "payment_id": payment_id
    })
    return {"refund_id": refund.id}

# Повтор платежа
@app.post("/retry_payment")
async def retry_payment(db: Session = Depends(get_db)):
    now = datetime.now()
    pending_retries = db.query(PaymentModel).filter(PaymentModel.retry_at <= now, PaymentModel.status == "canceled").all()

    for payment in pending_retries:
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
        await send_telegram_message_async(f"Повтор платежа {new_payment.id}: {new_payment.confirmation.confirmation_url}")

    return {"retried": len(pending_retries)}