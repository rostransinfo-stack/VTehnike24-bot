"""
VTehnike 24 — Telegram Bot v5.0
- Виды работ для каждой техники свои, выбор кнопками
- 1 смена = 1 рабочий день = 8 часов
- Форма оплаты
- История переписки сохраняется
"""

import asyncio
import json
import logging
from datetime import datetime
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
OWNER_ID   = "125380747"      # Ваш Telegram ID от @userinfobot
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ─── УЧЁТ ПОЛЬЗОВАТЕЛЕЙ ───────────────────────────────────────────────────────
USERS_FILE = "users.json"

def load_users() -> dict:
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def track_user(user, order_type: str = None):
    """Записать пользователя. order_type = 'repair' | 'rental' | None (просто зашёл)"""
    users = load_users()
    uid   = str(user.id)
    now   = datetime.now().strftime("%d.%m.%Y %H:%M")

    if uid not in users:
        users[uid] = {
            "id":         user.id,
            "name":       user.full_name,
            "username":   user.username or "",
            "first_seen": now,
            "last_seen":  now,
            "visits":     1,
            "orders":     [],
        }
    else:
        users[uid]["last_seen"] = now
        users[uid]["visits"]   += 1
        users[uid]["name"]      = user.full_name  # обновляем имя

    if order_type:
        users[uid]["orders"].append({"type": order_type, "date": now})

    save_users(users)

def get_stats() -> str:
    users = load_users()
    if not users:
        return "Пока никто не заходил в бот."

    total        = len(users)
    with_orders  = sum(1 for u in users.values() if u.get("orders"))
    total_orders = sum(len(u.get("orders", [])) for u in users.values())
    repair_count = sum(
        sum(1 for o in u.get("orders", []) if o["type"] == "repair")
        for u in users.values()
    )
    rental_count = sum(
        sum(1 for o in u.get("orders", []) if o["type"] == "rental")
        for u in users.values()
    )

    # последние 5 пользователей
    sorted_users = sorted(users.values(), key=lambda u: u["last_seen"], reverse=True)
    recent = ""
    for u in sorted_users[:5]:
        orders_count = len(u.get("orders", []))
        tag = f"@{u['username']}" if u.get("username") else f"ID {u['id']}"
        recent += f"  {u['name']} ({tag}) — {orders_count} заявок, был {u['last_seen']}\n"

    return (
        f"Статистика бота VTehnike 24\n\n"
        f"Всего пользователей:  {total}\n"
        f"Оставили заявку:      {with_orders}\n"
        f"Всего заявок:         {total_orders}\n"
        f"  из них ремонт:      {repair_count}\n"
        f"  из них аренда:      {rental_count}\n\n"
        f"Последние 5 активных:\n{recent}"
    )

# ─── УСЛУГИ РЕМОНТА ───────────────────────────────────────────────────────────
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

# ─── ТЕХНИКА ДЛЯ АРЕНДЫ ───────────────────────────────────────────────────────
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

