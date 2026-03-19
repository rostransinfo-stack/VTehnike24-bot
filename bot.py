"""
VTehnike 24 — Telegram Bot v8.0
+ SQLite база данных (не теряется при передеплое)
+ Статусы заявок с уведомлением клиенту
+ Отзыв после выполнения
+ Рассылка всем пользователям
+ Напоминание владельцу если заявка висит 2 часа
+ Кнопка "Перезвоните мне"
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart, Command

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────────────────
BOT_TOKEN = "7151969834:AAHLEnwxwfpaaERnJaOYiiA6ctXJoxvR4C8"    # Токен от @BotFather
OWNER_ID   = 125380747      # Ваш Telegram ID от @userinfobot
DB_FILE    = "/data/vtehnike.db"  # файл базы данных
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ─── БАЗА ДАННЫХ ──────────────────────────────────────────────────────────────
def db_connect():
    return sqlite3.connect(DB_FILE)

def db_init():
    """Создать таблицы если не существуют"""
    with db_connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                username    TEXT,
                first_seen  TEXT,
                last_seen   TEXT,
                visits      INTEGER DEFAULT 1
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                order_type  TEXT,
                summary     TEXT,
                status      TEXT DEFAULT 'принята',
                created_at  TEXT,
                updated_at  TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                order_id    INTEGER,
                rating      INTEGER,
                comment     TEXT,
                created_at  TEXT
            )
        """)
        con.commit()

