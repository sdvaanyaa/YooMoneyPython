from fastapi import FastAPI, Depends, HTTPException
from yookassa import Configuration, Payment, Refund
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid
import logging
from config import YKASSA_SHOP_ID, YKASSA_SECRET_KEY
from database import get_db, engine
from models import Base, Payment as PaymentModel
from pydantic import BaseModel
from telegram_bot import send_telegram_message_async
from scheduler import start_scheduler, stop_scheduler

app = FastAPI()
Configuration.account_id = YKASSA_SHOP_ID
Configuration.secret_key = YKASSA_SECRET_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

class WebhookEvent(BaseModel):
    event: str
    object: dict

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

    await send_telegram_message_async(
        f"💸 Новый платеж создан!\n"
        f"ID: {payment.id}\n"
        f"Покупка: {description}\n"
        f"Сумма: {amount:.2f} RUB\n"
        f"Статус: Ожидает оплаты ⚡\n"
        f"Ссылка: {payment.confirmation.confirmation_url}"
    )
    return {"payment_id": payment.id, "confirmation_url": payment.confirmation.confirmation_url}

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
        return {"status": "ok"}

    if event_type == "payment.succeeded":
        db_payment.status = "succeeded"
        db.commit()
        await send_telegram_message_async(
            f"🎉 Платеж успешен!\n"
            f"ID: {payment_id}\n"
            f"Покупка: {db_payment.description}\n"
            f"Сумма: {db_payment.amount:.2f} RUB\n"
            f"Статус: Завершён"
        )

    elif event_type == "payment.canceled":
        reason = event.object.get("cancellation_details", {}).get("reason", "неизвестно")
        db_payment.status = "canceled"
        db.commit()
        await send_telegram_message_async(
            f"🚫 Платеж отменён\n"
            f"ID: {payment_id}\n"
            f"Покупка: {db_payment.description}\n"
            f"Причина: {reason}\n"
            f"Статус: Отменён"
        )

        if db_payment.attempts < 3:
            db_payment.retry_at = datetime.now() + timedelta(days=1)  # Изменено на сутки
            db.commit()
            await send_telegram_message_async(
                f"🔄 Запланирован повтор\n"
                f"ID: {payment_id}\n"
                f"Покупка: {db_payment.description}\n"
                f"Когда: через 1 день\n"
                f"Попытка: {db_payment.attempts + 1}/3"
            )
        else:
            await send_telegram_message_async(
                f"⛔ Все попытки исчерпаны\n"
                f"ID: {payment_id}\n"
                f"Покупка: {db_payment.description}\n"
                f"Статус: Отменён окончательно"
            )

    elif event_type == "refund.succeeded":
        amount = event.object["amount"]["value"]
        db_payment.status = "refunded"
        db.commit()
        await send_telegram_message_async(
            f"💰 Возврат выполнен\n"
            f"ID: {payment_id}\n"
            f"Покупка: {db_payment.description}\n"
            f"Сумма: {amount} RUB\n"
            f"Статус: Возвращён"
        )

    return {"status": "ok"}

@app.post("/refund/{payment_id}")
async def refund_payment(payment_id: str, db: Session = Depends(get_db)):
    db_payment = db.query(PaymentModel).filter(PaymentModel.payment_id == payment_id).first()
    if not db_payment or db_payment.status != "succeeded":
        raise HTTPException(status_code=400, detail="Payment not succeeded or not found")

    refund = Refund.create({
        "amount": {"value": f"{db_payment.amount:.2f}", "currency": "RUB"},
        "payment_id": payment_id
    })
    await send_telegram_message_async(
        f"🔙 Создан возврат\n"
        f"ID: {payment_id}\n"
        f"Покупка: {db_payment.description}\n"
        f"Сумма: {db_payment.amount:.2f} RUB"
    )
    return {"refund_id": refund.id}

@app.on_event("startup")
async def startup_event():
    start_scheduler()

@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()