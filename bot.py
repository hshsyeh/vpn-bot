import asyncio
import aiosqlite
import httpx
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated,
)

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8860977552:AAHNNz_R0YcCzeeSR3f0N2xGFHCOcG-oygA"
ADMIN_ID = 5387282303                      # ваш Telegram ID
CHANNEL_ID = -1004423436594              # ID канала (бот должен быть админом)
CHANNEL_LINK = "https://t.me/SmokeVPN6745"
SUPPORT_LINK = "https://t.me/SmokeVPN_6745"

DB_PATH = "smokevpn.db"

REMNA_URL = "https://smoke6745.online"   # без слэша в конце
REMNA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1dWlkIjoiNTMxMDMyYjYtMTQwYy00ZDQ3LTlkNTItZjMyMzhlYjc3NjcwIiwidXNlcm5hbWUiOm51bGwsInJvbGUiOiJBUEkiLCJpYXQiOjE3OTI5MzkyODEsImV4cCI6MTkyMjUzOTI4MX0.MnVjDP_aToQdbSUqtJ9zx21ZSJaHzfB_G0Koj4UvqvU"
REMNA_HEADERS = {"Authorization": f"Bearer {REMNA_TOKEN}", "Content-Type": "application/json"}
REMNA_SQUAD_UUID = "6972f64e-feb0-4e76-9960-ab32bb8b9552"                     # uuid internal squad (если используется), иначе ""

TRIAL_DAYS = 3                            # бесплатный пробный период
REFERRER_BONUS_DAYS = 5                   # пригласившему за реферала
REFERRAL_BONUS_DAYS = 3                   # рефералу за регистрацию по ссылке
MIN_WITHDRAW_CRYPTO = 1000
MIN_WITHDRAW_SBP = 1000
SBP_FEE = 0.10
TIERS = [(500, 50), (100, 40), (10, 30), (0, 20)]

HAPP_IOS = "https://apps.apple.com/app/happ-proxy-utility/id6504287215"
HAPP_ANDROID = "https://play.google.com/store/apps/details?id=com.happproxy"
# ===============================================

dp = Dispatcher(storage=MemoryStorage())

WELCOME_TEXT = (
    "🌐 <b>Smoke VPN</b>\n\n"
    "🚀 <b>Как подключиться за 2 минуты:</b>\n\n"
    "1️⃣ <b>Подписка</b> → купите или получите бесплатно\n"
    "2️⃣ <b>Мой ключ</b> → создайте VPN-ключ\n"
    "3️⃣ <b>Инструкция</b> → скачайте приложение Happ\n"
    "4️⃣ Нажмите «Подключиться» в разделе ключей — готово!\n\n"
    "❓ <i>Не получается? Жмите «Инструкция» или «Поддержка»</i>"
)


# ================== БАЗА ДАННЫХ ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            referrer_id INTEGER,
            balance     REAL DEFAULT 0,
            earned      REAL DEFAULT 0,
            bonus_paid  INTEGER DEFAULT 0,
            in_channel  INTEGER DEFAULT 1,
            key_created INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            amount     REAL,
            method     TEXT,
            details    TEXT,
            status     TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        await db.commit()


async def db_get(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def db_register(user_id: int, username: str | None, referrer_id: int | None) -> bool:
    """Создаёт пользователя. Возвращает True, если он новый."""
    if await db_get(user_id):
        return False
    if referrer_id == user_id or (referrer_id and not await db_get(referrer_id)):
        referrer_id = None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)",
            (user_id, username, referrer_id),
        )
        await db.commit()
    return True


