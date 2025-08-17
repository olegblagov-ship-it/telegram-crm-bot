import logging
import os
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

class Form(StatesGroup):
    name = State()
    phone = State()
    consent = State()

@dp.message_handler(commands='start')
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать! Введите, пожалуйста, ваше имя:")
    await Form.name.set()

@dp.message_handler(state=Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите, пожалуйста, ваш номер телефона:")
    await Form.phone.set()

@dp.message_handler(state=Form.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        text="Согласен с условиями обработки персональных данных",
        url=PRIVACY_URL
    ))
    keyboard.add(types.InlineKeyboardButton(
        text="✅ Подтвердить и отправить",
        callback_data="submit"
    ))

    await message.answer("Пожалуйста, подтвердите согласие с условиями и отправьте заявку:", reply_markup=keyboard)
    await Form.consent.set()

@dp.callback_query_handler(lambda c: c.data == 'submit', state=Form.consent)
async def process_submit(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data['name']
    phone = data['phone']

    crm_payload = {'name': name, 'phone': phone}
    crm_response = requests.post(CRM_URL, data=crm_payload)

    msg = f"🔔 Новый лид\\n👤 Имя: {name}\\n📱 Телефон: {phone}"
    await bot.send_message(TELEGRAM_CHANNEL, msg)

    await bot.send_message(callback_query.from_user.id, "Спасибо! Ваша заявка принята.")
    await state.finish()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