# ─── ВИДЫ РАБОТ ПО ТЕХНИКЕ ────────────────────────────────────────────────────
WORK_TYPES = {
    "exc_mini": [
        "Разработка котлована",
        "Рытьё траншей",
        "Планировка участка",
        "Демонтажные работы",
        "Благоустройство",
        "Другое",
    ],
    "exc_mid": [
        "Разработка котлована",
        "Рытьё траншей",
        "Вскрышные работы",
        "Погрузка грунта",
        "Демонтаж строений",
        "Другое",
    ],
    "exc_heavy": [
        "Разработка глубокого котлована",
        "Вскрышные работы",
        "Погрузка скальника / тяжёлого грунта",
        "Демонтаж капитальных строений",
        "Дорожные работы",
        "Другое",
    ],
    "exc_loader": [
        "Рытьё траншей под коммуникации",
        "Планировка и засыпка",
        "Погрузка и перемещение материалов",
        "Расчистка территории",
        "Дорожные работы",
        "Другое",
    ],
    "loader_front": [
        "Погрузка грунта / щебня / песка",
        "Расчистка снега",
        "Планировка площадки",
        "Перемещение сыпучих материалов",
        "Складские работы",
        "Другое",
    ],
    "loader_mini": [
        "Погрузка в ограниченном пространстве",
        "Расчистка снега",
        "Планировка и засыпка",
        "Ландшафтные работы",
        "Складские работы",
        "Другое",
    ],
    "bulldozer": [
        "Расчистка территории",
        "Планировка площадки",
        "Рекультивация земель",
        "Разработка грунта",
        "Дорожные работы",
        "Другое",
    ],
    "grader": [
        "Профилирование дороги",
        "Планировка площадки",
        "Разравнивание щебня / грунта",
        "Содержание грунтовых дорог",
        "Снегоуборочные работы",
        "Другое",
    ],
    "crane": [
        "Монтаж конструкций",
        "Подъём оборудования",
        "Строительно-монтажные работы",
        "Разгрузка / погрузка крупногабаритного груза",
        "Демонтаж конструкций",
        "Другое",
    ],
    "dump": [
        "Вывоз грунта",
        "Вывоз строительного мусора",
        "Доставка щебня / песка / ПГС",
        "Вывоз снега",
        "Перевозка сыпучих грузов",
        "Другое",
    ],
    "manipulator": [
        "Подъём и перемещение грузов",
        "Разгрузка стройматериалов",
        "Монтаж / демонтаж оборудования",
        "Перевозка с разгрузкой",
        "Другое",
    ],
    "compactor": [
        "Уплотнение грунта",
        "Уплотнение щебня / ПГС",
        "Устройство дорожного основания",
        "Уплотнение асфальта",
        "Другое",
    ],
}

# ─── СМЕНЫ (1 смена = 1 календарный день = 8 часов) ──────────────────────────
SHIFTS = {
    "s1":  {"name": "1 смена — 1 день",   "count": 1},
    "s2":  {"name": "2 смены — 2 дня",    "count": 2},
    "s3":  {"name": "3 смены — 3 дня",    "count": 3},
    "s5":  {"name": "5 смен — 5 дней",    "count": 5},
    "s10": {"name": "10 смен — 10 дней",  "count": 10},
    "s22": {"name": "22 смены — месяц",   "count": 22},
    "own": {"name": "Другое — уточним",   "count": 0},
}

# ─── СРОЧНОСТЬ ────────────────────────────────────────────────────────────────
URGENCY = {
    "standard": {"name": "Стандарт (2-3 дня)",       "mult": "x1"},
    "urgent":   {"name": "Срочно (24 часа) +30%",    "mult": "+30%"},
    "express":  {"name": "Экстренно (сегодня) +60%", "mult": "+60%"},
}