def db_track_user(user) -> bool:
    """Записать пользователя. Возвращает True если новый."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with db_connect() as con:
        existing = con.execute("SELECT id FROM users WHERE id=?", (user.id,)).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO users (id, name, username, first_seen, last_seen, visits) VALUES (?,?,?,?,?,1)",
                (user.id, user.full_name, user.username or "", now, now)
            )
            con.commit()
            return True
        else:
            con.execute(
                "UPDATE users SET last_seen=?, visits=visits+1, name=?, username=? WHERE id=?",
                (now, user.full_name, user.username or "", user.id)
            )
            con.commit()
            return False

def db_add_order(user_id: int, order_type: str, summary: str) -> int:
    """Добавить заявку, вернуть её ID"""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with db_connect() as con:
        cur = con.execute(
            "INSERT INTO orders (user_id, order_type, summary, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (user_id, order_type, summary, "принята", now, now)
        )
        con.commit()
        return cur.lastrowid

def db_update_status(order_id: int, status: str):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with db_connect() as con:
        con.execute(
            "UPDATE orders SET status=?, updated_at=? WHERE id=?",
            (status, now, order_id)
        )
        con.commit()

def db_get_order(order_id: int):
    with db_connect() as con:
        return con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

def db_add_review(user_id: int, order_id: int, rating: int, comment: str):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with db_connect() as con:
        con.execute(
            "INSERT INTO reviews (user_id, order_id, rating, comment, created_at) VALUES (?,?,?,?,?)",
            (user_id, order_id, rating, comment, now)
        )
        con.commit()

def db_get_stats() -> str:
    with db_connect() as con:
        total_users  = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_orders = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        repair_cnt   = con.execute("SELECT COUNT(*) FROM orders WHERE order_type='repair'").fetchone()[0]
        rental_cnt   = con.execute("SELECT COUNT(*) FROM orders WHERE order_type='rental'").fetchone()[0]
        done_cnt     = con.execute("SELECT COUNT(*) FROM orders WHERE status='выполнено'").fetchone()[0]
        avg_rating   = con.execute("SELECT AVG(rating) FROM reviews").fetchone()[0]
        review_cnt   = con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

        recent = con.execute(
            "SELECT name, username, last_seen FROM users ORDER BY last_seen DESC LIMIT 5"
        ).fetchall()

    rating_str = f"{avg_rating:.1f} / 5 ({review_cnt} отзывов)" if avg_rating else "пока нет"
    recent_str = ""
    for name, username, last_seen in recent:
        tag = f"@{username}" if username else ""
        recent_str += f"  {name} {tag} — был {last_seen}\n"

    return (
        f"Статистика VTehnike 24\n\n"
        f"Пользователей:   {total_users}\n"
        f"Всего заявок:    {total_orders}\n"
        f"  ремонт:        {repair_cnt}\n"
        f"  аренда:        {rental_cnt}\n"
        f"  выполнено:     {done_cnt}\n"
        f"Средний отзыв:   {rating_str}\n\n"
        f"Последние 5 активных:\n{recent_str}"
    )


def db_get_pending_orders(minutes: int = 120) -> list:
    """Вернуть заявки со статусом 'принята' старше N минут"""
    with db_connect() as con:
        rows = con.execute(
            "SELECT id, user_id, order_type, created_at FROM orders WHERE status='принята'"
        ).fetchall()
    result = []
    now = datetime.now()
    for row in rows:
        try:
            created = datetime.strptime(row[3], "%d.%m.%Y %H:%M")
            if (now - created).total_seconds() > minutes * 60:
                result.append({"id": row[0], "user_id": row[1], "type": row[2], "created_at": row[3]})
        except Exception:
            pass
    return result


def db_get_active_orders() -> list:
    """Все заявки кроме выполненных и отменённых"""
    with db_connect() as con:
        rows = con.execute(
            """SELECT o.id, o.user_id, o.order_type, o.status, o.created_at,
                      u.name, u.username
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.id
               WHERE o.status NOT IN ('выполнено', 'отменена')
               ORDER BY o.created_at DESC"""
        ).fetchall()
    return rows

def db_get_order_user_id(order_id: int) -> int:
    with db_connect() as con:
        row = con.execute("SELECT user_id FROM orders WHERE id=?", (order_id,)).fetchone()
    return row[0] if row else None

def db_get_all_user_ids() -> list:
    with db_connect() as con:
        rows = con.execute("SELECT id FROM users").fetchall()
    return [r[0] for r in rows]

# ─── ДАННЫЕ ───────────────────────────────────────────────────────────────────
REPAIR_SERVICES = {
    "bucket_basic":  {"name": "Ремонт ковша (базовый)",       "price": "от 15 000 руб.",   "days": "1-2 дня"},
    "bucket_hardox": {"name": "Hardox-бронирование ковша",    "price": "от 40 000 руб.",   "days": "2-3 дня"},
    "teeth":         {"name": "Замена зубьев (комплект)",      "price": "от 12 000 руб.",   "days": "1 день"},
    "knife":         {"name": "Замена ножа",                   "price": "от 12 000 руб.",   "days": "1 день"},
    "bushing":       {"name": "Восстановление втулок",         "price": "от 5 000 руб./шт", "days": "1-2 дня"},
    "hydraulics":    {"name": "Ремонт гидравлики",             "price": "от 25 000 руб.",   "days": "2-4 дня"},
    "cylinder":      {"name": "Ремонт гидроцилиндра",          "price": "от 10 000 руб.",   "days": "1-2 дня"},
    "undercarriage": {"name": "Ходовая часть",                 "price": "от 18 000 руб.",   "days": "2-4 дня"},
    "maintenance":   {"name": "Плановое ТО",                   "price": "от 10 000 руб.",   "days": "1 день"},
    "welding":       {"name": "Сварочные работы",              "price": "от 8 000 руб.",    "days": "1-2 дня"},
    "diagnostics":   {"name": "Диагностика (выезд)",           "price": "5 000 руб.",       "days": "в день заявки"},
}

RENTAL_TECH = {
    "exc_mini":     {"name": "Мини-экскаватор (до 6т)",          "price_hour": 1800,  "price_day": 14400},
    "exc_mid":      {"name": "Экскаватор средний (6-20т)",       "price_hour": 2500,  "price_day": 20000},
    "exc_heavy":    {"name": "Экскаватор тяжёлый (20т+)",        "price_hour": 3500,  "price_day": 28000},
    "exc_loader":   {"name": "Экскаватор-погрузчик (JCB, Case)", "price_hour": 2200,  "price_day": 17600},
    "loader_front": {"name": "Погрузчик фронтальный",            "price_hour": 2000,  "price_day": 16000},
    "loader_mini":  {"name": "Мини-погрузчик (Bobcat)",          "price_hour": 1800,  "price_day": 14400},
    "bulldozer":    {"name": "Бульдозер",                        "price_hour": 3000,  "price_day": 24000},
    "grader":       {"name": "Автогрейдер",                      "price_hour": 3200,  "price_day": 25600},
    "crane":        {"name": "Автокран (25-50т)",                "price_hour": 3500,  "price_day": 28000},
    "dump":         {"name": "Самосвал (10-20т)",                "price_hour": 1500,  "price_day": 12000},
    "manipulator":  {"name": "Манипулятор",                      "price_hour": 2000,  "price_day": 16000},
    "compactor":    {"name": "Каток дорожный",                   "price_hour": 2500,  "price_day": 20000},
}

WORK_TYPES = {
    "exc_mini":     ["Разработка котлована", "Рытьё траншей", "Планировка участка", "Демонтажные работы", "Благоустройство", "Другое"],
    "exc_mid":      ["Разработка котлована", "Рытьё траншей", "Вскрышные работы", "Погрузка грунта", "Демонтаж строений", "Другое"],
    "exc_heavy":    ["Разработка глубокого котлована", "Вскрышные работы", "Погрузка скальника", "Демонтаж капитальных строений", "Дорожные работы", "Другое"],
    "exc_loader":   ["Рытьё траншей под коммуникации", "Планировка и засыпка", "Погрузка материалов", "Расчистка территории", "Дорожные работы", "Другое"],
    "loader_front": ["Погрузка грунта / щебня / песка", "Расчистка снега", "Планировка площадки", "Перемещение материалов", "Складские работы", "Другое"],
    "loader_mini":  ["Погрузка в ограниченном пространстве", "Расчистка снега", "Планировка и засыпка", "Ландшафтные работы", "Складские работы", "Другое"],
    "bulldozer":    ["Расчистка территории", "Планировка площадки", "Рекультивация земель", "Разработка грунта", "Дорожные работы", "Другое"],
    "grader":       ["Профилирование дороги", "Планировка площадки", "Разравнивание щебня / грунта", "Содержание грунтовых дорог", "Снегоуборочные работы", "Другое"],
    "crane":        ["Монтаж конструкций", "Подъём оборудования", "Строительно-монтажные работы", "Разгрузка крупногабаритного груза", "Демонтаж конструкций", "Другое"],
    "dump":         ["Вывоз грунта", "Вывоз строительного мусора", "Доставка щебня / песка / ПГС", "Вывоз снега", "Перевозка сыпучих грузов", "Другое"],
    "manipulator":  ["Подъём и перемещение грузов", "Разгрузка стройматериалов", "Монтаж / демонтаж оборудования", "Перевозка с разгрузкой", "Другое"],
    "compactor":    ["Уплотнение грунта", "Уплотнение щебня / ПГС", "Устройство дорожного основания", "Уплотнение асфальта", "Другое"],
}

SHIFTS = {
    "s1":  {"name": "1 смена — 1 день",   "count": 1},
    "s2":  {"name": "2 смены — 2 дня",    "count": 2},
    "s3":  {"name": "3 смены — 3 дня",    "count": 3},
    "s5":  {"name": "5 смен — 5 дней",    "count": 5},
    "s10": {"name": "10 смен — 10 дней",  "count": 10},
    "s22": {"name": "22 смены — месяц",   "count": 22},
    "own": {"name": "Другое — уточним",   "count": 0},
}

URGENCY = {
    "standard": {"name": "Стандарт (2-3 дня)",       "mult": "x1"},
    "urgent":   {"name": "Срочно (24 часа) +30%",    "mult": "+30%"},
    "express":  {"name": "Экстренно (сегодня) +60%", "mult": "+60%"},
}

PAYMENT = {
    "cash":       {"name": "Наличные"},
    "bank_nds":   {"name": "Безнал с НДС"},
    "bank_nonds": {"name": "Безнал без НДС"},
}

ORDER_STATUSES = {
    "принята":    "Заявка принята, скоро свяжемся",
    "в работе":   "Ваша заявка взята в работу",
    "выполнено":  "Работа выполнена",
    "отменена":   "Заявка отменена",
}

# ─── СОСТОЯНИЯ ────────────────────────────────────────────────────────────────
class Order(StatesGroup):
    choosing_service  = State()
    choosing_rental   = State()
    choosing_shifts   = State()
    choosing_worktype = State()
    choosing_urgency  = State()
    choosing_payment  = State()
    entering_tech     = State()
    entering_location = State()
    entering_phone    = State()
    entering_comment  = State()
    confirm           = State()

class OwnerReply(StatesGroup):
    waiting_message = State()

class Review(StatesGroup):
    waiting_rating  = State()
    waiting_comment = State()

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def fmt(amount: int, prefix: bool = False) -> str:
    s = f"{amount:,}".replace(",", " ") + " руб."
    return ("от " + s) if prefix else s

def order_summary(data: dict) -> str:
    order_type = data.get("order_type", "repair")
    payment    = PAYMENT.get(data.get("payment", ""), {}).get("name", "-")
    if order_type == "rental":
        tech  = RENTAL_TECH.get(data.get("rental_tech", ""), {})
        shift = SHIFTS.get(data.get("shifts", "own"), {})
        count = shift.get("count", 0)
        if count > 0:
            total      = tech.get("price_day", 0) * count
            price_line = f"{shift['name']} x {fmt(tech.get('price_day',0), True)} = от {fmt(total)}"
        else:
            price_line = f"{fmt(tech.get('price_hour',0), True)}/час — уточним"
        return (
            "Заявка на аренду:\n\n"
            f"Техника:     {tech.get('name','-')}\n"
            f"Вид работ:   {data.get('work_type','-')}\n"
            f"Смены:       {shift.get('name','-')}\n"
            f"Стоимость:   {price_line}\n"
            f"Оплата:      {payment}\n"
            f"Адрес:       {data.get('location','-')}\n"
            f"Телефон:     {data.get('phone','-')}\n"
            f"Комментарий: {data.get('comment','нет')}"
        )
    else:
        svc = REPAIR_SERVICES.get(data.get("service",""), {})
        urg = URGENCY.get(data.get("urgency","standard"), {})
        return (
            "Заявка на ремонт:\n\n"
            f"Услуга:      {svc.get('name','-')}\n"
            f"Срочность:   {urg.get('name','-')}\n"
            f"Техника:     {data.get('tech','-')}\n"
            f"Адрес:       {data.get('location','-')}\n"
            f"Телефон:     {data.get('phone','-')}\n"
            f"Оплата:      {payment}\n"
            f"Комментарий: {data.get('comment','нет')}\n\n"
            f"Стоимость:   {svc.get('price','-')} ({urg.get('mult','')})\n"
            f"Срок:        {svc.get('days','-')}"
        )


async def _handle_callback(message: Message, phone: str, state: FSMContext):
    user = message.from_user
    db_track_user(user)
    await state.clear()
    await message.answer(
        "Отлично! Перезвоним вам в течение 15 минут.",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Пока ждёте — можете посмотреть наши услуги:", reply_markup=kb_main())
    await bot.send_message(
        OWNER_ID,
        f"ЗАПРОС НА ЗВОНОК\n"
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Клиент: {user.full_name}"
        + (f" (@{user.username})" if user.username else "") +
        f"\nТелефон: {phone}\n"
        f"TG ID: {user.id}"
    )

async def notify_owner(data: dict, user, order_id: int):
    label = "АРЕНДА" if data.get("order_type") == "rental" else "РЕМОНТ"
    header = (
        f"НОВАЯ ЗАЯВКА #{order_id} — {label}\n"
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Клиент: {user.full_name}"
        f"{' (@' + user.username + ')' if user.username else ''}\n"
        f"TG ID: {user.id}\n\n"
    )
    body = order_summary(data).replace("Заявка на аренду:\n\n","").replace("Заявка на ремонт:\n\n","")
    # кнопки смены статуса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ В работу",        callback_data=f"ss_{order_id}_{user.id}_inwork")],
        [InlineKeyboardButton(text="✅ Выполнено",       callback_data=f"ss_{order_id}_{user.id}_done")],
        [InlineKeyboardButton(text="💬 Написать клиенту", callback_data=f"msg_{order_id}_{user.id}")],
        [InlineKeyboardButton(text="❌ Отменить",        callback_data=f"ss_{order_id}_{user.id}_cancel")],
    ])
    await bot.send_message(OWNER_ID, header + body, reply_markup=kb)

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Заявка на ремонт", callback_data="start_repair")],
        [InlineKeyboardButton(text="🚜 Аренда техники",   callback_data="start_rental")],
        [InlineKeyboardButton(text="📞 Перезвоните мне",  callback_data="callback_request")],
        [InlineKeyboardButton(text="💰 Прайс-лист",       callback_data="show_prices")],
        [InlineKeyboardButton(text="☎️ Позвонить нам",    callback_data="call_us")],
    ])

def kb_repair_services():
    rows = []
    items = list(REPAIR_SERVICES.items())
    for i in range(0, len(items), 2):
        row = []
        for key, val in items[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"rep_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_rental_tech():
    rows = []
    items = list(RENTAL_TECH.items())
    for i in range(0, len(items), 2):
        row = []
        for key, val in items[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"rnt_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_work_types(tech_key: str):
    works = WORK_TYPES.get(tech_key, ["Другое"])
    rows  = []
    for i in range(0, len(works), 2):
        row = []
        for w in works[i:i+2]:
            idx = works.index(w)
            row.append(InlineKeyboardButton(text=w, callback_data=f"wrk_{tech_key}_{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="start_rental")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_shifts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 смена — 1 день",  callback_data="shf_s1")],
        [InlineKeyboardButton(text="2 смены — 2 дня",   callback_data="shf_s2"),
         InlineKeyboardButton(text="3 смены — 3 дня",   callback_data="shf_s3")],
        [InlineKeyboardButton(text="5 смен — 5 дней",   callback_data="shf_s5"),
         InlineKeyboardButton(text="10 смен — 10 дней", callback_data="shf_s10")],
        [InlineKeyboardButton(text="22 смены — месяц",  callback_data="shf_s22")],
        [InlineKeyboardButton(text="Другое — уточним",  callback_data="shf_own")],
        [InlineKeyboardButton(text="⬅️ Назад",          callback_data="start_rental")],
    ])

def kb_urgency():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стандарт (2-3 дня)",       callback_data="urg_standard")],
        [InlineKeyboardButton(text="Срочно (24 часа) +30%",    callback_data="urg_urgent")],
        [InlineKeyboardButton(text="Экстренно (сегодня) +60%", callback_data="urg_express")],
        [InlineKeyboardButton(text="⬅️ Назад",                 callback_data="start_repair")],
    ])

def kb_payment():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Наличные",        callback_data="pay_cash")],
        [InlineKeyboardButton(text="🏦 Безнал с НДС",    callback_data="pay_bank_nds")],
        [InlineKeyboardButton(text="🏦 Безнал без НДС",  callback_data="pay_bank_nonds")],
    ])

def kb_skip():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_comment")]
    ])

def kb_confirm():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="✏️ Изменить",         callback_data="confirm_no")],
    ])

def kb_phone():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def kb_rating():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data="rev_1"),
            InlineKeyboardButton(text="⭐ 2", callback_data="rev_2"),
            InlineKeyboardButton(text="⭐ 3", callback_data="rev_3"),
            InlineKeyboardButton(text="⭐ 4", callback_data="rev_4"),
            InlineKeyboardButton(text="⭐ 5", callback_data="rev_5"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="rev_skip")]
    ])

def kb_review_comment():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="rev_comment_skip")]
    ])

# ─── СТАРТ ────────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db_track_user(message.from_user)
    name = message.from_user.first_name or "Добро пожаловать"
    await message.answer(
        f"Привет, {name}! Добро пожаловать в VTehnike 24!\n\n"
        "Ремонт ковшей, восстановление спецтехники и аренда.\n"
        "Выезжаем на объект по всей Московской области.\n\n"
        "Ремонт ковша за 24 часа\n"
        "Приедем сами — никуда везти не надо\n"
        "Цену скажем за 15 минут по фото\n\n"
        "Чем могу помочь?",
        reply_markup=kb_main()
    )

# ─── КОМАНДЫ ВЛАДЕЛЬЦА ────────────────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer(db_get_stats())

@dp.message(Command("status"))
async def cmd_set_status(message: Message):
    """Использование: /status 42 выполнено"""
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /status [номер заявки] [статус]\nСтатусы: принята, в работе, выполнено, отменена")
        return
    try:
        order_id = int(parts[1])
    except ValueError:
        await message.answer("Номер заявки должен быть числом")
        return
    status = parts[2].strip().lower()
    if status not in ORDER_STATUSES:
        await message.answer(f"Неверный статус. Доступные: {', '.join(ORDER_STATUSES.keys())}")
        return
    await _apply_status(message, order_id, status)


@dp.callback_query(F.data.startswith("msg_"))
async def cb_message_client(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        return
    parts    = cb.data.split("_")
    order_id = int(parts[1])
    user_id  = int(parts[2])
    await state.update_data(reply_order_id=order_id, reply_user_id=user_id)
    await state.set_state(OwnerReply.waiting_message)
    await cb.message.answer(
        f"Введите сообщение для клиента по заявке #{order_id}:\n"
        f"(оно придёт от имени бота)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_reply")]
        ])
    )
    await cb.answer()

@dp.callback_query(F.data == "cancel_reply")
async def cancel_reply(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Отменено.")
    await cb.answer()

@dp.message(OwnerReply.waiting_message)
async def send_message_to_client(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    data     = await state.get_data()
    order_id = data.get("reply_order_id")
    user_id  = data.get("reply_user_id")
    await state.clear()
    try:
        await bot.send_message(
            user_id,
            f"Сообщение от VTehnike 24 по заявке #{order_id}:\n\n"
            f"{message.text}\n\n"
            f"Если есть вопросы — +7 (992) 350-80-08"
        )
        await message.answer(f"Сообщение отправлено клиенту по заявке #{order_id}.")
    except Exception:
        await message.answer("Не удалось отправить — клиент заблокировал бота или удалил чат.")

@dp.callback_query(F.data.startswith("ss_"))
async def cb_set_status(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        return
    # формат: ss_42_123456789_inwork
    parts    = cb.data.split("_")  # ss, order_id, user_id, status_code
    order_id = int(parts[1])
    user_id  = int(parts[2])
    code     = parts[3]
    status_map = {"inwork": "в работе", "done": "выполнено", "cancel": "отменена"}
    status   = status_map.get(code, code)
    await _apply_status(cb.message, order_id, status, user_id=user_id)
    await cb.answer(f"Статус изменён: {status}")

async def _apply_status(msg_or_message, order_id: int, status: str, user_id: int = None):
    order = db_get_order(order_id)
    if not order:
        await msg_or_message.answer(f"Заявка #{order_id} не найдена")
        return
    db_update_status(order_id, status)
    client_id = user_id or order[1]
    status_text = ORDER_STATUSES.get(status, status)
    try:
        await bot.send_message(
            client_id,
            f"Заявка #{order_id}\n\n"
            f"Статус изменён: {status_text}\n\n"
            "Если есть вопросы — позвоните: +7 (992) 350-80-08"
        )
        # если выполнено — просим отзыв
        if status == "выполнено":
            await bot.send_message(
                client_id,
                "Оцените нашу работу — это займёт 30 секунд и поможет нам стать лучше:",
                reply_markup=kb_rating()
            )
    except Exception:
        pass
    await msg_or_message.answer(f"Статус заявки #{order_id} изменён на «{status}», клиент уведомлён.")


@dp.message(Command("orders"))
async def cmd_orders(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    rows = db_get_active_orders()
    if not rows:
        await message.answer("Нет активных заявок.")
        return
    for row in rows:
        order_id, user_id, order_type, status, created_at, name, username = row
        label   = "АРЕНДА" if order_type == "rental" else "РЕМОНТ"
        tag     = f"@{username}" if username else f"ID {user_id}"
        client  = f"{name} ({tag})"
        status_emoji = {"принята": "🆕", "в работе": "🔧"}.get(status, "📋")
        await message.answer(
            f"{status_emoji} Заявка #{order_id} — {label}\n"
            f"Клиент: {client}\n"
            f"Статус: {status}\n"
            f"Создана: {created_at}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ В работу",       callback_data=f"ss_{order_id}_{user_id}_inwork")],
                [InlineKeyboardButton(text="✅ Выполнено",      callback_data=f"ss_{order_id}_{user_id}_done")],
                [InlineKeyboardButton(text="💬 Написать клиенту", callback_data=f"msg_{order_id}_{user_id}")],
                [InlineKeyboardButton(text="❌ Отменить",       callback_data=f"ss_{order_id}_{user_id}_cancel")],
            ])
        )

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Рассылка: /broadcast Текст сообщения"""
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /broadcast Текст который получат все пользователи")
        return
    text    = parts[1]
    user_ids = db_get_all_user_ids()
    sent    = 0
    failed  = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"Рассылка завершена.\nОтправлено: {sent}\nНе доставлено: {failed}")