async def db_set(user_id: int, field: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
        await db.commit()


async def db_ref_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        return (await cur.fetchone())[0]


async def db_add_money(user_id: int, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ?, earned = earned + ? WHERE user_id = ?",
            (amount, amount, user_id),
        )
        await db.commit()


async def db_change_balance(user_id: int, delta: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        await db.commit()


def get_percent(count: int) -> int:
    for threshold, pct in TIERS:
        if count >= threshold:
            return pct
    return 20


def next_tier(count: int):
    for threshold, pct in reversed(TIERS):
        if count < threshold:
            return pct, threshold - count
    return None, 0


# ================== REMNAWAVE API ==================
def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def remna_user_by_tg(tg_id: int) -> dict | None:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{REMNA_URL}/api/users/by-telegram-id/{tg_id}", headers=REMNA_HEADERS)
        if r.status_code != 200:
            return None
        users = r.json().get("response") or []
        return users[0] if users else None


async def remna_create_user(tg_id: int, days: int) -> dict | None:
    """Создаёт пользователя в панели. <-- ВАШ КОД, если создаёте иначе."""
    expire = datetime.now(timezone.utc) + timedelta(days=days)
    body = {
        "username": f"tg_{tg_id}",
        "telegramId": tg_id,
        "expireAt": expire.isoformat(),
        "trafficLimitBytes": 0,
        "trafficLimitStrategy": "NO_RESET",
        "status": "ACTIVE",
    }
    if REMNA_SQUAD_UUID:
        body["activeInternalSquads"] = [REMNA_SQUAD_UUID]
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{REMNA_URL}/api/users", json=body, headers=REMNA_HEADERS)
        if r.status_code not in (200, 201):
            print("remna_create_user error:", r.status_code, r.text)
            return None
        return r.json().get("response")


async def remna_set_expire(uuid: str, expire_at: datetime):
    async with httpx.AsyncClient(timeout=15) as c:
        await c.patch(
            f"{REMNA_URL}/api/users",
            json={"uuid": uuid, "expireAt": expire_at.isoformat()},
            headers=REMNA_HEADERS,
        )


async def remna_add_days(tg_id: int, days: int) -> bool:
    u = await remna_user_by_tg(tg_id)
    if not u:
        return False
    base = max(_parse_dt(u["expireAt"]), datetime.now(timezone.utc))
    await remna_set_expire(u["uuid"], base + timedelta(days=days))
    return True


async def remna_halve_remaining(tg_id: int):
    u = await remna_user_by_tg(tg_id)
    if not u:
        return
    now = datetime.now(timezone.utc)
    remaining = _parse_dt(u["expireAt"]) - now
    if remaining.total_seconds() > 0:
        await remna_set_expire(u["uuid"], now + remaining / 2)


# ================== РЕФЕРАЛЬНАЯ ЛОГИКА ==================
async def referral_extra_days(tg_id: int) -> int:
    u = await db_get(tg_id)
    return REFERRAL_BONUS_DAYS if u and u["referrer_id"] else 0


async def on_payment_success(bot: Bot, tg_id: int, amount: float):
    """Вызывать после ПОДТВЕРЖДЁННОЙ оплаты (когда появится платёжка)."""
    u = await db_get(tg_id)
    if not u or not u["referrer_id"]:
        return
    pct = get_percent(await db_ref_count(u["referrer_id"]))
    reward = round(amount * pct / 100, 2)
    await db_add_money(u["referrer_id"], reward)
    try:
        await bot.send_message(
            u["referrer_id"],
            f"💰 Ваш реферал оплатил подписку — начислено <b>{reward:.2f}₽</b> ({pct}%)",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def award_referrer(bot: Bot, referral_id: int):
    """+5 дней пригласившему, когда реферал реально подключился."""
    u = await db_get(referral_id)
    if not u or not u["referrer_id"] or u["bonus_paid"]:
        return
    await db_set(referral_id, "bonus_paid", 1)
    ok = await remna_add_days(u["referrer_id"], REFERRER_BONUS_DAYS)
    text = (
        f"✅ Ваш реферал подключился к VPN — вам начислено <b>+{REFERRER_BONUS_DAYS} дней</b>!"
        if ok else
        f"✅ Ваш реферал подключился! Создайте ключ, и <b>+{REFERRER_BONUS_DAYS} дней</b> будут добавлены."
    )
    try:
        await bot.send_message(u["referrer_id"], text, parse_mode="HTML")
    except Exception:
        pass


async def connection_checker(bot: Bot):
    """Фоновая задача: раз в 5 минут проверяет, кто из рефералов подключился."""
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT user_id FROM users WHERE referrer_id IS NOT NULL AND bonus_paid = 0 AND key_created = 1"
                )
                pending = [r[0] for r in await cur.fetchall()]
            for tg_id in pending:
                u = await remna_user_by_tg(tg_id)
                if u and (u.get("onlineAt") or (u.get("usedTrafficBytes") or 0) > 0):
                    await award_referrer(bot, tg_id)
        except Exception as e:
            print("connection_checker error:", e)
        await asyncio.sleep(300)


# ================== КЛАВИАТУРЫ ==================
def get_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Подписка", callback_data="subscription"),
         InlineKeyboardButton(text="🔑 Мой ключ", callback_data="my_key")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="instruction"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=SUPPORT_LINK),
         InlineKeyboardButton(text="📜 Правила", callback_data="rules")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")]
    ])