# ─── ФОРМА ОПЛАТЫ ─────────────────────────────────────────────────────────────
PAYMENT = {
    "cash":       {"name": "Наличные"},
    "bank_nds":   {"name": "Безнал с НДС"},
    "bank_nonds": {"name": "Безнал без НДС"},
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

# ─── ХЕЛПЕР форматирования цены ───────────────────────────────────────────────
def fmt(amount: int, prefix: bool = False) -> str:
    s = f"{amount:,}".replace(",", " ") + " руб."
    return ("от " + s) if prefix else s

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Заявка на ремонт", callback_data="start_repair")],
        [InlineKeyboardButton(text="🚜 Аренда техники",   callback_data="start_rental")],
        [InlineKeyboardButton(text="💰 Прайс-лист",       callback_data="show_prices")],
        [InlineKeyboardButton(text="📞 Позвонить нам",    callback_data="call_us")],
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
    rows = []
    for i in range(0, len(works), 2):
        row = []
        for w in works[i:i+2]:
            # используем индекс чтобы не превышать лимит callback_data
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
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ─── ИТОГОВАЯ КАРТОЧКА ────────────────────────────────────────────────────────
def order_summary(data: dict) -> str:
    order_type = data.get("order_type", "repair")
    payment    = PAYMENT.get(data.get("payment", ""), {}).get("name", "-")

    if order_type == "rental":
        tech  = RENTAL_TECH.get(data.get("rental_tech", ""), {})
        shift = SHIFTS.get(data.get("shifts", "own"), {})
        count = shift.get("count", 0)
        if count > 0:
            total      = tech.get("price_day", 0) * count
            price_line = f"{shift['name']} x {fmt(tech.get('price_day', 0), True)} = от {fmt(total)}"
        else:
            price_line = f"{fmt(tech.get('price_hour', 0), True)}/час — объём уточним"
        return (
            "Заявка на аренду:\n\n"
            f"Техника:     {tech.get('name', '-')}\n"
            f"Вид работ:   {data.get('work_type', '-')}\n"
            f"Смены:       {shift.get('name', '-')}\n"
            f"Стоимость:   {price_line}\n"
            f"Оплата:      {payment}\n"
            f"Адрес:       {data.get('location', '-')}\n"
            f"Телефон:     {data.get('phone', '-')}\n"
            f"Комментарий: {data.get('comment', 'нет')}"
        )
    else:
        svc = REPAIR_SERVICES.get(data.get("service", ""), {})
        urg = URGENCY.get(data.get("urgency", "standard"), {})
        return (
            "Заявка на ремонт:\n\n"
            f"Услуга:      {svc.get('name', '-')}\n"
            f"Срочность:   {urg.get('name', '-')}\n"
            f"Техника:     {data.get('tech', '-')}\n"
            f"Адрес:       {data.get('location', '-')}\n"
            f"Телефон:     {data.get('phone', '-')}\n"
            f"Оплата:      {payment}\n"
            f"Комментарий: {data.get('comment', 'нет')}\n\n"
            f"Стоимость:   {svc.get('price', '-')} ({urg.get('mult', '')})\n"
            f"Срок:        {svc.get('days', '-')}"
        )

async def notify_owner(data: dict, user):
    order_type = data.get("order_type", "repair")
    label = "АРЕНДА" if order_type == "rental" else "РЕМОНТ"
    header = (
        f"НОВАЯ ЗАЯВКА — {label}\n"
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Клиент: {user.full_name}"
        f"{' (@' + user.username + ')' if user.username else ''}\n"
        f"TG ID: {user.id}\n\n"
    )
    body = order_summary(data)
    body = body.replace("Заявка на аренду:\n\n", "").replace("Заявка на ремонт:\n\n", "")
    await bot.send_message(OWNER_ID, header + body)

# ─── СТАРТ ────────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    track_user(message.from_user)
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

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != OWNER_ID:
        return  # только владелец видит статистику
    await message.answer(get_stats())

# ─── ГЛАВНОЕ МЕНЮ ─────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Главное меню:", reply_markup=kb_main())

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
    await cb.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="start_repair")],
            [InlineKeyboardButton(text="Главное меню",    callback_data="back_main")],
        ])
    )

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
        f"Выбрано: {svc['name']}\n"
        f"Цена: {svc['price']} — {svc['days']}\n\n"
        "Выберите срочность:",
        reply_markup=kb_urgency()
    )

