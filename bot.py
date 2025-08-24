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

# --- Загрузка переменных окружения ---
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
CRM_API_KEY = os.getenv("CRM_API_KEY")
CRM_SOURCE = os.getenv("CRM_SOURCE")  # не забудь указать в Render
CRM_USER_ID = os.getenv("CRM_USER_ID")
PRIVACY_URL = os.getenv("PRIVACY_URL")
NOTIFY_USER_ID = int(os.getenv("NOTIFY_USER_ID"))  # <- сюда вставишь свой ID после

CRM_URL = f"https://u-on.ru/{CRM_USER_ID}/api/lead/create.json?key={CRM_API_KEY}"

# --- Настройка логгирования и бота ---
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# --- Состояния формы ---
class Form(StatesGroup):
    name = State()
    phone = State()
    consent = State()

# --- Очистка и формат телефона ---
def sanitize_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return ""

# --- Команда /start ---
@dp.message_handler(commands='start')
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать! Введите, пожалуйста, ваше имя:")
    await Form.name.set()

# 👇 УДАЛИ ПОСЛЕ ПОЛУЧЕНИЯ ID
@dp.message_handler(commands='id')
async def get_id(message: types.Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")
# ☝️ УДАЛИ ПОСЛЕ ПОЛУЧЕНИЯ ID

# --- Имя ---
@dp.message_handler(state=Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(types.KeyboardButton("📱 Отправить номер", request_contact=True))

    await message.answer("Введите, пожалуйста, ваш номер телефона или нажмите кнопку:", reply_markup=keyboard)
    await Form.phone.set()

# --- Телефон через кнопку ---
@dp.message_handler(content_types=types.ContentType.CONTACT, state=Form.phone)
async def process_phone_contact(message: types.Message, state: FSMContext):
    phone = sanitize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("Номер некорректный. Введите вручную или попробуйте ещё раз.")
        return
    await state.update_data(phone=phone)
    await ask_consent(message, state)

# --- Телефон вручную ---
@dp.message_handler(state=Form.phone, content_types=types.ContentTypes.TEXT)
async def process_phone_text(message: types.Message, state: FSMContext):
    phone = sanitize_phone(message.text)
    if not phone:
        await message.answer("Номер некорректный. Укажите в формате +7XXXXXXXXXX или нажмите кнопку контакта.")
        return
    await state.update_data(phone=phone)
    await ask_consent(message, state)

# --- Согласие ---
async def ask_consent(message: types.Message, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="📖 Ознакомиться с условиями", url=PRIVACY_URL))
    keyboard.add(types.InlineKeyboardButton(text="✅ Подтвердить и отправить", callback_data="submit"))

    await message.answer("Пожалуйста, подтвердите согласие с условиями и отправьте заявку:", reply_markup=keyboard)
    await Form.consent.set()

# --- Подтверждение и отправка ---
@dp.callback_query_handler(lambda c: c.data == 'submit', state=Form.consent)
async def process_submit(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data['name']
    phone = data['phone']
    tg_id = callback_query.from_user.id
    username = callback_query.from_user.username or "—"

    # 1. Отправка в CRM
    crm_payload = {
        'name': name,
        'phone': phone,
        'comment': f"Telegram ID: {tg_id}, username: @{username}",
        'source': CRM_SOURCE
    }

    try:
        crm_response = requests.post(CRM_URL, data=crm_payload, timeout=10)
        crm_success = crm_response.status_code == 200
    except Exception as e:
        crm_success = False
        logging.exception("Ошибка при отправке в CRM")

    # 2. Уведомление в Telegram (только если CRM успешна)
    if crm_success:
        msg = (
            f"🔔 Новый лид\n"
            f"👤 Имя: {name}\n"
            f"📱 Телефон: {phone}\n"
            f"🆔 Telegram ID: {tg_id}\n"
            f"💬 Username: @{username}"
        )
        try:
            await bot.send_message(NOTIFY_USER_ID, msg)
        except Exception as e:
            logging.exception("Ошибка при отправке в Telegram")

        await bot.send_message(callback_query.from_user.id, "Спасибо! Ваша заявка принята ✅")
    else:
        await bot.send_message(callback_query.from_user.id, "⚠ Ошибка при отправке в CRM. Попробуйте позже.")

    await state.finish()

# --- Запуск ---
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
