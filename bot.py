"""
VTehnike 24 — Telegram Bot v12.0
Три направления:
  🚜 Аренда техники
  🏗️ Демонтаж, земляные работы и благоустройство
  🔧 VTehnike 24 Service — сервис и ремонт
"""

import asyncio
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
BOT_TOKEN = "7151969834:AAHLEnwxwfpaaERnJaOYiiA6ctXJoxvR4C8"
OWNER_ID   = 125380747
DB_FILE    = "/data/vtehnike.db"
PHONE      = "+7 (992) 350-80-08"
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ─── БАЗА ДАННЫХ ──────────────────────────────────────────────────────────────
def db_connect():
    return sqlite3.connect(DB_FILE)

def db_init():
    with db_connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY,
                name       TEXT,
                username   TEXT,
                first_seen TEXT,
                last_seen  TEXT,
                visits     INTEGER DEFAULT 1
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                section    TEXT,
                order_type TEXT,
                summary    TEXT,
                status     TEXT DEFAULT 'принята',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                order_id   INTEGER,
                rating     INTEGER,
                comment    TEXT,
                created_at TEXT
            )
        """)
        con.commit()

        # Миграция: добавить колонки если их нет (для старых баз данных)
        for migration in [
            "ALTER TABLE orders ADD COLUMN section TEXT DEFAULT 'rental'",
            "ALTER TABLE orders ADD COLUMN order_type TEXT DEFAULT 'rental'",
        ]:
            try:
                con.execute(migration)
                con.commit()
            except Exception:
                pass  # колонка уже существует

def db_track_user(user) -> bool:
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
        con.execute(
            "UPDATE users SET last_seen=?, visits=visits+1, name=?, username=? WHERE id=?",
            (now, user.full_name, user.username or "", user.id)
        )
        con.commit()
        return False

def db_add_order(user_id: int, section: str, order_type: str, summary: str) -> int:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with db_connect() as con:
        cur = con.execute(
            "INSERT INTO orders (user_id, section, order_type, summary, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, section, order_type, summary, "принята", now, now)
        )
        con.commit()
        return cur.lastrowid

def db_update_status(order_id: int, status: str):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with db_connect() as con:
        con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, now, order_id))
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

def db_get_active_orders() -> list:
    with db_connect() as con:
        return con.execute(
            """SELECT o.id, o.user_id, o.section, o.order_type, o.status, o.created_at,
                      u.name, u.username
               FROM orders o LEFT JOIN users u ON o.user_id = u.id
               WHERE o.status NOT IN ('выполнено','отменена')
               ORDER BY o.created_at DESC"""
        ).fetchall()

def db_get_client_orders(user_id: int) -> list:
    with db_connect() as con:
        return con.execute(
            "SELECT id, section, order_type, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        ).fetchall()

def db_get_all_user_ids() -> list:
    with db_connect() as con:
        return [r[0] for r in con.execute("SELECT id FROM users").fetchall()]

def db_get_pending_orders(minutes: int = 120) -> list:
    with db_connect() as con:
        rows = con.execute(
            "SELECT id, user_id, section, created_at FROM orders WHERE status='принята'"
        ).fetchall()
    result = []
    now = datetime.now()
    for row in rows:
        try:
            created = datetime.strptime(row[3], "%d.%m.%Y %H:%M")
            if (now - created).total_seconds() > minutes * 60:
                result.append({"id": row[0], "user_id": row[1], "section": row[2], "created_at": row[3]})
        except Exception:
            pass
    return result

def db_get_stats() -> str:
    with db_connect() as con:
        total_users  = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_orders = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        rental_cnt   = con.execute("SELECT COUNT(*) FROM orders WHERE section='rental'").fetchone()[0]
        works_cnt    = con.execute("SELECT COUNT(*) FROM orders WHERE section='works'").fetchone()[0]
        service_cnt  = con.execute("SELECT COUNT(*) FROM orders WHERE section='service'").fetchone()[0]
        done_cnt     = con.execute("SELECT COUNT(*) FROM orders WHERE status='выполнено'").fetchone()[0]
        avg_rating   = con.execute("SELECT AVG(rating) FROM reviews").fetchone()[0]
        review_cnt   = con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        recent       = con.execute(
            "SELECT name, username, last_seen FROM users ORDER BY last_seen DESC LIMIT 5"
        ).fetchall()
    rating_str = f"{avg_rating:.1f}/5 ({review_cnt} отзывов)" if avg_rating else "пока нет"
    recent_str = ""
    for name, username, last_seen in recent:
        tag = f"@{username}" if username else ""
        recent_str += f"  {name} {tag} — {last_seen}\n"
    return (
        f"Статистика VTehnike 24\n\n"
        f"Пользователей:   {total_users}\n"
        f"Всего заявок:    {total_orders}\n"
        f"  аренда:        {rental_cnt}\n"
        f"  работы:        {works_cnt}\n"
        f"  сервис:        {service_cnt}\n"
        f"  выполнено:     {done_cnt}\n"
        f"Средний отзыв:   {rating_str}\n\n"
        f"Последние 5:\n{recent_str}"
    )

def db_get_weekly_stats() -> str:
    with db_connect() as con:
        week_ago    = (datetime.now() - timedelta(days=7)).strftime("%d.%m.%Y")
        new_users   = con.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ?", (week_ago,)).fetchone()[0]
        new_orders  = con.execute("SELECT COUNT(*) FROM orders WHERE created_at >= ?", (week_ago,)).fetchone()[0]
        rental_cnt  = con.execute("SELECT COUNT(*) FROM orders WHERE section='rental' AND created_at >= ?", (week_ago,)).fetchone()[0]
        works_cnt   = con.execute("SELECT COUNT(*) FROM orders WHERE section='works' AND created_at >= ?", (week_ago,)).fetchone()[0]
        service_cnt = con.execute("SELECT COUNT(*) FROM orders WHERE section='service' AND created_at >= ?", (week_ago,)).fetchone()[0]
        done_cnt    = con.execute("SELECT COUNT(*) FROM orders WHERE status='выполнено' AND updated_at >= ?", (week_ago,)).fetchone()[0]
        avg_rating  = con.execute("SELECT AVG(rating) FROM reviews WHERE created_at >= ?", (week_ago,)).fetchone()[0]
    rating_str = f"{avg_rating:.1f}/5" if avg_rating else "нет"
    return (
        f"Сводка за 7 дней\n{datetime.now().strftime('%d.%m.%Y')}\n\n"
        f"Новых пользователей: {new_users}\n"
        f"Новых заявок:        {new_orders}\n"
        f"  аренда:            {rental_cnt}\n"
        f"  работы:            {works_cnt}\n"
        f"  сервис:            {service_cnt}\n"
        f"Выполнено:           {done_cnt}\n"
        f"Средний отзыв:       {rating_str}"
    )

# ─── ДАННЫЕ ───────────────────────────────────────────────────────────────────
def is_working_hours() -> bool:
    now = datetime.now()
    if now.weekday() == 6:
        return False
    return 8 <= now.hour < 20

def fmt(amount: int, prefix: bool = False) -> str:
    s = f"{amount:,}".replace(",", " ") + " руб."
    return ("от " + s) if prefix else s

# ─── АРЕНДА ТЕХНИКИ ───────────────────────────────────────────────────────────
RENTAL_TECH = {
    "exc_mini":     {"name": "Мини-экскаватор (до 6т)",          "price_hour": 1800, "price_day": 14400},
    "exc_mid":      {"name": "Экскаватор средний (6-20т)",       "price_hour": 2500, "price_day": 20000},
    "exc_heavy":    {"name": "Экскаватор тяжёлый (20т+)",        "price_hour": 3500, "price_day": 28000},
    "exc_loader":   {"name": "Экскаватор-погрузчик (JCB, Case)", "price_hour": 2200, "price_day": 17600},
    "loader_front": {"name": "Погрузчик фронтальный",            "price_hour": 2000, "price_day": 16000},
    "loader_mini":  {"name": "Мини-погрузчик (Bobcat)",          "price_hour": 1800, "price_day": 14400},
    "bulldozer":    {"name": "Бульдозер",                        "price_hour": 3000, "price_day": 24000},
    "grader":       {"name": "Автогрейдер",                      "price_hour": 3200, "price_day": 25600},
    "crane":        {"name": "Автокран (25-50т)",                "price_hour": 3500, "price_day": 28000},
    "dump":         {"name": "Самосвал (10-20т)",                "price_hour": 1500, "price_day": 12000},
    "manipulator":  {"name": "Манипулятор",                      "price_hour": 2000, "price_day": 16000},
    "compactor":    {"name": "Каток дорожный",                   "price_hour": 2500, "price_day": 20000},
}

RENTAL_WORK_TYPES = {
    "exc_mini":     ["Разработка котлована", "Рытьё траншей", "Планировка участка", "Демонтажные работы", "Благоустройство", "Другое"],
    "exc_mid":      ["Разработка котлована", "Рытьё траншей", "Вскрышные работы", "Погрузка грунта", "Демонтаж строений", "Другое"],
    "exc_heavy":    ["Разработка глубокого котлована", "Вскрышные работы", "Погрузка скальника", "Демонтаж капитальных строений", "Дорожные работы", "Другое"],
    "exc_loader":   ["Рытьё траншей под коммуникации", "Планировка и засыпка", "Погрузка материалов", "Расчистка территории", "Дорожные работы", "Другое"],
    "loader_front": ["Погрузка грунта / щебня / песка", "Расчистка снега", "Планировка площадки", "Перемещение материалов", "Складские работы", "Другое"],
    "loader_mini":  ["Погрузка в ограниченном пространстве", "Расчистка снега", "Планировка и засыпка", "Ландшафтные работы", "Другое"],
    "bulldozer":    ["Расчистка территории", "Планировка площадки", "Рекультивация земель", "Разработка грунта", "Дорожные работы", "Другое"],
    "grader":       ["Профилирование дороги", "Планировка площадки", "Разравнивание щебня / грунта", "Снегоуборочные работы", "Другое"],
    "crane":        ["Монтаж конструкций", "Подъём оборудования", "Строительно-монтажные работы", "Разгрузка крупногабаритного груза", "Другое"],
    "dump":         ["Вывоз грунта", "Вывоз строительного мусора", "Доставка щебня / песка / ПГС", "Вывоз снега", "Перевозка сыпучих грузов", "Другое"],
    "manipulator":  ["Подъём и перемещение грузов", "Разгрузка стройматериалов", "Монтаж / демонтаж оборудования", "Другое"],
    "compactor":    ["Уплотнение грунта", "Уплотнение щебня / ПГС", "Устройство дорожного основания", "Уплотнение асфальта", "Другое"],
}

SHIFTS = {
    "s1":  {"name": "1 смена — 1 день",  "count": 1},
    "s2":  {"name": "2 смены — 2 дня",   "count": 2},
    "s3":  {"name": "3 смены — 3 дня",   "count": 3},
    "s5":  {"name": "5 смен — 5 дней",   "count": 5},
    "s10": {"name": "10 смен — 10 дней", "count": 10},
    "s22": {"name": "22 смены — месяц",  "count": 22},
    "own": {"name": "Другое — уточним",  "count": 0},
}

# ─── ДЕМОНТАЖ, ЗЕМЛЯНЫЕ РАБОТЫ И БЛАГОУСТРОЙСТВО ────────────────────────────
WORKS_CATEGORIES = {
    "demolition": {"name": "Демонтаж"},
    "earthwork":  {"name": "Земляные работы"},
    "landscape":  {"name": "Благоустройство"},
}

WORKS_SERVICES = {
    "demolition": {
        "dem_building":    {"name": "Снос зданий и сооружений",              "price": "по объёму"},
        "dem_foundation":  {"name": "Демонтаж фундаментов",                  "price": "по объёму"},
        "dem_fence":       {"name": "Демонтаж заборов и ограждений",         "price": "от 500 руб./м"},
        "dem_asphalt":     {"name": "Демонтаж асфальта и покрытий",          "price": "по площади"},
        "dem_partitions":  {"name": "Демонтаж перегородок и перекрытий",     "price": "по объёму"},
    },
    "earthwork": {
        "ew_pit":          {"name": "Разработка котлована",                  "price": "по объёму"},
        "ew_trench":       {"name": "Рытьё траншей",                         "price": "по объёму"},
        "ew_planning":     {"name": "Планировка участка",                    "price": "по площади"},
        "ew_vplanning":    {"name": "Вертикальная планировка",               "price": "по площади"},
        "ew_backfill":     {"name": "Обратная засыпка",                      "price": "по объёму"},
        "ew_drainage":     {"name": "Дренаж и водоотведение",                "price": "по объёму"},
        "ew_piles":        {"name": "Устройство свайных полей",              "price": "по объёму"},
    },
    "landscape": {
        "ls_road":         {"name": "Устройство въездов и дорог",            "price": "по площади"},
        "ls_backfill":     {"name": "Отсыпка территории",                    "price": "по объёму"},
        "ls_clearing":     {"name": "Расчистка территории",                  "price": "по площади"},
        "ls_trees":        {"name": "Снос деревьев и пней",                  "price": "от 3 000 руб./шт"},
        "ls_greening":     {"name": "Озеленение",                            "price": "по проекту"},
        "ls_paving":       {"name": "Укладка тротуарной плитки и брусчатки", "price": "от 1 500 руб./м²"},
        "ls_lawn":         {"name": "Устройство газона",                     "price": "от 300 руб./м²"},
    },
}

# ─── СЕРВИС И РЕМОНТ ──────────────────────────────────────────────────────────
SERVICE_CATEGORIES = {
    "repair":  {"name": "Сервис и ремонт техники"},
    "special": {"name": "Выездные услуги"},
}

SERVICE_SERVICES = {
    "repair": {
        "bucket_basic":  {"name": "Ремонт ковша (базовый)",       "price": "от 15 000 руб.", "days": "1-2 дня"},
        "bucket_hardox": {"name": "Hardox-бронирование ковша",    "price": "от 40 000 руб.", "days": "2-3 дня"},
        "teeth":         {"name": "Замена зубьев (комплект)",      "price": "от 12 000 руб.", "days": "1 день"},
        "knife":         {"name": "Замена ножа",                   "price": "от 12 000 руб.", "days": "1 день"},
        "bushing":       {"name": "Восстановление втулок",         "price": "от 5 000 руб./шт","days": "1-2 дня"},
        "hydraulics":    {"name": "Ремонт гидравлики",             "price": "от 25 000 руб.", "days": "2-4 дня"},
        "cylinder":      {"name": "Ремонт гидроцилиндра",          "price": "от 10 000 руб.", "days": "1-2 дня"},
        "undercarriage": {"name": "Ходовая часть",                 "price": "от 18 000 руб.", "days": "2-4 дня"},
        "maintenance":   {"name": "Плановое ТО",                   "price": "от 10 000 руб.", "days": "1 день"},
        "welding":       {"name": "Сварочные работы",              "price": "от 8 000 руб.",  "days": "1-2 дня"},
        "diagnostics":   {"name": "Диагностика (выезд)",           "price": "5 000 руб.",     "days": "в день заявки"},
    },
    "special": {
        "fuel":          {"name": "Заправка топливом на объекте",  "price": "по объёму",      "days": "в день заявки"},
        "duty":          {"name": "Техническое дежурство",         "price": "от 8 000 руб./смена","days": "по договору"},
        "towing":        {"name": "Эвакуация и буксировка техники","price": "от 5 000 руб.",  "days": "в день заявки"},
    },
}

SERVICE_URGENCY = {
    "standard": {"name": "Стандарт (2-3 дня)", "mult": "x1"},
    "urgent":   {"name": "Срочно (24 часа) +30%", "mult": "+30%"},
    "express":  {"name": "Экстренно (сегодня) +60%", "mult": "+60%"},
}

PAYMENT = {
    "cash":       {"name": "Наличные"},
    "bank_nds":   {"name": "Безнал с НДС"},
    "bank_nonds": {"name": "Безнал без НДС"},
}

ORDER_STATUSES = {
    "принята":   "Заявка принята, скоро свяжемся",
    "в работе":  "Ваша заявка взята в работу",
    "выполнено": "Работа выполнена",
    "отменена":  "Заявка отменена",
}

# ─── СОСТОЯНИЯ ────────────────────────────────────────────────────────────────
class Rental(StatesGroup):
    choosing_tech     = State()
    choosing_worktype = State()
    choosing_shifts   = State()
    entering_location = State()
    entering_phone    = State()
    choosing_payment  = State()
    entering_comment  = State()
    confirm           = State()

class Works(StatesGroup):
    choosing_category = State()
    choosing_service  = State()
    entering_location = State()
    entering_phone    = State()
    choosing_payment  = State()
    entering_comment  = State()
    confirm           = State()

class Service(StatesGroup):
    choosing_category = State()
    choosing_service  = State()
    choosing_urgency  = State()
    choosing_fuel     = State()
    entering_tech     = State()
    entering_location = State()
    entering_phone    = State()
    choosing_payment  = State()
    entering_comment  = State()
    confirm           = State()

class OwnerReply(StatesGroup):
    waiting_message = State()

class Review(StatesGroup):
    waiting_comment = State()

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚜 Аренда техники",                   callback_data="start_rental")],
        [InlineKeyboardButton(text="🏗 Демонтаж, земляные работы, благ.", callback_data="start_works")],
        [InlineKeyboardButton(text="🔧 VTehnike 24 Service",              callback_data="start_service")],
        [InlineKeyboardButton(text="📋 Мои заявки",                       callback_data="my_orders")],
        [InlineKeyboardButton(text="📞 Перезвоните мне",                  callback_data="callback_request")],
        [InlineKeyboardButton(text="☎️ Позвонить нам",                    callback_data="call_us")],
    ])

def kb_back_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_main")]
    ])

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

def kb_rental_worktype(tech_key: str):
    works = RENTAL_WORK_TYPES.get(tech_key, ["Другое"])
    rows = []
    for i in range(0, len(works), 2):
        row = []
        for w in works[i:i+2]:
            idx = works.index(w)
            row.append(InlineKeyboardButton(text=w, callback_data=f"rwt_{tech_key}_{idx}"))
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

def kb_works_categories():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Демонтаж",           callback_data="wcat_demolition")],
        [InlineKeyboardButton(text="Земляные работы",    callback_data="wcat_earthwork")],
        [InlineKeyboardButton(text="Благоустройство",    callback_data="wcat_landscape")],
        [InlineKeyboardButton(text="⬅️ Главное меню",   callback_data="back_main")],
    ])

def kb_works_services(category: str):
    services = WORKS_SERVICES.get(category, {})
    rows = []
    items = list(services.items())
    for i in range(0, len(items), 2):
        row = []
        for key, val in items[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"wsvc_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="start_works")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_service_categories():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Сервис и ремонт техники", callback_data="scat_repair")],
        [InlineKeyboardButton(text="🚛 Выездные услуги",         callback_data="scat_special")],
        [InlineKeyboardButton(text="⬅️ Главное меню",           callback_data="back_main")],
    ])

def kb_service_services(category: str):
    services = SERVICE_SERVICES.get(category, {})
    rows = []
    items = list(services.items())
    for i in range(0, len(items), 2):
        row = []
        for key, val in items[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"ssvc_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="start_service")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_urgency():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стандарт (2-3 дня)",       callback_data="urg_standard")],
        [InlineKeyboardButton(text="Срочно (24 часа) +30%",    callback_data="urg_urgent")],
        [InlineKeyboardButton(text="Экстренно (сегодня) +60%", callback_data="urg_express")],
        [InlineKeyboardButton(text="⬅️ Назад",                 callback_data="start_service")],
    ])

def kb_payment(sec: str = "r"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Наличные",       callback_data=f"pay_{sec}_cash")],
        [InlineKeyboardButton(text="🏦 Безнал с НДС",   callback_data=f"pay_{sec}_bank_nds")],
        [InlineKeyboardButton(text="🏦 Безнал без НДС", callback_data=f"pay_{sec}_bank_nonds")],
    ])

def kb_address():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
            [KeyboardButton(text="✏️ Ввести адрес текстом")],
        ],
        resize_keyboard=True, one_time_keyboard=True
    )

def kb_phone():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

def kb_skip(sec: str = "r"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data=f"skipc_{sec}")]
    ])

def kb_confirm(sec: str = "r"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить заявку", callback_data=f"cfyes_{sec}")],
        [InlineKeyboardButton(text="✏️ Изменить",         callback_data=f"cfno_{sec}")],
    ])

def kb_rating(order_id: int = 0):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rev_{order_id}_1"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rev_{order_id}_2"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rev_{order_id}_3"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rev_{order_id}_4"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rev_{order_id}_5"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data=f"rev_{order_id}_skip")]
    ])


def kb_fuel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100 литров",  callback_data="fuel_100"),
         InlineKeyboardButton(text="150 литров",  callback_data="fuel_150")],
        [InlineKeyboardButton(text="200 литров",  callback_data="fuel_200"),
         InlineKeyboardButton(text="250 литров",  callback_data="fuel_250")],
        [InlineKeyboardButton(text="300 литров",  callback_data="fuel_300"),
         InlineKeyboardButton(text="400 литров",  callback_data="fuel_400")],
        [InlineKeyboardButton(text="500 литров",  callback_data="fuel_500")],
        [InlineKeyboardButton(text="Другой объём — уточним", callback_data="fuel_own")],
        [InlineKeyboardButton(text="⬅️ Назад",   callback_data="start_service")],
    ])

def kb_review_comment():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="rev_comment_skip")]
    ])

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def get_payment_name(key: str) -> str:
    return PAYMENT.get(key, {}).get("name", "-")

def rental_summary(data: dict) -> str:
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
        f"Оплата:      {get_payment_name(data.get('payment',''))}\n"
        f"Адрес:       {data.get('location','-')}\n"
        f"Телефон:     {data.get('phone','-')}\n"
        f"Комментарий: {data.get('comment','нет')}"
    )

def works_summary(data: dict) -> str:
    cat_key = data.get("works_category", "")
    svc_key = data.get("works_service", "")
    cat     = WORKS_CATEGORIES.get(cat_key, {})
    svc     = WORKS_SERVICES.get(cat_key, {}).get(svc_key, {})
    return (
        "Заявка на работы:\n\n"
        f"Раздел:      {cat.get('name','-')}\n"
        f"Услуга:      {svc.get('name','-')}\n"
        f"Стоимость:   {svc.get('price','-')}\n"
        f"Оплата:      {get_payment_name(data.get('payment',''))}\n"
        f"Адрес:       {data.get('location','-')}\n"
        f"Телефон:     {data.get('phone','-')}\n"
        f"Комментарий: {data.get('comment','нет')}"
    )

def service_summary(data: dict) -> str:
    cat_key = data.get("service_category", "")
    svc_key = data.get("service_key", "")
    svc     = SERVICE_SERVICES.get(cat_key, {}).get(svc_key, {})
    urg     = SERVICE_URGENCY.get(data.get("urgency", "standard"), {})
    lines   = [
        "Заявка на сервис:\n",
        f"Услуга:      {svc.get('name','-')}",
        f"Срочность:   {urg.get('name','-')}",
        f"Стоимость:   {svc.get('price','-')} ({urg.get('mult','')})",
        f"Срок:        {svc.get('days','-')}",
    ]
    if data.get("fuel_volume"):
        lines.append(f"Объём топлива: {data['fuel_volume']}")
    elif data.get("tech"):
        lines.append(f"Техника:     {data['tech']}")
    lines += [
        f"Оплата:      {get_payment_name(data.get('payment',''))}",
        f"Адрес:       {data.get('location','-')}",
        f"Телефон:     {data.get('phone','-')}",
        f"Комментарий: {data.get('comment','нет')}",
    ]
    return "\n".join(lines)

async def notify_owner(section: str, summary: str, user, order_id: int, data: dict = None):
    labels = {"rental": "АРЕНДА", "works": "РАБОТЫ", "service": "СЕРВИС"}
    label  = labels.get(section, section.upper())
    tag    = f"@{user.username}" if user.username else f"ID: {user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ В работу",         callback_data=f"ss_{order_id}_{user.id}_inwork")],
        [InlineKeyboardButton(text="✅ Выполнено",         callback_data=f"ss_{order_id}_{user.id}_done")],
        [InlineKeyboardButton(text="💬 Написать клиенту", callback_data=f"msg_{order_id}_{user.id}")],
        [InlineKeyboardButton(text="❌ Отменить",          callback_data=f"ss_{order_id}_{user.id}_cancel")],
    ])
    await bot.send_message(
        OWNER_ID,
        f"НОВАЯ ЗАЯВКА #{order_id} — {label}\n"
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"Клиент: {user.full_name} ({tag})\n\n{summary}",
        reply_markup=kb
    )
    if data and data.get("lat") and data.get("lon"):
        await bot.send_location(OWNER_ID, latitude=data["lat"], longitude=data["lon"])

# ─── ОБЩИЙ СБОР ДАННЫХ (адрес, телефон, оплата, комментарий) ─────────────────
async def ask_location(target, state: FSMContext):
    if hasattr(target, "message"):
        await target.message.answer("Укажите адрес объекта:", reply_markup=kb_address())
    else:
        await target.answer("Укажите адрес объекта:", reply_markup=kb_address())

async def handle_location_input(message: Message, state: FSMContext):
    """Возвращает True если локация обработана, False если нужно ждать текст"""
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        await state.update_data(
            location=f"Геолокация: {lat:.5f}, {lon:.5f}",
            lat=lat, lon=lon
        )
        await message.answer("Геолокация получена. Укажите номер телефона:", reply_markup=ReplyKeyboardRemove())
        await message.answer("👇", reply_markup=kb_phone())
        return True
    if message.text == "✏️ Ввести адрес текстом":
        await message.answer("Введите адрес объекта:", reply_markup=ReplyKeyboardRemove())
        return False
    await state.update_data(location=message.text)
    await message.answer("Адрес принят. Укажите номер телефона:", reply_markup=ReplyKeyboardRemove())
    await message.answer("👇", reply_markup=kb_phone())
    return True

async def handle_phone_input(message: Message, state: FSMContext, phone: str, sec: str = "r"):
    await state.update_data(phone=phone)
    await message.answer("Выберите форму оплаты:", reply_markup=ReplyKeyboardRemove())
    await message.answer("👇", reply_markup=kb_payment(sec))

async def handle_confirm(cb: CallbackQuery, state: FSMContext, section: str, summary_fn):
    data     = await state.get_data()
    summary  = summary_fn(data)
    order_id = db_add_order(cb.from_user.id, section, data.get("order_type", section), summary)
    await notify_owner(section, summary, cb.from_user, order_id, data)
    await state.clear()
    await cb.message.answer(
        f"Заявка #{order_id} принята!\n\n"
        f"Свяжемся в течение 15 минут.\n\n"
        f"Спасибо, что выбрали VTehnike 24!",
        reply_markup=kb_main()
    )

# ─── СТАРТ ────────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db_track_user(message.from_user)
    name = message.from_user.first_name or "Добро пожаловать"
    off  = ""
    if not is_working_hours():
        off = "\n\nРаботаем Пн-Сб 8:00-20:00. Заявку можно оставить сейчас — ответим утром первым делом.\nЭкстренный выезд: " + PHONE
    await message.answer(
        f"Привет, {name}! Добро пожаловать в VTehnike 24!\n\n"
        f"Аренда спецтехники, демонтаж, земляные работы, благоустройство и сервис — "
        f"работаем по всей Московской области.{off}\n\n"
        f"Чем могу помочь?",
        reply_markup=kb_main()
    )

# ─── ГЛАВНОЕ МЕНЮ ─────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Главное меню:", reply_markup=kb_main())

@dp.callback_query(F.data == "call_us")
async def call_us(cb: CallbackQuery):
    await cb.message.answer(
        f"Позвоните нам:\n\n{PHONE}\n\nПн-Сб 8:00-20:00\nЭкстренные выезды — круглосуточно",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="start_rental")],
            [InlineKeyboardButton(text="Главное меню",    callback_data="back_main")],
        ])
    )

@dp.callback_query(F.data == "callback_request")
async def callback_request(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(order_type="callback")
    await cb.message.answer("Оставьте номер — перезвоним в течение 15 минут:", reply_markup=kb_phone())

@dp.callback_query(F.data == "my_orders")
async def my_orders(cb: CallbackQuery):
    rows = db_get_client_orders(cb.from_user.id)
    if not rows:
        await cb.message.answer(
            "У вас пока нет заявок.\n\nОставьте первую — ответим в течение 15 минут!",
            reply_markup=kb_main()
        )
        return
    emoji_map = {"принята": "🆕", "в работе": "🔧", "выполнено": "✅", "отменена": "❌"}
    section_map = {"rental": "Аренда", "works": "Работы", "service": "Сервис", "callback": "Звонок"}
    text = "Ваши заявки:\n\n"
    for row in rows:
        order_id, section, order_type, status, created_at = row
        emoji  = emoji_map.get(status, "📋")
        label  = section_map.get(section, section)
        text  += f"{emoji} #{order_id} — {label}\n   Статус: {status}\n   Дата: {created_at}\n\n"
    await cb.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_main")]
    ]))
    await cb.answer()

# ─── АРЕНДА ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "start_rental")
async def start_rental(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(section="rental", order_type="rental")
    await state.set_state(Rental.choosing_tech)
    await cb.message.answer("Выберите технику для аренды:", reply_markup=kb_rental_tech())

@dp.callback_query(F.data.startswith("rnt_"), Rental.choosing_tech)
async def choose_rental_tech(cb: CallbackQuery, state: FSMContext):
    key  = cb.data.replace("rnt_", "")
    tech = RENTAL_TECH[key]
    await state.update_data(rental_tech=key)
    await state.set_state(Rental.choosing_worktype)
    await cb.message.answer(
        f"Выбрано: {tech['name']}\n"
        f"Цена: {fmt(tech['price_hour'], True)}/час — {fmt(tech['price_day'], True)}/смена\n\n"
        "Выберите вид работ:",
        reply_markup=kb_rental_worktype(key)
    )

@dp.callback_query(F.data.startswith("rwt_"), Rental.choosing_worktype)
async def choose_rental_worktype(cb: CallbackQuery, state: FSMContext):
    parts    = cb.data.split("_")
    idx      = int(parts[-1])
    tech_key = "_".join(parts[1:-1])
    works    = RENTAL_WORK_TYPES.get(tech_key, ["Другое"])
    work     = works[idx] if idx < len(works) else "Другое"
    await state.update_data(work_type=work)
    await state.set_state(Rental.choosing_shifts)
    await cb.message.answer(
        f"Вид работ: {work}\n\nСколько смен нужно?\n(1 смена = 1 рабочий день = 8 часов)",
        reply_markup=kb_shifts()
    )

@dp.callback_query(F.data.startswith("shf_"), Rental.choosing_shifts)
async def choose_shifts(cb: CallbackQuery, state: FSMContext):
    key   = cb.data.replace("shf_", "")
    shift = SHIFTS[key]
    data  = await state.get_data()
    tech  = RENTAL_TECH.get(data.get("rental_tech", ""), {})
    await state.update_data(shifts=key)
    await state.set_state(Rental.entering_location)
    count = shift.get("count", 0)
    price = f"Итого: от {fmt(tech.get('price_day',0) * count)}" if count > 0 else f"{fmt(tech.get('price_hour',0), True)}/час"
    await cb.message.answer(f"Смены: {shift['name']}\n{price}\n\nУкажите адрес объекта:", reply_markup=kb_address())

@dp.message(Rental.entering_location)
async def rental_location(message: Message, state: FSMContext):
    done = await handle_location_input(message, state)
    if done:
        await state.set_state(Rental.entering_phone)

@dp.message(Rental.entering_phone, F.contact)
async def rental_phone_contact(message: Message, state: FSMContext):
    await handle_phone_input(message, state, message.contact.phone_number)
    await state.set_state(Rental.choosing_payment)

@dp.message(Rental.entering_phone)
async def rental_phone_text(message: Message, state: FSMContext):
    await handle_phone_input(message, state, message.text)
    await state.set_state(Rental.choosing_payment)

@dp.callback_query(F.data.startswith("pay_r_"), Rental.choosing_payment)
async def rental_payment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(payment=cb.data.replace("pay_r_", ""))
    await state.set_state(Rental.entering_comment)
    await cb.message.answer("Добавьте комментарий или нажмите Пропустить:", reply_markup=kb_skip("r"))

@dp.callback_query(F.data == "skipc_r", Rental.entering_comment)
async def rental_skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Rental.confirm)
    await cb.message.answer(rental_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm("r"))

@dp.message(Rental.entering_comment)
async def rental_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Rental.confirm)
    await message.answer(rental_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm("r"))

@dp.callback_query(F.data == "cfyes_r", Rental.confirm)
async def rental_confirm(cb: CallbackQuery, state: FSMContext):
    await handle_confirm(cb, state, "rental", rental_summary)

@dp.callback_query(F.data == "cfno_r", Rental.confirm)
async def rental_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Начнём заново:", reply_markup=kb_main())

# ─── ДЕМОНТАЖ, ЗЕМЛЯНЫЕ РАБОТЫ И БЛАГОУСТРОЙСТВО ─────────────────────────────
@dp.callback_query(F.data == "start_works")
async def start_works(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(section="works", order_type="works")
    await state.set_state(Works.choosing_category)
    await cb.message.answer("Выберите раздел:", reply_markup=kb_works_categories())

@dp.callback_query(F.data.startswith("wcat_"), Works.choosing_category)
async def choose_works_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.replace("wcat_", "")
    await state.update_data(works_category=cat)
    await state.set_state(Works.choosing_service)
    cat_name = WORKS_CATEGORIES.get(cat, {}).get("name", "")
    await cb.message.answer(f"{cat_name} — выберите услугу:", reply_markup=kb_works_services(cat))

@dp.callback_query(F.data.startswith("wsvc_"), Works.choosing_service)
async def choose_works_service(cb: CallbackQuery, state: FSMContext):
    svc_key  = cb.data.replace("wsvc_", "")
    data     = await state.get_data()
    cat_key  = data.get("works_category", "")
    svc      = WORKS_SERVICES.get(cat_key, {}).get(svc_key, {})
    await state.update_data(works_service=svc_key)
    await state.set_state(Works.entering_location)
    await cb.message.answer(
        f"Выбрано: {svc.get('name','-')}\nСтоимость: {svc.get('price','-')}\n\nУкажите адрес объекта:",
        reply_markup=kb_address()
    )

@dp.message(Works.entering_location)
async def works_location(message: Message, state: FSMContext):
    done = await handle_location_input(message, state)
    if done:
        await state.set_state(Works.entering_phone)

@dp.message(Works.entering_phone, F.contact)
async def works_phone_contact(message: Message, state: FSMContext):
    await handle_phone_input(message, state, message.contact.phone_number, "w")
    await state.set_state(Works.choosing_payment)

@dp.message(Works.entering_phone)
async def works_phone_text(message: Message, state: FSMContext):
    await handle_phone_input(message, state, message.text, "w")
    await state.set_state(Works.choosing_payment)

@dp.callback_query(F.data.startswith("pay_w_"), Works.choosing_payment)
async def works_payment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(payment=cb.data.replace("pay_w_", ""))
    await state.set_state(Works.entering_comment)
    await cb.message.answer("Добавьте комментарий или нажмите Пропустить:", reply_markup=kb_skip("w"))

@dp.callback_query(F.data == "skipc_w", Works.entering_comment)
async def works_skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Works.confirm)
    await cb.message.answer(works_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm("w"))

@dp.message(Works.entering_comment)
async def works_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Works.confirm)
    await message.answer(works_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm("w"))

@dp.callback_query(F.data == "cfyes_w", Works.confirm)
async def works_confirm(cb: CallbackQuery, state: FSMContext):
    await handle_confirm(cb, state, "works", works_summary)

@dp.callback_query(F.data == "cfno_w", Works.confirm)
async def works_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Начнём заново:", reply_markup=kb_main())

# ─── СЕРВИС И РЕМОНТ ──────────────────────────────────────────────────────────
@dp.callback_query(F.data == "start_service")
async def start_service(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(section="service", order_type="service")
    await state.set_state(Service.choosing_category)
    await cb.message.answer("VTehnike 24 Service\n\nВыберите раздел:", reply_markup=kb_service_categories())

@dp.callback_query(F.data.startswith("scat_"), Service.choosing_category)
async def choose_service_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.replace("scat_", "")
    await state.update_data(service_category=cat)
    await state.set_state(Service.choosing_service)
    cat_name = SERVICE_CATEGORIES.get(cat, {}).get("name", "")
    await cb.message.answer(f"{cat_name} — выберите услугу:", reply_markup=kb_service_services(cat))

@dp.callback_query(F.data.startswith("ssvc_"), Service.choosing_service)
async def choose_service_service(cb: CallbackQuery, state: FSMContext):
    svc_key = cb.data.replace("ssvc_", "")
    data    = await state.get_data()
    cat_key = data.get("service_category", "")
    svc     = SERVICE_SERVICES.get(cat_key, {}).get(svc_key, {})
    await state.update_data(service_key=svc_key)
    await state.set_state(Service.choosing_urgency)
    await cb.message.answer(
        f"Выбрано: {svc.get('name','-')}\n"
        f"Стоимость: {svc.get('price','-')} — {svc.get('days','-')}\n\n"
        "Выберите срочность:",
        reply_markup=kb_urgency()
    )

@dp.callback_query(F.data.startswith("urg_"), Service.choosing_urgency)
async def choose_service_urgency(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("urg_", "")
    await state.update_data(urgency=key)
    data = await state.get_data()
    # Если заправка топливом — спрашиваем объём
    if data.get("service_key") == "fuel":
        await state.set_state(Service.choosing_fuel)
        await cb.message.answer(
            f"Срочность: {SERVICE_URGENCY[key]['name']}\n\nВыберите объём топлива:",
            reply_markup=kb_fuel()
        )
        return
    await state.set_state(Service.entering_tech)
    await cb.message.answer(
        f"Срочность: {SERVICE_URGENCY[key]['name']}\n\n"
        "Укажите тип и марку техники:\nНапример: Экскаватор Komatsu PC200\n\n"
        "(или напишите «нет» если неизвестно)"
    )


@dp.callback_query(F.data.startswith("fuel_"), Service.choosing_fuel)
async def choose_fuel_volume(cb: CallbackQuery, state: FSMContext):
    code = cb.data.replace("fuel_", "")
    volume = "уточним по телефону" if code == "own" else f"{code} литров"
    await state.update_data(fuel_volume=volume, tech=f"Объём: {volume}")
    await state.set_state(Service.entering_location)
    await cb.message.answer(
        f"Объём топлива: {volume}\n\nУкажите адрес объекта:",
        reply_markup=kb_address()
    )
    await cb.answer()

@dp.message(Service.entering_tech)
async def service_enter_tech(message: Message, state: FSMContext):
    await state.update_data(tech=message.text)
    await state.set_state(Service.entering_location)
    await message.answer("Укажите адрес объекта:", reply_markup=kb_address())

@dp.message(Service.entering_location)
async def service_location(message: Message, state: FSMContext):
    done = await handle_location_input(message, state)
    if done:
        await state.set_state(Service.entering_phone)

@dp.message(Service.entering_phone, F.contact)
async def service_phone_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("order_type") == "callback":
        await _handle_callback(message, message.contact.phone_number, state)
        return
    await handle_phone_input(message, state, message.contact.phone_number, "s")
    await state.set_state(Service.choosing_payment)

@dp.message(Service.entering_phone)
async def service_phone_text(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("order_type") == "callback":
        await _handle_callback(message, message.text, state)
        return
    await handle_phone_input(message, state, message.text, "s")
    await state.set_state(Service.choosing_payment)

@dp.callback_query(F.data.startswith("pay_s_"), Service.choosing_payment)
async def service_payment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(payment=cb.data.replace("pay_s_", ""))
    await state.set_state(Service.entering_comment)
    await cb.message.answer("Добавьте комментарий или нажмите Пропустить:", reply_markup=kb_skip("s"))

@dp.callback_query(F.data == "skipc_s", Service.entering_comment)
async def service_skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Service.confirm)
    await cb.message.answer(service_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm("s"))

@dp.message(Service.entering_comment)
async def service_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Service.confirm)
    await message.answer(service_summary(data) + "\n\nВсё верно?", reply_markup=kb_confirm("s"))

@dp.callback_query(F.data == "cfyes_s", Service.confirm)
async def service_confirm(cb: CallbackQuery, state: FSMContext):
    await handle_confirm(cb, state, "service", service_summary)

@dp.callback_query(F.data == "cfno_s", Service.confirm)
async def service_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Начнём заново:", reply_markup=kb_main())

# ─── ПЕРЕЗВОНИТЕ МНЕ ──────────────────────────────────────────────────────────
async def _handle_callback(message: Message, phone: str, state: FSMContext):
    user = message.from_user
    db_track_user(user)
    await state.clear()
    tag = f"@{user.username}" if user.username else f"ID: {user.id}"
    await bot.send_message(
        OWNER_ID,
        f"ПЕРЕЗВОНИТЬ!\n\n"
        f"Клиент: {user.full_name} ({tag})\n"
        f"Телефон: {phone}\n"
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать клиенту", callback_data=f"msg_0_{user.id}")]
        ])
    )
    await message.answer("Перезвоним в течение 15 минут!", reply_markup=ReplyKeyboardRemove())
    await message.answer("Главное меню:", reply_markup=kb_main())

# Обработчик телефона для callback_request (без FSM секции)
@dp.message(F.contact)
async def global_phone_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("order_type") == "callback":
        await _handle_callback(message, message.contact.phone_number, state)

# ─── КОМАНДЫ ВЛАДЕЛЬЦА ────────────────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer(db_get_stats())

@dp.message(Command("week"))
async def cmd_week(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer(db_get_weekly_stats())

@dp.message(Command("orders"))
async def cmd_orders(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    rows = db_get_active_orders()
    if not rows:
        await message.answer("Нет активных заявок.")
        return
    section_map = {"rental": "АРЕНДА", "works": "РАБОТЫ", "service": "СЕРВИС"}
    emoji_map   = {"принята": "🆕", "в работе": "🔧"}
    for row in rows:
        order_id, user_id, section, order_type, status, created_at, name, username = row
        label = section_map.get(section, section.upper())
        tag   = f"@{username}" if username else f"ID {user_id}"
        emoji = emoji_map.get(status, "📋")
        await message.answer(
            f"{emoji} Заявка #{order_id} — {label}\n"
            f"Клиент: {name} ({tag})\n"
            f"Статус: {status}\n"
            f"Создана: {created_at}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ В работу",         callback_data=f"ss_{order_id}_{user_id}_inwork")],
                [InlineKeyboardButton(text="✅ Выполнено",         callback_data=f"ss_{order_id}_{user_id}_done")],
                [InlineKeyboardButton(text="💬 Написать клиенту", callback_data=f"msg_{order_id}_{user_id}")],
                [InlineKeyboardButton(text="❌ Отменить",          callback_data=f"ss_{order_id}_{user_id}_cancel")],
            ])
        )

@dp.message(Command("status"))
async def cmd_set_status(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /status [номер] [статус]\nСтатусы: принята, в работе, выполнено, отменена")
        return
    try:
        order_id = int(parts[1])
    except ValueError:
        await message.answer("Номер заявки должен быть числом")
        return
    status = parts[2].strip().lower()
    if status not in ORDER_STATUSES:
        await message.answer(f"Статусы: {', '.join(ORDER_STATUSES.keys())}")
        return
    await _apply_status(message, order_id, status)

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /broadcast Текст сообщения")
        return
    user_ids = db_get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, parts[1])
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"Рассылка завершена.\nОтправлено: {sent}\nНе доставлено: {failed}")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if message.from_user.id == OWNER_ID:
        await message.answer(
            "Команды владельца:\n\n"
            "/orders — активные заявки\n"
            "/stats — статистика\n"
            "/week — сводка за 7 дней\n"
            "/status [№] [статус] — сменить статус\n"
            "/broadcast [текст] — рассылка всем\n\n"
            "Статусы: принята, в работе, выполнено, отменена"
        )
    else:
        await message.answer("/start — главное меню\n/contacts — контакты", reply_markup=kb_main())

@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await message.answer(
        f"VTehnike 24\n\nТелефон: {PHONE}\nСайт: www.vtehnike24.ru\n"
        "МО — выезжаем на любой объект\n\nПн-Сб 8:00-20:00\nЭкстренные выезды — круглосуточно"
    )

# ─── СТАТУСЫ ──────────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("ss_"))
async def cb_set_status(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        return
    parts    = cb.data.split("_")
    order_id = int(parts[1])
    user_id  = int(parts[2])
    code     = parts[3]
    status   = {"inwork": "в работе", "done": "выполнено", "cancel": "отменена"}.get(code, code)
    await _apply_status(cb.message, order_id, status, user_id=user_id)
    await cb.answer(f"Статус: {status}")

async def _apply_status(msg, order_id: int, status: str, user_id: int = None):
    order = db_get_order(order_id)
    if not order:
        await msg.answer(f"Заявка #{order_id} не найдена")
        return
    db_update_status(order_id, status)
    client_id   = user_id or order[1]
    status_text = ORDER_STATUSES.get(status, status)
    try:
        await bot.send_message(
            client_id,
            f"Заявка #{order_id}\n\nСтатус: {status_text}\n\nВопросы? Звоните: {PHONE}"
        )
        if status == "выполнено":
            await bot.send_message(client_id, "Оцените нашу работу:", reply_markup=kb_rating(order_id))
    except Exception:
        pass
    await msg.answer(f"Статус заявки #{order_id} → «{status}», клиент уведомлён.")

# ─── НАПИСАТЬ КЛИЕНТУ ─────────────────────────────────────────────────────────
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
        f"Введите сообщение для клиента по заявке #{order_id}:",
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
            f"Сообщение от VTehnike 24 по заявке #{order_id}:\n\n{message.text}\n\nЗвоните: {PHONE}"
        )
        await message.answer(f"Сообщение отправлено клиенту по заявке #{order_id}.")
    except Exception:
        await message.answer("Не удалось отправить — клиент заблокировал бота.")

# ─── ОТЗЫВЫ ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("rev_"))
async def handle_review(cb: CallbackQuery, state: FSMContext):
    parts    = cb.data.split("_")
    order_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    action   = parts[2] if len(parts) > 2 else "skip"
    if action == "skip":
        await cb.message.answer("Спасибо! Будем рады видеть вас снова.", reply_markup=kb_main())
        await cb.answer()
        return
    if action.isdigit():
        rating = int(action)
        await state.update_data(review_rating=rating, review_order_id=order_id)
        await state.set_state(Review.waiting_comment)
        await cb.message.answer(
            f"Спасибо за оценку {'⭐' * rating}!\n\nОставьте комментарий или нажмите Пропустить:",
            reply_markup=kb_review_comment()
        )
    await cb.answer()

@dp.callback_query(F.data == "rev_comment_skip", Review.waiting_comment)
async def review_comment_skip(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db_add_review(cb.from_user.id, data.get("review_order_id", 0), data.get("review_rating", 5), "")
    await state.clear()
    await cb.message.answer("Спасибо за отзыв!", reply_markup=kb_main())
    await bot.send_message(
        OWNER_ID,
        f"Отзыв от {cb.from_user.full_name}:\n"
        f"Оценка: {'⭐' * data.get('review_rating', 5)}\nЗаявка #{data.get('review_order_id','?')}"
    )
    await cb.answer()

@dp.message(Review.waiting_comment)
async def review_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    db_add_review(message.from_user.id, data.get("review_order_id", 0), data.get("review_rating", 5), message.text)
    await state.clear()
    await message.answer("Спасибо за отзыв!", reply_markup=kb_main())
    await bot.send_message(
        OWNER_ID,
        f"Отзыв от {message.from_user.full_name}:\n"
        f"Оценка: {'⭐' * data.get('review_rating', 5)}\n"
        f"Комментарий: {message.text}\nЗаявка #{data.get('review_order_id','?')}"
    )

# ─── ФОТО ─────────────────────────────────────────────────────────────────────
@dp.message(F.photo)
async def handle_photo(message: Message):
    await bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
    with db_connect() as con:
        row = con.execute(
            "SELECT id FROM orders WHERE user_id=? AND status NOT IN ('выполнено','отменена') ORDER BY created_at DESC LIMIT 1",
            (message.from_user.id,)
        ).fetchone()
    if row:
        await bot.send_message(OWNER_ID, f"Фото от {message.from_user.full_name} к заявке #{row[0]}")
        await message.answer(
            f"Фото прикреплено к заявке #{row[0]}. Свяжемся в ближайшее время.",
            reply_markup=kb_back_main()
        )
    else:
        await bot.send_message(OWNER_ID, f"Фото от {message.from_user.full_name} (без заявки)")
        await message.answer("Фото получено! Свяжемся в течение 15 минут.", reply_markup=kb_back_main())

# ─── FALLBACK ─────────────────────────────────────────────────────────────────
@dp.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        return
    await message.answer("Воспользуйтесь меню:", reply_markup=kb_main())

# ─── ФОНОВЫЕ ЗАДАЧИ ───────────────────────────────────────────────────────────
async def reminder_task():
    await asyncio.sleep(60)
    while True:
        try:
            pending = db_get_pending_orders(minutes=120)
            for order in pending:
                section_map = {"rental": "АРЕНДА", "works": "РАБОТЫ", "service": "СЕРВИС"}
                label = section_map.get(order["section"], order["section"].upper())
                await bot.send_message(
                    OWNER_ID,
                    f"НАПОМИНАНИЕ\n\nЗаявка #{order['id']} ({label}) без ответа 2 часа!\nСоздана: {order['created_at']}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="▶️ В работу", callback_data=f"ss_{order['id']}_{order['user_id']}_inwork")],
                        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"ss_{order['id']}_{order['user_id']}_cancel")],
                    ])
                )
        except Exception as e:
            logging.error(f"Reminder error: {e}")
        await asyncio.sleep(30 * 60)

async def weekly_report_task():
    while True:
        now         = datetime.now()
        days_ahead  = (7 - now.weekday()) % 7 or 7
        next_monday = now.replace(hour=9, minute=0, second=0, microsecond=0)
        next_monday = next_monday.replace(day=now.day + days_ahead)
        wait        = (next_monday - now).total_seconds()
        if wait < 0:
            wait += 7 * 24 * 3600
        await asyncio.sleep(wait)
        try:
            await bot.send_message(OWNER_ID, db_get_weekly_stats())
        except Exception as e:
            logging.error(f"Weekly report error: {e}")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
async def main():
    db_init()
    print("VTehnike 24 Bot v12.0 запущен!")
    asyncio.create_task(reminder_task())
    asyncio.create_task(weekly_report_task())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
