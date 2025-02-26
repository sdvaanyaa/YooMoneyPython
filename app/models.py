from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from database import Base
from datetime import datetime


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(String, unique=True, index=True)  # ID платежа от YooKassa
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    status = Column(String, nullable=False)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    retry_at = Column(DateTime, nullable=True)  # Время следующей попытки