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

# Загружаем переменные окружения из .env
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
CRM_API_KEY = os.getenv("CRM_API_KEY")
CRM_USER_ID = os.getenv("CRM_USER_ID")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")
PRIVACY_URL = os.getenv("PRIVACY_URL")

CRM_URL = f"https://u-on.ru/{CRM_USER_ID}/api/lead/create.json?key={CRM_API_KEY}"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())


# --- FSM состояния ---
class Form(StatesGroup):
    name = State()
    phone = State()
    consent = State()


# --- Нормализация телефона ---
def sanitize_phone(text: str) -> str:
    """Привести телефон к формату +7XXXXXXXXXX"""
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)

    # Если ввели 11 цифр, начинающихся с 8 → заменяем на 7
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]

    # Если ввели 10 цифр и начинается с 9 → добавляем 7
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits

    # Должно получиться строго 11 цифр и начинаться с 7
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"

    return ""  # сигнал, что номер некорректный


# --- Старт ---
@dp.message_handler(commands='start')
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать! Введите, пожалуйста, ваше имя:")
    await Form.name.set()


# --- Имя ---
@dp.message_handler(state=Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)

    # Кнопка отправки контакта
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(types.KeyboardButton("📱 Отправить номер", request_contact=True))

    await message.answer("Введите, пожалуйста, ваш номер телефона или нажмите кнопку:", reply_markup=keyboard)
    await Form.phone.set()


# --- Телефон через кнопку "Отправить контакт" ---
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


# --- Запрос согласия ---
async def ask_consent(message: types.Message, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        text="📖 Ознакомиться с условиями",
        url=PRIVACY_URL
    ))
    keyboard.add(types.InlineKeyboardButton(
        text="✅ Подтвердить и отправить",
        callback_data="submit"
    ))

    await message.answer("Пожалуйста, подтвердите согласие с условиями и отправьте заявку:", reply_markup=keyboard)
    await Form.consent.set()


# --- Подтверждение ---
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
        'comment': f"Telegram ID: {tg_id}, username: @{username}"
    }
    crm_response = requests.post(CRM_URL, data=crm_payload)

    # 2. Отправка дубликата в @turzapros
    msg = f"🔔 Новый лид\n👤 Имя: {name}\n📱 Телефон: {phone}\n🆔 Telegram ID: {tg_id}\n💬 Username: @{username}"
    await bot.send_message(TELEGRAM_CHANNEL, msg)

    # 3. Ответ пользователю
    if crm_response.status_code == 200:
        await bot.send_message(callback_query.from_user.id, "Спасибо! Ваша заявка принята ✅")
    else:
        await bot.send_message(callback_query.from_user.id, "⚠ Ошибка при отправке в CRM. Попробуйте позже.")

    await state.finish()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