# ─── ОТЗЫВЫ ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("rev_"))
async def handle_review(cb: CallbackQuery, state: FSMContext):
    data = cb.data.replace("rev_", "")
    if data == "skip":
        await cb.message.answer("Спасибо! Будем рады видеть вас снова.", reply_markup=kb_main())
        return
    if data.isdigit():
        rating = int(data)
        await state.update_data(review_rating=rating, review_msg_id=cb.message.message_id)
        await state.set_state(Review.waiting_comment)
        stars = "⭐" * rating
        await cb.message.answer(
            f"Спасибо за оценку {stars}!\n\nОставьте короткий комментарий или нажмите Пропустить:",
            reply_markup=kb_review_comment()
        )
    await cb.answer()

@dp.callback_query(F.data == "rev_comment_skip", Review.waiting_comment)
async def review_comment_skip(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db_add_review(cb.from_user.id, data.get("last_order_id", 0), data.get("review_rating", 5), "")
    await state.clear()
    await cb.message.answer("Спасибо за отзыв! Это очень важно для нас.", reply_markup=kb_main())
    await bot.send_message(
        OWNER_ID,
        f"Новый отзыв от {cb.from_user.full_name}:\n"
        f"Оценка: {'⭐' * data.get('review_rating', 5)}\n"
        f"Заявка #{data.get('last_order_id', '?')}"
    )

@dp.message(Review.waiting_comment)
async def review_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    db_add_review(message.from_user.id, data.get("last_order_id", 0), data.get("review_rating", 5), message.text)
    await state.clear()
    await message.answer("Спасибо за отзыв! Это очень важно для нас.", reply_markup=kb_main())
    await bot.send_message(
        OWNER_ID,
        f"Новый отзыв от {message.from_user.full_name}:\n"
        f"Оценка: {'⭐' * data.get('review_rating', 5)}\n"
        f"Комментарий: {message.text}\n"
        f"Заявка #{data.get('last_order_id', '?')}"
    )

# ─── ПРОЧИЕ КОМАНДЫ ───────────────────────────────────────────────────────────
@dp.message(Command("prices"))
async def cmd_prices(message: Message):
    text = "Прайс — Ремонт спецтехники\n\n"
    for svc in REPAIR_SERVICES.values():
        text += f"{svc['name']}\n{svc['price']} — {svc['days']}\n\n"
    text += "Точная стоимость — после фото или осмотра"
    await message.answer(text)

@dp.message(Command("rental"))
async def cmd_rental_prices(message: Message):
    text = "Прайс — Аренда спецтехники\n1 смена = 1 рабочий день = 8 часов\n\n"
    for t in RENTAL_TECH.values():
        text += f"{t['name']}\n{fmt(t['price_hour'], True)}/час — {fmt(t['price_day'], True)}/смена\n\n"
    text += "С оператором — Выезд по МО — ИП и ООО"
    await message.answer(text)

@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await message.answer(
        "Контакты VTehnike 24\n\n"
        "Телефон: +7 (992) 350-80-08\n"
        "Сайт: www.vtehnike24.ru\n"
        "МО — выезжаем на любой объект\n\n"
        "Пн-Сб 8:00-20:00\n"
        "Экстренные выезды — круглосуточно"
    )

# ─── ГЛАВНОЕ МЕНЮ ─────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Главное меню:", reply_markup=kb_main())


@dp.callback_query(F.data == "callback_request")
async def callback_request(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(order_type="callback")
    await state.set_state(Order.entering_phone)
    await cb.message.answer(
        "Оставьте номер телефона — перезвоним в течение 15 минут:",
        reply_markup=kb_phone()
    )

@dp.callback_query(F.data == "call_us")
async def call_us(cb: CallbackQuery):
    await cb.message.answer(
        "Позвоните нам:\n\n"
        "+7 (992) 350-80-08\n\n"
        "Пн-Сб 8:00-20:00\n"
        "Экстренные выезды — круглосуточно\n\n"
        "Или оставьте заявку — перезвоним:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="start_repair")],
            [InlineKeyboardButton(text="Главное меню",    callback_data="back_main")],
        ])
    )