# ================== /START ==================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    args = command.args or ""
    referrer_id = int(args[4:]) if args.startswith("ref_") and args[4:].isdigit() else None

    is_new = await db_register(user_id, message.from_user.username, referrer_id)

    if is_new and referrer_id and referrer_id != user_id:
        try:
            await message.bot.send_message(
                referrer_id,
                "🎉 По вашей ссылке зарегистрировался новый пользователь!\n"
                f"После его подключения к VPN вы получите <b>+{REFERRER_BONUS_DAYS} дней</b>.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer(WELCOME_TEXT, reply_markup=get_main_menu(), parse_mode="HTML")


# ================== ПОДПИСКА ==================
@dp.callback_query(F.data == "subscription")
async def subscription_handler(callback: types.CallbackQuery):  # <-- ВАШ КОД
    u = await remna_user_by_tg(callback.from_user.id)
    if u:
        exp = _parse_dt(u["expireAt"])
        left = exp - datetime.now(timezone.utc)
        status = (
            f"✅ Активна до <b>{exp.strftime('%d.%m.%Y')}</b> (осталось {max(left.days, 0)} дн.)"
            if left.total_seconds() > 0 else "❌ Подписка истекла"
        )
    else:
        status = f"🎁 Доступен бесплатный период: <b>{TRIAL_DAYS} дн.</b> — создайте ключ в разделе «Мой ключ»"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц — 150₽", callback_data="noop")],
        [InlineKeyboardButton(text="3 месяца — 400₽", callback_data="noop")],
        [InlineKeyboardButton(text="12 месяцев — 1200₽", callback_data="noop")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")],
    ])
    await callback.message.edit_text(
        f"💳 <b>Подписка</b>\n\n{status}\n\nВыберите тариф:",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


# ================== МОЙ КЛЮЧ ==================
@dp.callback_query(F.data == "my_key")
async def my_key_handler(callback: types.CallbackQuery):  # <-- ВАШ КОД (логика создания ключа)
    tg_id = callback.from_user.id
    await db_register(tg_id, callback.from_user.username, None)

    u = await remna_user_by_tg(tg_id)
    if not u:
        days = TRIAL_DAYS + await referral_extra_days(tg_id)   # <-- бонус рефералу
        u = await remna_create_user(tg_id, days)
        if not u:
            await callback.answer("Ошибка создания ключа. Напишите в поддержку.", show_alert=True)
            return
        await db_set(tg_id, "key_created", 1)

    sub_url = u.get("subscriptionUrl", "")
    exp = _parse_dt(u["expireAt"]).strftime("%d.%m.%Y")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Подключиться", url=f"happ://add/{sub_url}")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="instruction")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")],
    ])
    await callback.message.edit_text(
        f"🔑 <b>Ваш ключ</b>\n\n"
        f"Действует до: <b>{exp}</b>\n\n"
        f"Ссылка подписки (нажмите, чтобы скопировать):\n<code>{sub_url}</code>\n\n"
        f"Нажмите «Подключиться» — ссылка откроется в приложении Happ.",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


# ================== ИНСТРУКЦИЯ ==================
@dp.callback_query(F.data == "instruction")
async def instruction_handler(callback: types.CallbackQuery):  # <-- ВАШ КОД
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Happ для iOS", url=HAPP_IOS),
         InlineKeyboardButton(text="🤖 Happ для Android", url=HAPP_ANDROID)],
        [InlineKeyboardButton(text="🔑 Мой ключ", callback_data="my_key")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")],
    ])
    await callback.message.edit_text(
        "📖 <b>Инструкция</b>\n\n"
        "1️⃣ Установите приложение <b>Happ</b> по кнопке ниже\n"
        "2️⃣ Вернитесь в бот → «Мой ключ»\n"
        "3️⃣ Нажмите «Подключиться» — подписка добавится автоматически\n"
        "4️⃣ В Happ нажмите кнопку включения — готово!\n\n"
        f"❓ Проблемы? <a href=\"{SUPPORT_LINK}\">Напишите в поддержку</a>",
        reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True,
    )
    await callback.answer()


