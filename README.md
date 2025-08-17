# Telegram CRM Bot (U-ON)

Простой Telegram-бот для сбора имени и телефона пользователя, согласия на обработку данных, и отправки лида в CRM [u-on.ru](https://u-on.ru).

## ⚙️ Настройка

Создайте файл `.env` со своими переменными:

- BOT_TOKEN=твой_бот_токен
- CRM_API_KEY=твой_api_key
- CRM_USER_ID=твой_user_id
- TELEGRAM_CHANNEL=@turzapros
- PRIVACY_URL=https://uletaimoskva.ru/pod

## 🚀 Запуск локально

```bash
pip install -r requirements.txt
python bot.py