@dp.callback_query(F.data == "show_prices")
async def show_prices(cb: CallbackQuery):
    text = "Прайс — Ремонт спецтехники\n\n"
    for svc in REPAIR_SERVICES.values():
        text += f"{svc['name']}\n{svc['price']} — {svc['days']}\n\n"
    text += "Точная стоимость — после фото или осмотра"
    await cb.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оставить заявку", callback_data="start_repair")],
        [InlineKeyboardButton(text="Главное меню",    callback_data="back_main")],
    ]))

# ─── РЕМОНТ ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "start_repair")
async def start_repair(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(order_type="repair")
    await state.set_state(Order.choosing_service)
    await cb.message.answer("Выберите услугу:", reply_markup=kb_repair_services())

@dp.callback_query(F.data.startswith("rep_"), Order.choosing_service)
async def choose_repair_service(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("rep_", "")
    svc = REPAIR_SERVICES[key]
    await state.update_data(service=key)
    await state.set_state(Order.choosing_urgency)
    await cb.message.answer(
        f"Выбрано: {svc['name']}\nЦена: {svc['price']} — {svc['days']}\n\nВыберите срочность:",
        reply_markup=kb_urgency()
    )

@dp.callback_query(F.data.startswith("urg_"), Order.choosing_urgency)
async def choose_urgency(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("urg_", "")
    await state.update_data(urgency=key)
    await state.set_state(Order.entering_tech)
    await cb.message.answer(
        f"Срочность: {URGENCY[key]['name']}\n\n"
        "Укажите тип и марку техники:\nНапример: Экскаватор Komatsu PC200"
    )

# ─── АРЕНДА ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "start_rental")
async def start_rental(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(order_type="rental")
    await state.set_state(Order.choosing_rental)
    await cb.message.answer("Выберите технику для аренды:", reply_markup=kb_rental_tech())

@dp.callback_query(F.data.startswith("rnt_"), Order.choosing_rental)
async def choose_rental_tech(cb: CallbackQuery, state: FSMContext):
    key  = cb.data.replace("rnt_", "")
    tech = RENTAL_TECH[key]
    await state.update_data(rental_tech=key)
    await state.set_state(Order.choosing_worktype)
    await cb.message.answer(
        f"Выбрано: {tech['name']}\n"
        f"Цена: {fmt(tech['price_hour'], True)}/час — {fmt(tech['price_day'], True)}/смена\n\n"
        "Выберите вид работ:",
        reply_markup=kb_work_types(key)
    )

@dp.callback_query(F.data.startswith("wrk_"), Order.choosing_worktype)
async def choose_work_type(cb: CallbackQuery, state: FSMContext):
    parts    = cb.data.split("_")
    idx      = int(parts[-1])
    tech_key = "_".join(parts[1:-1])
    works    = WORK_TYPES.get(tech_key, ["Другое"])
    work_name = works[idx] if idx < len(works) else "Другое"
    await state.update_data(work_type=work_name)
    await state.set_state(Order.choosing_shifts)
    await cb.message.answer(
        f"Вид работ: {work_name}\n\nСколько смен нужно?\n(1 смена = 1 рабочий день = 8 часов)",
        reply_markup=kb_shifts()
    )

@dp.callback_query(F.data.startswith("shf_"), Order.choosing_shifts)
async def choose_shifts(cb: CallbackQuery, state: FSMContext):
    key   = cb.data.replace("shf_", "")
    shift = SHIFTS[key]
    data  = await state.get_data()
    tech  = RENTAL_TECH.get(data.get("rental_tech",""), {})
    await state.update_data(shifts=key)
    await state.set_state(Order.entering_location)
    count = shift.get("count", 0)
    price_line = f"Итого: от {fmt(tech.get('price_day',0) * count)}" if count > 0 else f"{fmt(tech.get('price_hour',0), True)}/час — уточним"
    await cb.message.answer(
        f"Смены: {shift['name']}\n{price_line}\n\n"
        "Укажите адрес объекта или район:"
    )

# ─── ОБЩИЙ СБОР ДАННЫХ ────────────────────────────────────────────────────────
@dp.message(Order.entering_tech)
async def enter_tech(message: Message, state: FSMContext):
    await state.update_data(tech=message.text)
    await state.set_state(Order.entering_location)
    await message.answer("Укажите адрес объекта или район:")

@dp.message(Order.entering_location)
async def enter_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text)
    await state.set_state(Order.entering_phone)
    await message.answer("Укажите номер телефона:", reply_markup=kb_phone())

@dp.message(Order.entering_phone, F.contact)
async def enter_phone_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("order_type") == "callback":
        await _handle_callback(message, message.contact.phone_number, state)
        return
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Order.choosing_payment)
    await message.answer("Выберите форму оплаты:", reply_markup=ReplyKeyboardRemove())
    await message.answer("👇", reply_markup=kb_payment())

@dp.message(Order.entering_phone)
async def enter_phone_text(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("order_type") == "callback":
        await _handle_callback(message, message.text, state)
        return
    await state.update_data(phone=message.text)
    await state.set_state(Order.choosing_payment)
    await message.answer("Выберите форму оплаты:", reply_markup=ReplyKeyboardRemove())
    await message.answer("👇", reply_markup=kb_payment())

@dp.callback_query(F.data.startswith("pay_"), Order.choosing_payment)
async def choose_payment(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("pay_", "")
    await state.update_data(payment=key)
    await state.set_state(Order.entering_comment)
    await cb.message.answer(
        f"Оплата: {PAYMENT[key]['name']}\n\nДобавьте комментарий или нажмите Пропустить:",
        reply_markup=kb_skip()
    )

@dp.callback_query(F.data == "skip_comment", Order.entering_comment)
async def skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await cb.message.answer(order_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm())

@dp.message(Order.entering_comment)
async def enter_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await message.answer(order_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm())

# ─── ПОДТВЕРЖДЕНИЕ ────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "confirm_yes", Order.confirm)
async def confirm_order(cb: CallbackQuery, state: FSMContext):
    data     = await state.get_data()
    summary  = order_summary(data)
    order_id = db_add_order(cb.from_user.id, data.get("order_type","repair"), summary)
    await notify_owner(data, cb.from_user, order_id)
    await state.update_data(last_order_id=order_id)
    await state.clear()
    msg = f"Заявка #{order_id} принята!\n\nСвяжемся с вами в течение 15 минут.\n\n"
    if data.get("order_type") == "repair":
        msg += "Можете прислать фото неисправности — поможет точнее назвать цену.\n\n"
    msg += "Спасибо, что выбрали VTehnike 24!"
    await cb.message.answer(msg, reply_markup=kb_main())

@dp.callback_query(F.data == "confirm_no", Order.confirm)
async def cancel_order(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Хорошо, начнём заново:", reply_markup=kb_main())

# ─── ФОТО ─────────────────────────────────────────────────────────────────────
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    # Пересылаем владельцу
    await bot.forward_message(OWNER_ID, message.chat.id, message.message_id)

    # Ищем последнюю активную заявку клиента
    with db_connect() as con:
        row = con.execute(
            """SELECT id FROM orders
               WHERE user_id=? AND status NOT IN ('выполнено','отменена')
               ORDER BY created_at DESC LIMIT 1""",
            (message.from_user.id,)
        ).fetchone()

    if row:
        order_id = row[0]
        await bot.send_message(
            OWNER_ID,
            f"Фото от {message.from_user.full_name} (ID: {message.from_user.id})\n"
            f"Прикреплено к заявке #{order_id}"
        )
        await message.answer(
            f"Фото получено и прикреплено к заявке #{order_id}.\nСвяжемся в течение 15 минут.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Главное меню", callback_data="back_main")]
            ])
        )
    else:
        await bot.send_message(
            OWNER_ID,
            f"Фото от {message.from_user.full_name} (ID: {message.from_user.id})\n"
            f"Активных заявок нет"
        )
        await message.answer(
            "Фото получено! Оценим и свяжемся в течение 15 минут.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Главное меню", callback_data="back_main")]
            ])
        )

