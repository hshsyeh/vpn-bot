import asyncio
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ ---
# ВНИМАНИЕ! ОБЯЗАТЕЛЬНО СМЕНИ ЭТИ ДАННЫЕ, ОНИ ЗАСВЕТИЛИСЬ В ЧАТЕ!
BOT_TOKEN = "8860977552:AAEsSlQxOR_gsaTAS4ZAXuFVOoWLVB_WOIk"
MARZBAN_URL = "https://fgsu34.duckdns.org:8001"  # https и порт 8001
MARZBAN_USER = "admin"
MARZBAN_PASS = "admin2222"

dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

async def save_user(user: types.User):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute('''
            INSERT INTO users (user_id, username, first_name) 
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
            username=excluded.username, first_name=excluded.first_name
        ''', (user.id, user.username, user.first_name))
        await db.commit()

# --- ФУНКЦИЯ ДЛЯ СОЗДАНИЯ КЛЮЧА В MARZBAN ---
async def create_vpn_key(username: str):
    # Отключаем проверку SSL, чтобы бот не отваливался с ошибкой Server disconnected
    connector = aiohttp.TCPConnector(ssl=False)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        login_url = f"{MARZBAN_URL}/api/admin/token"
        login_data = {"username": MARZBAN_USER, "password": MARZBAN_PASS}
        
        # 1. Авторизация
        try:
            async with session.post(login_url, data=login_data) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return None, f"Ошибка авторизации: {error_text}"
                token_data = await resp.json()
                access_token = token_data.get("access_token")
        except Exception as e:
            return None, f"Сервер недоступен: {str(e)}"

        # 2. Создание пользователя
        headers = {"Authorization": f"Bearer {access_token}"}
        user_url = f"{MARZBAN_URL}/api/user"
        
        user_data = {
            "username": username,
            "proxies": {"vless": {}},
            "inbounds": {"vless": ["VLESS TCP REALITY"]},
            "expire": 0,
            "data_limit": 0,
            "status": "active"
        }
        
        async with session.post(user_url, json=user_data, headers=headers) as resp:
            if resp.status == 409: 
                return None, "У вас уже есть активный ключ!"
            if resp.status != 200:
                error_text = await resp.text()
                return None, f"Ошибка создания: {error_text}"
            
            user_info = await resp.json()
            subscription_url = user_info.get("subscription_url")
            
            # Исправленный блок (проверяем, не начинается ли ссылка уже с http)
            if subscription_url:
                if subscription_url.startswith("http"):
                    return subscription_url, None
                else:
                    return f"{MARZBAN_URL}{subscription_url}", None
            return None, "Ключ создан, но ссылка не найдена"

# --- КЛАВИАТУРА (СЕТКА 8 КНОПОК) ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Подписка", callback_data="menu_buy"), 
         InlineKeyboardButton(text="🔑 Мой ключ", callback_data="menu_profile")],
        [InlineKeyboardButton(text="🎁 Бесплатный ключ", callback_data="free_key"), 
         InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu_help"), 
         InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/your_support")],
        [InlineKeyboardButton(text="⭐️ Отзывы", url="https://t.me/+IypfxcYTDGtmYmYy"), 
         InlineKeyboardButton(text="📜 Правила", callback_data="rules")]
    ])

# --- ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await save_user(message.from_user)
    
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
    await message.answer(".", reply_markup=types.ReplyKeyboardRemove())

@dp.callback_query(F.data == "free_key")
async def free_key_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("⏳ Создаю для вас ключ на сервере, подождите...")
    
    username = f"user_{callback.from_user.id}"
    link, error = await create_vpn_key(username)
    
    if error:
        await callback.message.edit_text(
            f"❌ <b>Ошибка:</b>\n<code>{error}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
            ])
        )
    else:
        text = (
            f"✅ <b>Ваш VPN-ключ готов!</b>\n\n"
            f"🔗 <b>Ссылка для подключения:</b>\n"
            f"<code>{link}</code>\n\n"
            f"Скопируйте её и добавьте в приложение."
        )
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
            ])
        )
    await callback.answer()

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

@dp.callback_query(F.data == "menu_help")
async def help_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📖 <b>Инструкция</b>\n\n"
        "1. Выберите тариф в меню «Подписка» или нажмите «Бесплатный ключ».\n"
        "2. Скопируйте полученную ссылку.\n"
        "3. Вставьте её в приложение v2rayNG, Streisand или Happ.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "menu_buy")
async def buy_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💎 <b>Выберите подходящий тариф:</b>\n\n"
        "Здесь мы позже подключим оплату.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 1 месяц — 199 ₽", callback_data="noop")],
            [InlineKeyboardButton(text="📅 3 месяца — 499 ₽ (Выгодно)", callback_data="noop")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "rules")
async def rules_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📜 <b>Правила сервиса</b>\n\n"
        "1. Запрещено использовать VPN для незаконных действий.\n"
        "2. Одним ключом может пользоваться только один человек.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    await callback.answer("Оплата скоро появится!", show_alert=True)

@dp.callback_query(F.data == "referrals")
async def referrals_handler(callback: types.CallbackQuery):
    await callback.answer("Реферальная система в разработке...", show_alert=True)

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
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
