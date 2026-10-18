import asyncio
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8860977552:AAEsSlQxOR_gsaTAS4ZAXuFVOoWLVB_WOIk"
MARZBAN_URL = "http://127.0.0.1:8080" # Адрес вашей панели
MARZBAN_USER = "admin"
MARZBAN_PASS = "admin2026"

dp = Dispatcher()

# --- ФУНКЦИЯ ДЛЯ СОЗДАНИЯ КЛЮЧА В MARZBAN ---
async def create_vpn_key(username: str):
    async with aiohttp.ClientSession() as session:
        # 1. Получаем токен авторизации
        login_url = f"{MARZBAN_URL}/api/admin/token"
        login_data = {"username": MARZBAN_USER, "password": MARZBAN_PASS}
        try:
            async with session.post(login_url, data=login_data) as resp:
                if resp.status != 200:
                    return None, "Ошибка авторизации в панели"
                token_data = await resp.json()
                access_token = token_data.get("access_token")
        except Exception as e:
            return None, "Сервер Marzban недоступен"

        # 2. Создаем пользователя
        headers = {"Authorization": f"Bearer {access_token}"}
        user_url = f"{MARZBAN_URL}/api/user"
        user_data = {
            "username": username,
            "proxies": {"vless": {}},
            "inbounds": {"vless": ["VLESS TCP REALITY"]},
            "expire": 0, # Бессрочно (или укажите timestamp для срока)
            "data_limit": 0, # Безлимит
            "status": "active"
        }
        
        async with session.post(user_url, json=user_data, headers=headers) as resp:
            if resp.status == 409: # Пользователь уже существует
                return None, "У вас уже есть активный ключ!"
            if resp.status != 200:
                return None, "Ошибка создания ключа"
            
            user_info = await resp.json()
            # 3. Достаем ссылку для подключения
            subscription_url = user_info.get("subscription_url")
            if subscription_url:
                return f"{MARZBAN_URL}{subscription_url}", None
            return None, "Ключ создан, но ссылка не найдена"

# --- КЛАВИАТУРЫ ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Подписка", callback_data="menu_buy"), 
         InlineKeyboardButton(text="🔑 Мой ключ", callback_data="menu_profile")],
        [InlineKeyboardButton(text="🎁 Бесплатный ключ", callback_data="free_key"), 
         InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu_help"), 
         InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/your_support")]
    ])

def get_bottom_reply_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Главное меню")]],
        resize_keyboard=True,
        is_persistent=True
    )

# --- ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    welcome_text = (
        f"🌐 <b>Nexyon VPN</b>\n\n"
        f"🚀 <b>Как подключиться за 2 минуты:</b>\n\n"
        f"1️⃣ <b>Подписка</b> → купите или получите бесплатно\n"
        f"2️⃣ <b>Мой ключ</b> → создайте VPN-ключ\n"
        f"3️⃣ <b>Инструкция</b> → скачайте приложение Happ\n"
        f"4️⃣ Нажмите «Подключиться» в разделе ключей — готово!\n\n"
        f"❓ <i>Не получается? Жмите «Инструкция» или «Поддержка»</i>"
    )
    await message.answer(welcome_text, reply_markup=get_main_menu(), parse_mode="HTML")
    await message.answer("Меню закреплено внизу 👇", reply_markup=get_bottom_reply_menu())

@dp.message(F.text == "🏠 Главное меню")
async def reply_menu_handler(message: types.Message):
    await start_handler(message)

# Обработчик кнопки "Бесплатный ключ"
@dp.callback_query(F.data == "free_key")
async def free_key_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("⏳ Создаю для вас ключ на сервере, подождите...")
    
    # Имя пользователя в панели будет равно Telegram ID
    username = f"user_{callback.from_user.id}"
    
    link, error = await create_vpn_key(username)
    
    if error:
        await callback.message.edit_text(
            f"❌ {error}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
            ])
        )
    else:
        text = (
            f"✅ <b>Ваш VPN-ключ готов!</b>\n\n"
            f"🔗 <b>Ссылка для подключения:</b>\n"
            f"<code>{link}</code>\n\n"
            f"Скопируйте её и добавьте в приложение v2rayNG, Streisand или Happ.\n"
            f"Если ссылка не работает, нажмите на неё, чтобы скопировать."
        )
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
            ])
        )
    await callback.answer()

# Обработчик кнопки "Мой ключ" (ведет в профиль)
@dp.callback_query(F.data == "menu_profile")
async def profile_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"Нажмите «🎁 Бесплатный ключ», чтобы получить доступ к VPN.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_handler(callback: types.CallbackQuery):
    welcome_text = (
        f"🌐 <b>Nexyon VPN</b>\n\n"
        f"🚀 <b>Как подключиться за 2 минуты:</b>\n\n"
        f"1️⃣ <b>Подписка</b> → купите или получите бесплатно\n"
        f"2️⃣ <b>Мой ключ</b> → создайте VPN-ключ\n"
        f"3️⃣ <b>Инструкция</b> → скачайте приложение Happ\n"
        f"4️⃣ Нажмите «Подключиться» в разделе ключей — готово!\n\n"
        f"❓ <i>Не получается? Жмите «Инструкция» или «Поддержка»</i>"
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_menu(), parse_mode="HTML")
    await callback.answer()

# --- ЗАПУСК ---
async def main():
    bot = Bot(token=BOT_TOKEN)
    print("Бот с интеграцией Marzban запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())