# ================== ПРАВИЛА ==================
@dp.callback_query(F.data == "rules")
async def rules_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📜 <b>Правила использования</b>\n\n"
        "1. Запрещено использовать VPN для незаконных действий.\n"
        "2. Одним ключом может пользоваться только один человек.",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    await callback.answer("Оплата скоро появится!", show_alert=True)


# ================== РЕФЕРАЛЫ ==================
async def build_referral_screen(bot: Bot, tg_id: int, username: str | None):
    await db_register(tg_id, username, None)
    u = await db_get(tg_id)
    count = await db_ref_count(tg_id)
    pct = get_percent(count)
    nxt_pct, need = next_tier(count)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{tg_id}"
    tier_line = f"До {nxt_pct}% осталось {need} реф." if nxt_pct else "🏆 Максимальный уровень!"

    text = (
        "👥 <b>Приглашай рефералов — получай VPN бесплатно!</b>\n\n"
        "<b>Вы получите:</b>\n"
        f"• +{REFERRER_BONUS_DAYS} дней VPN за каждого реферала\n"
        f"• {pct}% от покупок реферала на баланс\n\n"
        "<b>Реферал получит:</b>\n"
        f"• +{REFERRAL_BONUS_DAYS} дня VPN бесплатно\n\n"
        "<b>Приглашай больше — получай больше:</b>\n"
        "• 0–9 реф. — 20%\n"
        "• 10–99 реф. — 30%\n"
        "• 100–499 реф. — 40%\n"
        "• 500+ реф. — 50%\n"
        f"{tier_line}\n\n"
        "⚠️ <b>Условия:</b>\n"
        f"• Бонус +{REFERRER_BONUS_DAYS} дней начисляется после того, как реферал создаст ключ и подключится к VPN\n"
        "• Если реферал отпишется от канала — у обоих спишется 50% оставшегося бонуса\n\n"
        "📊 <b>Ваша статистика:</b>\n"
        f"• Рефералов: {count}\n"
        f"• Заработано: {u['earned']:.2f}₽\n"
        f"• Баланс: {u['balance']:.2f}₽\n\n"
        "🔗 <b>Ваша ссылка</b> (нажмите чтобы скопировать):\n"
        f"<code>{link}</code>\n\n"
        f"🪙 Вывод в крипте (BNB, BTC, ETH, LTC, TON, TRX, USDT) от {MIN_WITHDRAW_CRYPTO}₽\n"
        f"🏦 Вывод по СБП от {MIN_WITHDRAW_SBP}₽ — вручную, до 24 ч, комиссия {int(SBP_FEE * 100)}%"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести средства", callback_data="ref_withdraw")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main")],
    ])
    return text, kb


@dp.callback_query(F.data == "referrals")
async def referrals_handler(callback: types.CallbackQuery):
    text, kb = await build_referral_screen(callback.bot, callback.from_user.id, callback.from_user.username)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ================== ВЫВОД СРЕДСТВ ==================
class WithdrawState(StatesGroup):
    details = State()


@dp.callback_query(F.data == "ref_withdraw")
async def withdraw_menu(callback: types.CallbackQuery):
    u = await db_get(callback.from_user.id)
    bal = u["balance"] if u else 0
    if bal < MIN_WITHDRAW_CRYPTO:
        await callback.answer(
            f"Минимум для вывода — {MIN_WITHDRAW_CRYPTO}₽. Ваш баланс: {bal:.2f}₽", show_alert=True
        )
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪙 Крипта", callback_data="wd_crypto")],
        [InlineKeyboardButton(text="🏦 СБП", callback_data="wd_sbp")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="referrals")],
    ])
    await callback.message.edit_text(
        f"💸 Баланс: <b>{bal:.2f}₽</b>\nВыберите способ вывода:", reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.in_({"wd_crypto", "wd_sbp"}))
