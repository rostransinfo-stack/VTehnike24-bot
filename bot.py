"""
VTehnike 24 — Telegram Bot v2.0
Приём заявок, расчёт стоимости, уведомления владельцу
"""

import asyncio
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
BOT_TOKEN = "7151969834:AAHLEnwxwfpaaERnJaOYiiA6ctXJoxvR4C8"      # Вставить токен от @BotFather
OWNER_ID   = "125380747"        # Вставить свой Telegram ID от @userinfobot
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

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
    "exc_mini":     {"name": "Мини-экскаватор (до 6т)",           "price": "от 1 800 руб./час"},
    "exc_mid":      {"name": "Экскаватор средний (6-20т)",        "price": "от 2 500 руб./час"},
    "exc_heavy":    {"name": "Экскаватор тяжёлый (20т+)",         "price": "от 3 500 руб./час"},
    "exc_loader":   {"name": "Экскаватор-погрузчик (JCB, Case)",  "price": "от 2 200 руб./час"},
    "loader_front": {"name": "Погрузчик фронтальный",             "price": "от 2 000 руб./час"},
    "loader_mini":  {"name": "Мини-погрузчик (Bobcat)",           "price": "от 1 800 руб./час"},
    "bulldozer":    {"name": "Бульдозер",                         "price": "от 3 000 руб./час"},
    "grader":       {"name": "Автогрейдер",                       "price": "от 3 200 руб./час"},
    "crane":        {"name": "Автокран (25-50т)",                 "price": "от 3 500 руб./час"},
    "dump":         {"name": "Самосвал (10-20т)",                 "price": "от 1 500 руб./час"},
    "manipulator":  {"name": "Манипулятор",                       "price": "от 2 000 руб./час"},
    "compactor":    {"name": "Каток дорожный",                    "price": "от 2 500 руб./час"},
}

URGENCY = {
    "standard": {"name": "Стандарт (2-3 дня)",       "mult": "x1"},
    "urgent":   {"name": "Срочно (24 часа) +30%",    "mult": "+30%"},
    "express":  {"name": "Экстренно (сегодня) +60%", "mult": "+60%"},
}

# ─── СОСТОЯНИЯ ────────────────────────────────────────────────────────────────
class Order(StatesGroup):
    choosing_service  = State()
    choosing_rental   = State()
    choosing_urgency  = State()
    entering_tech     = State()
    entering_location = State()
    entering_phone    = State()
    entering_comment  = State()
    confirm           = State()

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заявка на ремонт",  callback_data="start_repair")],
        [InlineKeyboardButton(text="Аренда техники",    callback_data="start_rental")],
        [InlineKeyboardButton(text="Прайс-лист",        callback_data="show_prices")],
        [InlineKeyboardButton(text="Позвонить нам",     callback_data="call_us")],
    ])

def kb_repair_services():
    rows = []
    items = list(REPAIR_SERVICES.items())
    for i in range(0, len(items), 2):
        row = []
        for key, val in items[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"rep_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_rental_tech():
    rows = []
    items = list(RENTAL_TECH.items())
    for i in range(0, len(items), 2):
        row = []
        for key, val in items[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"rnt_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_urgency():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стандарт (2-3 дня)",        callback_data="urg_standard")],
        [InlineKeyboardButton(text="Срочно (24 часа) +30%",     callback_data="urg_urgent")],
        [InlineKeyboardButton(text="Экстренно (сегодня) +60%",  callback_data="urg_express")],
        [InlineKeyboardButton(text="Назад",                     callback_data="back_repair")],
    ])

def kb_skip():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]
    ])

def kb_confirm():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить заявку", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="Изменить",         callback_data="confirm_no")],
    ])