@dp.callback_query(F.data.startswith("urg_"), Order.choosing_urgency)
async def choose_urgency(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("urg_", "")
    await state.update_data(urgency=key)
    await state.set_state(Order.entering_tech)
    await cb.message.answer(
        f"Срочность: {URGENCY[key]['name']}\n\n"
        "Укажите тип и марку техники:\n"
        "Например: Экскаватор Komatsu PC200, JCB 3CX"
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
    key = cb.data.replace("rnt_", "")
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
    # формат: wrk_exc_mini_0
    parts = cb.data.split("_")
    # последний элемент — индекс, остальное после "wrk_" — ключ техники
    idx = int(parts[-1])
    tech_key = "_".join(parts[1:-1])
    works = WORK_TYPES.get(tech_key, ["Другое"])
    work_name = works[idx] if idx < len(works) else "Другое"
    await state.update_data(work_type=work_name)
    await state.set_state(Order.choosing_shifts)
    await cb.message.answer(
        f"Вид работ: {work_name}\n\n"
        "Сколько смен нужно?\n"
        "(1 смена = 1 рабочий день = 8 часов)",
        reply_markup=kb_shifts()
    )

@dp.callback_query(F.data.startswith("shf_"), Order.choosing_shifts)
async def choose_shifts(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("shf_", "")
    shift = SHIFTS[key]
    data = await state.get_data()
    tech = RENTAL_TECH.get(data.get("rental_tech", ""), {})
    await state.update_data(shifts=key)
    await state.set_state(Order.entering_location)

    count = shift.get("count", 0)
    if count > 0:
        total      = tech.get("price_day", 0) * count
        price_line = f"Итого: от {fmt(total)}"
    else:
        price_line = f"Стоимость: {fmt(tech.get('price_hour', 0), True)}/час — уточним"

    await cb.message.answer(
        f"Смены: {shift['name']}\n"
        f"{price_line}\n\n"
        "Укажите адрес объекта или район:\n"
        "Например: Подольск, ул. Ленина 5 / Красногорск"
    )

# ─── ОБЩИЙ СБОР ДАННЫХ ────────────────────────────────────────────────────────
@dp.message(Order.entering_tech)
async def enter_tech(message: Message, state: FSMContext):
    await state.update_data(tech=message.text)
    await state.set_state(Order.entering_location)
    await message.answer(
        "Укажите адрес объекта или район:\n"
        "Например: Подольск, ул. Ленина 5 / Красногорск"
    )

@dp.message(Order.entering_location)
async def enter_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text)
    await state.set_state(Order.entering_phone)
    await message.answer("Укажите номер телефона:", reply_markup=kb_phone())

@dp.message(Order.entering_phone, F.contact)
async def enter_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Order.choosing_payment)
    await message.answer("Выберите форму оплаты:", reply_markup=ReplyKeyboardRemove())
    await message.answer("👇", reply_markup=kb_payment())

@dp.message(Order.entering_phone)
async def enter_phone_text(message: Message, state: FSMContext):
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
        f"Оплата: {PAYMENT[key]['name']}\n\n"
        "Добавьте комментарий или нажмите Пропустить:",
        reply_markup=kb_skip()
    )

@dp.callback_query(F.data == "skip_comment", Order.entering_comment)
async def skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await cb.message.answer(
        order_summary(data) + "\n\nВсё верно?",
        reply_markup=kb_confirm()
    )

@dp.message(Order.entering_comment)
async def enter_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await message.answer(
        order_summary(data) + "\n\nВсё верно?",
        reply_markup=kb_confirm()
    )

# ─── ПОДТВЕРЖДЕНИЕ ────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "confirm_yes", Order.confirm)
async def confirm_order(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await notify_owner(data, cb.from_user)
    track_user(cb.from_user, order_type=data.get("order_type", "repair"))
    await state.clear()
    msg = (
        "Заявка принята!\n\n"
        "Свяжемся с вами в течение 15 минут.\n\n"
    )
    if data.get("order_type") == "repair":
        msg += "Можете прислать фото неисправности прямо в этот чат — поможет точнее назвать цену.\n\n"
    msg += "Спасибо, что выбрали VTehnike 24!"
    await cb.message.answer(msg, reply_markup=kb_main())

@dp.callback_query(F.data == "confirm_no", Order.confirm)
async def cancel_order(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Хорошо, начнём заново:", reply_markup=kb_main())

# ─── ФОТО ─────────────────────────────────────────────────────────────────────
@dp.message(F.photo)
async def handle_photo(message: Message):
    await bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
    await bot.send_message(
        OWNER_ID,
        f"Фото от: {message.from_user.full_name} (ID: {message.from_user.id})"
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
    current = await state.get_state()
    if current:
        return
    await message.answer("Воспользуйтесь меню:", reply_markup=kb_main())

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
async def main():
    print("VTehnike 24 Bot v5.0 запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
