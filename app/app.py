from fastapi import FastAPI, Depends, HTTPException
from yookassa import Configuration, Payment, Refund
import telegram
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid
from config import YKASSA_SHOP_ID, YKASSA_SECRET_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from database import get_db, engine
from models import Base, Payment as PaymentModel

app = FastAPI()
Configuration.account_id = YKASSA_SHOP_ID
Configuration.secret_key = YKASSA_SECRET_KEY
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# Создание таблиц
Base.metadata.create_all(bind=engine)


def send_telegram_message(message):
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)


# Создание платежа
@app.post("/create_payment")
def create_payment(amount: float, description: str, db: Session = Depends(get_db)):
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

    send_telegram_message(f"Создан платеж {payment.id}: {payment.confirmation.confirmation_url}")
    return {"payment_id": payment.id, "confirmation_url": payment.confirmation.confirmation_url}


# Обработка вебхука
@app.post("/webhook")
def webhook(event: dict, db: Session = Depends(get_db)):
    event_type = event["event"]
    payment_id = event["object"]["id"]
    status = event["object"].get("status", "")

    db_payment = db.query(PaymentModel).filter(PaymentModel.payment_id == payment_id).first()
    if not db_payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if event_type == "payment.succeeded":
        db_payment.status = "succeeded"
        db.commit()
        send_telegram_message(f"Платеж {payment_id} успешен! Сумма: {db_payment.amount} RUB")

    elif event_type == "payment.canceled":
        reason = event["object"].get("cancellation_details", {}).get("reason", "неизвестно")
        db_payment.status = "canceled"
        send_telegram_message(f"Платеж {payment_id} неуспешен, причина: {reason}")

        if db_payment.attempts < 3:
            db_payment.attempts += 1
            db_payment.retry_at = datetime.utcnow() + timedelta(days=1)  # Повтор через день
            db.commit()
            send_telegram_message(f"Запланирован повтор для {payment_id} через день")
        else:
            send_telegram_message(f"Все попытки для {payment_id} исчерпаны")

    elif event_type == "refund.succeeded":
        amount = event["object"]["amount"]["value"]
        send_telegram_message(f"Возврат {payment_id} успешен! Сумма: {amount} RUB")

    return {"status": "ok"}


# Создание возврата
@app.post("/refund/{payment_id}")
def refund_payment(payment_id: str, db: Session = Depends(get_db)):
    db_payment = db.query(PaymentModel).filter(PaymentModel.payment_id == payment_id).first()
    if not db_payment or db_payment.status != "succeeded":
        raise HTTPException(status_code=400, detail="Payment not succeeded or not found")

    refund = Refund.create({
        "amount": {"value": f"{db_payment.amount:.2f}", "currency": "RUB"},
        "payment_id": payment_id
    })
    return {"refund_id": refund.id}


# Повтор платежа (вызывается вручную или по расписанию)
@app.post("/retry_payment")
def retry_payment(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    pending_retries = db.query(PaymentModel).filter(PaymentModel.retry_at <= now,
                                                    PaymentModel.status == "canceled").all()

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
        send_telegram_message(f"Повтор платежа {new_payment.id}: {new_payment.confirmation.confirmation_url}")

    return {"retried": len(pending_retries)}