def kb_phone():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def order_summary(data: dict) -> str:
    order_type = data.get("order_type", "repair")
    if order_type == "rental":
        tech = RENTAL_TECH.get(data.get("rental_tech", ""), {})
        return (
            "*Ваша заявка на аренду:*\n\n"
            f"Техника: {tech.get('name', '-')}\n"
            f"Стоимость: {tech.get('price', '-')}\n"
            f"Адрес/объект: {data.get('location', '-')}\n"
            f"Телефон: {data.get('phone', '-')}\n"
            f"Комментарий: {data.get('comment', 'нет')}"
        )
    else:
        svc = REPAIR_SERVICES.get(data.get("service", ""), {})
        urg = URGENCY.get(data.get("urgency", "standard"), {})
        return (
            "*Ваша заявка на ремонт:*\n\n"
            f"Услуга: {svc.get('name', '-')}\n"
            f"Срочность: {urg.get('name', '-')}\n"
            f"Техника: {data.get('tech', '-')}\n"
            f"Адрес/объект: {data.get('location', '-')}\n"
            f"Телефон: {data.get('phone', '-')}\n"
            f"Комментарий: {data.get('comment', 'нет')}\n\n"
            f"Стоимость: {svc.get('price', '-')} ({urg.get('mult', '')})\n"
            f"Срок: {svc.get('days', '-')}"
        )

async def notify_owner(data: dict, user):
    order_type = data.get("order_type", "repair")
    if order_type == "rental":
        tech = RENTAL_TECH.get(data.get("rental_tech", ""), {})
        text = (
            f"НОВАЯ ЗАЯВКА - АРЕНДА\n"
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Клиент: {user.full_name}"
            f"{' (@' + user.username + ')' if user.username else ''}\n"
            f"TG ID: {user.id}\n\n"
            f"Техника: {tech.get('name', '-')}\n"
            f"Цена: {tech.get('price', '-')}\n"
            f"Объект: {data.get('location', '-')}\n"
            f"Телефон: {data.get('phone', '-')}\n"
            f"Комментарий: {data.get('comment', 'нет')}"
        )
    else:
        svc = REPAIR_SERVICES.get(data.get("service", ""), {})
        urg = URGENCY.get(data.get("urgency", "standard"), {})
        text = (
            f"НОВАЯ ЗАЯВКА - РЕМОНТ\n"
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Клиент: {user.full_name}"
            f"{' (@' + user.username + ')' if user.username else ''}\n"
            f"TG ID: {user.id}\n\n"
            f"Услуга: {svc.get('name', '-')}\n"
            f"Срочность: {urg.get('name', '-')}\n"
            f"Техника: {data.get('tech', '-')}\n"
            f"Объект: {data.get('location', '-')}\n"
            f"Телефон: {data.get('phone', '-')}\n"
            f"Комментарий: {data.get('comment', 'нет')}\n\n"
            f"Цена: {svc.get('price', '-')} ({urg.get('mult', '')})"
        )
    await bot.send_message(OWNER_ID, text)

# ─── СТАРТ ────────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    name = message.from_user.first_name or "Добро пожаловать"
    await message.answer(
        f"Привет, {name}! Добро пожаловать в VTehnike 24!\n\n"
        "Ремонт ковшей, восстановление спецтехники и аренда - "
        "выезжаем на объект по всей Московской области.\n\n"
        "Ремонт ковша за 24 часа\n"
        "Приедем сами - никуда везти не надо\n"
        "Цену скажем за 15 минут по фото\n\n"
        "Чем могу помочь?",
        reply_markup=kb_main()
    )

@dp.message(Command("prices"))
async def cmd_prices(message: Message):
    text = "Прайс - Ремонт спецтехники\n\n"
    for svc in REPAIR_SERVICES.values():
        text += f"{svc['name']}\n{svc['price']} - {svc['days']}\n\n"
    text += "Точная стоимость - после фото или осмотра"
    await message.answer(text)

@dp.message(Command("rental"))
async def cmd_rental_prices(message: Message):
    text = "Прайс - Аренда спецтехники\n\n"
    for t in RENTAL_TECH.values():
        text += f"{t['name']}\n{t['price']}\n\n"
    text += "С оператором - Выезд по МО - Работаем с ИП и ООО"
    await message.answer(text)

@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await message.answer(
        "Контакты VTehnike 24\n\n"
        "Телефон: +7 (___) ___-__-__\n"
        "Сайт: www.vtehnike24.ru\n"
        "МО - выезжаем на любой объект\n\n"
        "Пн-Сб 8:00-20:00\n"
        "Экстренные выезды - круглосуточно"
    )

# ─── ГЛАВНОЕ МЕНЮ ─────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Главное меню:", reply_markup=kb_main())

