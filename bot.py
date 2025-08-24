# bot.py
import logging
import os
import re
import requests

from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from dotenv import load_dotenv

load_dotenv()

# --- ENV ---
API_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")  # поддержка обоих имён
UON_API_KEY = os.getenv("CRM_API_KEY") or os.getenv("UON_API_KEY")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")  # например, @turzapros
PRIVACY_URL = os.getenv("PRIVACY_URL", "https://example.com/privacy")
CRM_SOURCE = os.getenv("CRM_SOURCE", "Заявка из Telegram")

# Проверки окружения
missing = []
if not API_TOKEN:
    missing.append("BOT_TOKEN (или API_TOKEN)")
if not UON_API_KEY:
    missing.append("CRM_API_KEY (или UON_API_KEY)")
if not TELEGRAM_CHANNEL:
    missing.append("TELEGRAM_CHANNEL (@turzapros)")
if missing:
    raise RuntimeError("Отсутствуют переменные окружения: " + ", ".join(missing))

# --- CRM endpoint (U-ON) ---
CRM_ENDPOINT = f"https://api.u-on.ru/{UON_API_KEY}/lead/create.json"  # см. оф. доки

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())


class Form(StatesGroup):
    name = State()
    phone = State()
    consent = State()


def sanitize_phone(text: str) -> str:
    # Оставляем только + и цифры, убираем пробелы/скобки/дефисы
    if not text:
        return ""
    p = re.sub(r"[^\d+]", "", text)
    # Нормализация ведущих нулей/8 при желании — тут по минимуму
    return p


@dp.message_handler(commands="start")
async def cmd_start(message: types.Message):
    kb = types.ReplyKeyboardRemove()
    await message.answer("Добро пожаловать! Введите, пожалуйста, ваше имя:", reply_markup=kb)
    await Form.name.set()


@dp.message_handler(state=Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    # Кнопка для отправки контакта (даст phone без опечаток)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📱 Отправить телефон", request_contact=True))
    await message.answer("Введите номер телефона или нажмите кнопку ниже:", reply_markup=kb)
    await Form.phone.set()


# Пришёл контакт через кнопку
@dp.message_handler(content_types=types.ContentType.CONTACT, state=Form.phone)
async def process_phone_contact(message: types.Message, state: FSMContext):
    phone = sanitize_phone(message.contact.phone_number)
    await state.update_data(phone=phone)
    await ask_consent(message, state)


# Пришёл текстом
@dp.message_handler(state=Form.phone, content_types=types.ContentTypes.TEXT)
async def process_phone_text(message: types.Message, state: FSMContext):
    phone = sanitize_phone(message.text)
    if len(re.sub(r"\D", "", phone)) < 6:
        await message.answer("Похоже, номер некорректный. Попробуйте ещё раз или нажмите кнопку контакта ниже.")
        return
    await state.update_data(phone=phone)
    await ask_consent(message, state)


async def ask_consent(message: types.Message, state: FSMContext):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Политика конфиденциальности", url=PRIVACY_URL))
    kb.add(types.InlineKeyboardButton("✅ Подтвердить и отправить", callback_data="submit"))
    await message.answer(
        "Проверьте данные и подтвердите отправку заявки:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    data = await state.get_data()
    await message.answer(f"Имя: {data.get('name')}\nТелефон: {data.get('phone')}", reply_markup=kb)
    await Form.consent.set()


@dp.callback_query_handler(lambda c: c.data == "submit", state=Form.consent)
async def process_submit(callback_query: types.CallbackQuery, state: FSMContext):
    user = callback_query.from_user
    data = await state.get_data()
    name = (data.get("name") or user.full_name or "").strip()
    phone = sanitize_phone(data.get("phone") or "")

    # --- Отправка в U-ON CRM ---
    note = f"tg_id: {user.id}; username: @{user.username or '-'}"
    payload = {
        "source": CRM_SOURCE,
        "u_name": name,
        "u_phone": phone,
        "note": note,
    }

    crm_ok = False
    crm_err = None
    try:
        resp = requests.post(CRM_ENDPOINT, data=payload, timeout=10)
        if resp.status_code == 200:
            # Во многих случаях U-ON возвращает JSON с данными лида.
            # На всякий случай не жёстко парсим структуру:
            try:
                j = resp.json()
                # Если в ответе есть явная ошибка — отловим
                if isinstance(j, dict) and j.get("error"):
                    crm_err = str(j.get("error"))
                else:
                    crm_ok = True
            except ValueError:
                # Не JSON? Считаем по коду ответа
                crm_ok = True
        else:
            crm_err = f"HTTP {resp.status_code}"
    except Exception as e:
        crm_err = str(e)

    # --- Дубль в @turzapros ---
    # В канал передаём краткое уведомление с tg_id и username.
    channel_msg = (
        "🔔 Новый лид\n"
        f"👤 Имя: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"🆔 tg_id: {user.id}\n"
        f"📝 username: @{user.username or '-'}"
    )
    try:
        await bot.send_message(TELEGRAM_CHANNEL, channel_msg)
    except Exception as e:
        logging.exception("Не удалось отправить дубль в канал: %s", e)

    # --- Ответ пользователю ---
    if crm_ok:
        await bot.send_message(user.id, "Спасибо! Ваша заявка принята ✅")
    else:
        logging.error("CRM ошибка: %s", crm_err)
        await bot.send_message(
            user.id,
            "Мы получили ваши данные, но не удалось отправить в CRM. Попробуем позже. 🙏",
        )

    await state.finish()
    await callback_query.answer()  # убрать "часики" у кнопки


if __name__ == "__main__":
    # skip_updates=True — чтобы не обрабатывать старые апдейты при рестарте
    executor.start_polling(dp, skip_updates=True)
