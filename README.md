# Платёжный сервис с рекуррентными платежами

Проект — REST API на FastAPI для работы с платежами через ЮKassa. Поддерживает создание платежей, обработку вебхуков, автоматические повторы отменённых платежей через сутки и уведомления в Telegram.

## Установка

1. **Клонируйте репозиторий**:
   ```bash
   git clone <URL_репозитория>
   cd <название_папки>
   ```
2.	**Создайте виртуальное окружение**:

    ```bash
    python -m venv venv
    source venv/bin/activate  # Linux/Mac
    venv\Scripts\activate     # Windows
    ```
3.	**Установите зависимости**:

    ```bash
    pip install -r requirements.txt
    ```

4.	**Настройте конфигурацию в файле config.py**:

	```bash
	YKASSA_SHOP_ID = "your_shop_id"
	YKASSA_SECRET_KEY = "your_secret_key"
	TELEGRAM_TOKEN = "your_bot_token"
	TELEGRAM_CHAT_ID = "your_chat_id"
	DATABASE_URL = "postgresql://user:password@localhost:5432/dbname"
	```

5. **Запустите приложение**:

	```bash
	uvicorn main:app --reload
	```
 
6. **Проверьте работоспособность API**:

	```bash
	API доступно на http://127.0.0.1:8000.
	Документация Swagger: http://127.0.0.1:8000/docs.
	```

## Основные функции

- **Создание платежа**: `POST /create_payment`
- **Обработка вебхуков**: `POST /webhook`
- **Возврат платежа**: `POST /refund/{payment_id}`
- **Повтор платежей**: Автоматически через 1 день после отмены (до 3 попыток) с помощью APScheduler..

## Примечания
- **Если вы разрабатываете локально, ngrok поможет создать временный публичный URL для вашего сервера (http://127.0.0.1:8000). Это позволит ЮKassa отправлять вебхуки напрямую на ваш компьютер через интернет.**

    ```bash
    ngrok http 8000
    ```

 - **Обновите URL вебхука в ЮKassa.**