@dp.callback_query(F.data == "call_us")
async def call_us(cb: CallbackQuery):
    await cb.message.edit_text(
        "Позвоните нам:\n\n"
        "+7 (___) ___-__-__\n\n"
        "Пн-Сб 8:00-20:00\n"
        "Экстренные выезды - круглосуточно",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="start_repair")],
            [InlineKeyboardButton(text="Назад",           callback_data="back_main")],
        ])
    )

@dp.callback_query(F.data == "show_prices")
async def show_prices(cb: CallbackQuery):
    text = "Прайс - Ремонт спецтехники\n\n"
    for svc in REPAIR_SERVICES.values():
        text += f"{svc['name']}\n{svc['price']} - {svc['days']}\n\n"
    text += "Точная стоимость - после фото или осмотра"
    await cb.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="start_repair")],
            [InlineKeyboardButton(text="Назад",           callback_data="back_main")],
        ])
    )

# ─── РЕМОНТ ───────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "start_repair")
async def start_repair(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(order_type="repair")
    await state.set_state(Order.choosing_service)
    await cb.message.edit_text(
        "Выберите услугу:",
        reply_markup=kb_repair_services()
    )

@dp.callback_query(F.data == "back_repair")
async def back_repair(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Order.choosing_service)
    await cb.message.edit_text("Выберите услугу:", reply_markup=kb_repair_services())

@dp.callback_query(F.data.startswith("rep_"), Order.choosing_service)
async def choose_repair_service(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("rep_", "")
    svc = REPAIR_SERVICES[key]
    await state.update_data(service=key)
    await state.set_state(Order.choosing_urgency)
    await cb.message.edit_text(
        f"Выбрано: {svc['name']}\n"
        f"Цена: {svc['price']} - {svc['days']}\n\n"
        f"Выберите срочность:",
        reply_markup=kb_urgency()
    )

@dp.callback_query(F.data.startswith("urg_"), Order.choosing_urgency)
async def choose_urgency(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("urg_", "")
    await state.update_data(urgency=key)
    await state.set_state(Order.entering_tech)
    await cb.message.edit_text(
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
    await cb.message.edit_text(
        "Выберите технику для аренды:",
        reply_markup=kb_rental_tech()
    )

@dp.callback_query(F.data.startswith("rnt_"), Order.choosing_rental)
async def choose_rental_tech(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("rnt_", "")
    tech = RENTAL_TECH[key]
    await state.update_data(rental_tech=key)
    await state.set_state(Order.entering_location)
    await cb.message.edit_text(
        f"Выбрано: {tech['name']}\n"
        f"Цена: {tech['price']}\n\n"
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
    await message.answer(
        "Укажите номер телефона:",
        reply_markup=kb_phone()
    )

@dp.message(Order.entering_phone, F.contact)
async def enter_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Order.entering_comment)
    await message.answer(
        "Опишите задачу подробнее (или нажмите Пропустить):",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(".", reply_markup=kb_skip())

@dp.message(Order.entering_phone)
async def enter_phone_text(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(Order.entering_comment)
    await message.answer(
        "Опишите задачу подробнее (или нажмите Пропустить):",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(".", reply_markup=kb_skip())

@dp.callback_query(F.data == "skip_comment", Order.entering_comment)
async def skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await cb.message.edit_text(
        order_summary(data) + "\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=kb_confirm()
    )

@dp.message(Order.entering_comment)
async def enter_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await message.answer(
        order_summary(data) + "\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=kb_confirm()
    )

# ─── ПОДТВЕРЖДЕНИЕ ────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "confirm_yes", Order.confirm)
async def confirm_order(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await notify_owner(data, cb.from_user)
    await state.clear()
    await cb.message.edit_text(
        "Заявка принята!\n\n"
        "Свяжемся с вами в течение 15 минут.\n\n"
        "Можете прислать фото прямо в этот чат - "
        "это поможет точнее назвать цену.\n\n"
        "Спасибо, что выбрали VTehnike 24!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="На главную", callback_data="back_main")]
        ])
    )

@dp.callback_query(F.data == "confirm_no", Order.confirm)
async def cancel_order(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Хорошо, начнём заново:", reply_markup=kb_main())

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
            [InlineKeyboardButton(text="На главную", callback_data="back_main")]
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
    print("VTehnike 24 Bot v2.0 запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
