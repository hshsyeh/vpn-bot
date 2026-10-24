import asyncio
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ ---
# ВНИМАНИЕ! ТОКЕН БОТА ОБЯЗАТЕЛЬНО ПЕРЕВЫПУСТИТЕ В @BotFather!
BOT_TOKEN = "ВАШ_НОВЫЙ_ТОКЕН_БОТА"

# Настройки Remnawave
REMNAWAVE_URL = "https://smoke6745.online" 
REMNAWAVE_API_TOKEN = "ВАШ_API_ТОКЕН_ИЗ_ПАНЕЛИ_REMNAWAVE"
# UUID вашего сквада (Настройки -> Внутренние сквады)
REMNAWAVE_SQUAD_UUID = "ВАШ_UUID_СКВАДА"

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

# --- ФУНКЦИЯ ДЛЯ СОЗДАНИЯ КЛЮЧА В REMNAWAVE ---
async def create_vpn_key(username: str):
    headers = {
        "Authorization": f"Bearer {REMNAWAVE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Данные для создания пользователя (безлимит, до 2099 года)
    user_data = {
        "username": username,
        "status": "ACTIVE",
        "expireAt": "2099-12-31T23:59:59.000Z",
        "trafficLimitBytes": 0,
        "trafficLimitStrategy": "NO_RESET",
        "activeInternalSquads": [REMNAWAVE_SQUAD_UUID]
    }

    async with aiohttp.ClientSession() as session:
        try:
            # 1. Пытаемся создать пользователя
            async with session.post(f"{REMNAWAVE_URL}/api/users", json=user_data, headers=headers) as resp:
                user_info = None
                
                # Если создан успешно
                if resp.status in [200, 201]:
                    data = await resp.json()
                    user_info = data.get("response", data) # В Remnawave ответ часто обернут в "response"
                
                # Если пользователь уже существует (ошибка 409)
                elif resp.status == 409:
                    # Запрашиваем данные существующего пользователя
                    async with session.get(f"{REMNAWAVE_URL}/api/users/by-username/{username}", headers=headers) as get_resp:
                        if get_resp.status == 200:
                            data = await get_resp.json()
                            user_info = data.get("response", data)
                        else:
                            return None, "Ошибка: не удалось получить данные существующего пользователя."
                
                else:
                    error_text = await resp.text()
                    return None, f"Ошибка создания: {error_text}"
                
                # 2. Формируем ссылку
                if user_info:
                    # В Remnawave ссылка на подписку лежит в поле subscriptionUrl
                    subscription_url = user_info.get("subscriptionUrl")
                    if subscription_url:
                        return subscription_url, None
                
                return None, "Ключ создан, но ссылка на подписку не найдена в ответе API."
                
        except Exception as e:
            return None, f"Сервер недоступен: {str(e)}"

# --- КЛАВИАТУРА ---
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
    print("Бот запущен и готов к работе с Remnawave!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