async def withdraw_choose(callback: types.CallbackQuery, state: FSMContext):
    method = "crypto" if callback.data == "wd_crypto" else "sbp"
    u = await db_get(callback.from_user.id)
    minimum = MIN_WITHDRAW_CRYPTO if method == "crypto" else MIN_WITHDRAW_SBP
    if u["balance"] < minimum:
        await callback.answer(f"Для этого способа минимум {minimum}₽", show_alert=True)
        return
    await state.update_data(method=method)
    await state.set_state(WithdrawState.details)
    hint = (
        "Отправьте: <b>монета</b> и <b>адрес кошелька</b>\nНапример: <code>USDT TRC20 TXyz...</code>"
        if method == "crypto" else
        "Отправьте: <b>номер телефона</b> и <b>банк</b>\nНапример: <code>+79990001122 Сбер</code>"
    )
    await callback.message.edit_text(hint, parse_mode="HTML")
    await callback.answer()


@dp.message(WithdrawState.details)
async def withdraw_details(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    method = data["method"]
    tg_id = message.from_user.id
    u = await db_get(tg_id)
    amount = round(u["balance"], 2)
    payout = round(amount * (1 - SBP_FEE), 2) if method == "sbp" else amount

    await db_change_balance(tg_id, -amount)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO withdrawals (user_id, amount, method, details) VALUES (?, ?, ?, ?)",
            (tg_id, amount, method, message.text),
        )
        wid = cur.lastrowid
        await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выплачено", callback_data=f"wd_ok_{wid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wd_no_{wid}"),
    ]])
    await message.bot.send_message(
        ADMIN_ID,
        f"💸 <b>Заявка #{wid}</b> ({'СБП' if method == 'sbp' else 'Крипта'})\n"
        f"Юзер: <code>{tg_id}</code> @{message.from_user.username}\n"
        f"Списано: {amount:.2f}₽ → к выплате <b>{payout:.2f}₽</b>\n"
        f"Реквизиты: <code>{message.text}</code>",
        reply_markup=kb, parse_mode="HTML",
    )
    await message.answer(
        f"✅ Заявка #{wid} создана. К выплате: <b>{payout:.2f}₽</b>\nОбычно обрабатываем до 24 ч.",
        parse_mode="HTML", reply_markup=back_kb(),
    )


@dp.callback_query(F.data.startswith(("wd_ok_", "wd_no_")))
async def withdraw_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    approved = callback.data.startswith("wd_ok_")
    wid = int(callback.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM withdrawals WHERE id = ?", (wid,))
        w = await cur.fetchone()
        if not w or w["status"] != "pending":
            await callback.answer("Уже обработано", show_alert=True)
            return
        await db.execute(
            "UPDATE withdrawals SET status = ? WHERE id = ?",
            ("paid" if approved else "rejected", wid),
        )
        await db.commit()
    if not approved:
        await db_change_balance(w["user_id"], w["amount"])  # возврат средств
    try:
        await callback.bot.send_message(
            w["user_id"],
            f"✅ Заявка #{wid} выплачена!" if approved
            else f"❌ Заявка #{wid} отклонена, средства возвращены на баланс.",
        )
    except Exception:
        pass
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Готово")


# ================== ОТПИСКА ОТ КАНАЛА ==================
@dp.chat_member()
async def on_member_change(event: ChatMemberUpdated):
    if event.chat.id != CHANNEL_ID:
        return
    tg_id = event.new_chat_member.user.id
    status = event.new_chat_member.status
    u = await db_get(tg_id)
    if not u:
        return

    if status in ("left", "kicked") and u["in_channel"]:
        await db_set(tg_id, "in_channel", 0)
        await remna_halve_remaining(tg_id)
        try:
            await event.bot.send_message(
                tg_id, "⚠️ Вы отписались от канала — списано 50% оставшегося срока подписки."
            )
        except Exception:
            pass
        if u["referrer_id"]:
            await remna_halve_remaining(u["referrer_id"])
            try:
                await event.bot.send_message(
                    u["referrer_id"],
                    "⚠️ Ваш реферал отписался от канала — списано 50% оставшегося бонуса.",
                )
            except Exception:
                pass
    elif status in ("member", "administrator", "creator"):
        await db_set(tg_id, "in_channel", 1)


# ================== НАЗАД ==================
@dp.callback_query(F.data == "back_to_main")
async def back_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=get_main_menu(), parse_mode="HTML")
    await callback.answer()


# ================== ЗАПУСК ==================
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    asyncio.create_task(connection_checker(bot))
    print("Бот Smoke VPN запущен и готов к работе!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