# ─── FALLBACK ─────────────────────────────────────────────────────────────────
@dp.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        return
    await message.answer("Воспользуйтесь меню:", reply_markup=kb_main())


# ─── ФОНОВАЯ ЗАДАЧА — НАПОМИНАНИЕ О ЗАЯВКЕ ───────────────────────────────────
async def reminder_task():
    """Каждые 30 минут проверяем заявки которые висят более 2 часов без ответа"""
    await asyncio.sleep(60)  # старт через минуту после запуска бота
    while True:
        try:
            pending = db_get_pending_orders(minutes=120)
            for order in pending:
                label = "АРЕНДА" if order["type"] == "rental" else "РЕМОНТ"
                await bot.send_message(
                    OWNER_ID,
                    f"НАПОМИНАНИЕ\n\n"
                    f"Заявка #{order['id']} ({label}) висит без ответа!\n"
                    f"Создана: {order['created_at']}\n\n"
                    f"Свяжись с клиентом.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="▶️ В работу", callback_data=f"ss_{order['id']}_{order['user_id']}_inwork")],
                        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"ss_{order['id']}_{order['user_id']}_cancel")],
                    ])
                )
        except Exception as e:
            logging.error(f"Reminder error: {e}")
        await asyncio.sleep(30 * 60)  # следующая проверка через 30 минут

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
async def main():
    db_init()
    print("VTehnike 24 Bot v8.0 запущен!")
    asyncio.create_task(reminder_task())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
