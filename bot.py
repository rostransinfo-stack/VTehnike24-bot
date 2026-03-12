"""
VTehnike 24 — Telegram Bot
Приём заявок, расчёт стоимости, уведомления владельцу
Требует: pip install aiogram==3.* python-dotenv
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
BOT_TOKEN = 7151969834:AAEIP36v2mCVgFGhAmX_2oeRjNLacikDX-Y
OWNER_ID   = 125380747
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ─── ПРАЙС ────────────────────────────────────────────────────────────────────
SERVICES = {
    "bucket_basic":  {"name": "Ремонт ковша (базовый)",        "price": "от 15 000 ₽",  "days": "1–2 дня"},
    "bucket_hardox": {"name": "Hardox-бронирование ковша",     "price": "от 40 000 ₽",  "days": "2–3 дня"},
    "teeth":         {"name": "Замена зубьев (комплект)",       "price": "от 12 000 ₽",  "days": "1 день"},
    "knife":         {"name": "Замена ножа",                    "price": "от 12 000 ₽",  "days": "1 день"},
    "bushing":       {"name": "Восстановление втулок",          "price": "от 5 000 ₽/шт","days": "1–2 дня"},
    "hydraulics":    {"name": "Ремонт гидравлики",              "price": "от 25 000 ₽",  "days": "2–4 дня"},
    "cylinder":      {"name": "Ремонт гидроцилиндра",           "price": "от 10 000 ₽",  "days": "1–2 дня"},
    "undercarriage": {"name": "Ходовая часть",                  "price": "от 18 000 ₽",  "days": "2–4 дня"},
    "maintenance":   {"name": "Плановое ТО",                    "price": "от 10 000 ₽",  "days": "1 день"},
    "welding":       {"name": "Сварочные работы",               "price": "от 8 000 ₽",   "days": "1–2 дня"},
    "diagnostics":   {"name": "Диагностика (выезд)",            "price": "5 000 ₽",      "days": "в день заявки"},
    "rental":        {"name": "Аренда спецтехники",             "price": "от 2 500 ₽/час","days": "по договору"},
}

URGENCY = {
    "standard": {"name": "Стандарт (2–3 дня)",     "mult": "×1"},
    "urgent":   {"name": "Срочно (24 часа) +30%",  "mult": "+30%"},
    "express":  {"name": "Экстренно (сегодня) +60%","mult": "+60%"},
}

# ─── СОСТОЯНИЯ FSM ────────────────────────────────────────────────────────────
class Order(StatesGroup):
    choosing_service  = State()
    choosing_urgency  = State()
    entering_tech     = State()
    entering_location = State()
    entering_phone    = State()
    entering_comment  = State()
    confirm           = State()

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧 Оставить заявку на ремонт", callback_data="start_order")],
        [InlineKeyboardButton(text="💰 Узнать стоимость",          callback_data="show_prices")],
        [InlineKeyboardButton(text="🚜 Аренда техники",            callback_data="rental_info")],
        [InlineKeyboardButton(text="📞 Позвонить нам",             callback_data="call_us")],
    ])

def kb_services():
    rows = []
    pairs = list(SERVICES.items())
    for i in range(0, len(pairs), 2):
        row = []
        for key, val in pairs[i:i+2]:
            row.append(InlineKeyboardButton(text=val["name"], callback_data=f"srv_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_urgency():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Стандарт (2–3 дня)",       callback_data="urg_standard")],
        [InlineKeyboardButton(text="⚡ Срочно (24 часа) +30%",    callback_data="urg_urgent")],
        [InlineKeyboardButton(text="🔥 Экстренно (сегодня) +60%", callback_data="urg_express")],
        [InlineKeyboardButton(text="⬅️ Назад",                    callback_data="back_services")],
    ])

def kb_skip():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="skip_comment")]
    ])

def kb_confirm():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить заявку",   callback_data="confirm_yes")],
        [InlineKeyboardButton(text="✏️ Изменить",          callback_data="confirm_no")],
    ])

def kb_phone(user_phone=None):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return kb

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────
def order_summary(data: dict) -> str:
    svc = SERVICES.get(data.get("service", ""), {})
    urg = URGENCY.get(data.get("urgency", "standard"), {})
    return (
        f"📋 *Ваша заявка:*\n\n"
        f"🔧 *Услуга:* {svc.get('name', '—')}\n"
        f"⏱ *Срочность:* {urg.get('name', '—')}\n"
        f"🚜 *Техника:* {data.get('tech', '—')}\n"
        f"📍 *Адрес/объект:* {data.get('location', '—')}\n"
        f"📞 *Телефон:* {data.get('phone', '—')}\n"
        f"💬 *Комментарий:* {data.get('comment', 'нет')}\n\n"
        f"💰 *Стоимость:* {svc.get('price', '—')} ({urg.get('mult', '')})\n"
        f"📅 *Срок:* {svc.get('days', '—')}"
    )

async def notify_owner(data: dict, user):
    svc = SERVICES.get(data.get("service", ""), {})
    urg = URGENCY.get(data.get("urgency", "standard"), {})
    text = (
        f"🆕 *НОВАЯ ЗАЯВКА VTehnike 24*\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"👤 Клиент: {user.full_name}"
        f"{' (@' + user.username + ')' if user.username else ''}\n"
        f"🆔 TG ID: `{user.id}`\n\n"
        f"🔧 Услуга: {svc.get('name', '—')}\n"
        f"⏱ Срочность: {urg.get('name', '—')}\n"
        f"🚜 Техника: {data.get('tech', '—')}\n"
        f"📍 Объект: {data.get('location', '—')}\n"
        f"📞 Телефон: {data.get('phone', '—')}\n"
        f"💬 Комментарий: {data.get('comment', 'нет')}\n\n"
        f"💰 Цена: {svc.get('price', '—')} ({urg.get('mult', '')})"
    )
    await bot.send_message(OWNER_ID, text, parse_mode="Markdown")

# ─── ХЭНДЛЕРЫ ─────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    name = message.from_user.first_name or "Привет"
    await message.answer(
        f"👋 *{name}, добро пожаловать в VTehnike 24!*\n\n"
        "Мы занимаемся ремонтом ковшей, восстановлением спецтехники "
        "и арендой — выезжаем на объект по всей Московской области.\n\n"
        "⚡ Ремонт ковша за 24 часа\n"
        "📍 Приедем сами — никуда везти не надо\n"
        "💰 Цену скажем за 15 минут по фото\n\n"
        "Чем могу помочь?",
        parse_mode="Markdown",
        reply_markup=kb_main()
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ *VTehnike 24 — помощь*\n\n"
        "/start — главное меню\n"
        "/prices — прайс-лист\n"
        "/order — оставить заявку\n"
        "/contacts — наши контакты",
        parse_mode="Markdown"
    )

@dp.message(Command("prices"))
async def cmd_prices(message: Message):
    text = "💰 *Прайс-лист VTehnike 24*\n\n"
    for svc in SERVICES.values():
        text += f"• {svc['name']}\n  {svc['price']} · {svc['days']}\n\n"
    text += "_Точная стоимость — после фото или осмотра_"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await message.answer(
        "📞 *Контакты VTehnike 24*\n\n"
        "📱 Телефон: +7 (___) ___-__-__\n"
        "🌐 Сайт: www.vtehnike24.ru\n"
        "📍 МО — выезжаем на любой объект\n\n"
        "Режим работы: Пн–Сб 8:00–20:00\n"
        "Экстренные выезды — круглосуточно",
        parse_mode="Markdown"
    )

@dp.message(Command("order"))
async def cmd_order(message: Message, state: FSMContext):
    await state.set_state(Order.choosing_service)
    await message.answer(
        "🔧 *Выберите услугу:*",
        parse_mode="Markdown",
        reply_markup=kb_services()
    )

# ─── CALLBACK: главное меню ───────────────────────────────────────────────────

@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(
        "Главное меню — чем могу помочь?",
        reply_markup=kb_main()
    )

@dp.callback_query(F.data == "start_order")
async def start_order(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Order.choosing_service)
    await cb.message.edit_text(
        "🔧 *Выберите услугу:*",
        parse_mode="Markdown",
        reply_markup=kb_services()
    )

@dp.callback_query(F.data == "show_prices")
async def show_prices(cb: CallbackQuery):
    text = "💰 *Прайс-лист VTehnike 24*\n\n"
    for svc in SERVICES.values():
        text += f"• {svc['name']}\n  {svc['price']} · {svc['days']}\n\n"
    text += "_Точная стоимость — после фото или осмотра_"
    await cb.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Оставить заявку", callback_data="start_order")],
            [InlineKeyboardButton(text="⬅️ Назад",           callback_data="back_main")],
        ])
    )

@dp.callback_query(F.data == "rental_info")
async def rental_info(cb: CallbackQuery):
    await cb.message.edit_text(
        "🚜 *Аренда спецтехники*\n\n"
        "• Экскаватор (JCB, Volvo, Komatsu) — от 2 500 ₽/час\n"
        "• Погрузчик фронтальный — от 2 000 ₽/час\n"
        "• Мини-экскаватор — от 1 800 ₽/час\n\n"
        "✅ С оператором\n"
        "✅ Выезд по МО\n"
        "✅ Работаем с ИП и ООО\n\n"
        "Для заявки — нажмите кнопку ниже 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Заявка на аренду", callback_data="srv_rental")],
            [InlineKeyboardButton(text="⬅️ Назад",            callback_data="back_main")],
        ])
    )

@dp.callback_query(F.data == "call_us")
async def call_us(cb: CallbackQuery):
    await cb.message.edit_text(
        "📞 *Позвоните нам:*\n\n"
        "+7 (___) ___-__-__\n\n"
        "Режим работы: Пн–Сб 8:00–20:00\n"
        "Экстренные выезды — круглосуточно\n\n"
        "Или оставьте заявку — мы перезвоним сами 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Оставить заявку", callback_data="start_order")],
            [InlineKeyboardButton(text="⬅️ Назад",           callback_data="back_main")],
        ])
    )

# ─── CALLBACK: выбор услуги ───────────────────────────────────────────────────

@dp.callback_query(F.data == "back_services")
async def back_services(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Order.choosing_service)
    await cb.message.edit_text(
        "🔧 *Выберите услугу:*",
        parse_mode="Markdown",
        reply_markup=kb_services()
    )

@dp.callback_query(F.data.startswith("srv_"), Order.choosing_service)
async def choose_service(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("srv_", "")
    await state.update_data(service=key)
    svc = SERVICES[key]
    await state.set_state(Order.choosing_urgency)
    await cb.message.edit_text(
        f"✅ Выбрано: *{svc['name']}*\n"
        f"💰 {svc['price']} · {svc['days']}\n\n"
        f"⏱ *Выберите срочность:*",
        parse_mode="Markdown",
        reply_markup=kb_urgency()
    )

# Обработка нажатия услуги вне состояния (из rental_info и т.д.)
@dp.callback_query(F.data.startswith("srv_"))
async def choose_service_any(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("srv_", "")
    await state.set_state(Order.choosing_service)
    await state.update_data(service=key)
    svc = SERVICES[key]
    await state.set_state(Order.choosing_urgency)
    await cb.message.edit_text(
        f"✅ Выбрано: *{svc['name']}*\n"
        f"💰 {svc['price']} · {svc['days']}\n\n"
        f"⏱ *Выберите срочность:*",
        parse_mode="Markdown",
        reply_markup=kb_urgency()
    )

# ─── CALLBACK: срочность ─────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("urg_"), Order.choosing_urgency)
async def choose_urgency(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("urg_", "")
    await state.update_data(urgency=key)
    await state.set_state(Order.entering_tech)
    await cb.message.edit_text(
        f"✅ Срочность: *{URGENCY[key]['name']}*\n\n"
        "🚜 *Укажите тип и марку техники*\n"
        "_Например: Экскаватор Komatsu PC200, Погрузчик JCB 3CX_",
        parse_mode="Markdown"
    )

# ─── FSM: ввод данных ─────────────────────────────────────────────────────────

@dp.message(Order.entering_tech)
async def enter_tech(message: Message, state: FSMContext):
    await state.update_data(tech=message.text)
    await state.set_state(Order.entering_location)
    await message.answer(
        "📍 *Укажите адрес объекта или район*\n"
        "_Например: Подольск, ул. Ленина 5, стройка / Красногорск_",
        parse_mode="Markdown"
    )

@dp.message(Order.entering_location)
async def enter_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text)
    await state.set_state(Order.entering_phone)
    await message.answer(
        "📞 *Укажите ваш номер телефона*\n"
        "Нажмите кнопку ниже или введите вручную:",
        parse_mode="Markdown",
        reply_markup=kb_phone()
    )

@dp.message(Order.entering_phone, F.contact)
async def enter_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await state.set_state(Order.entering_comment)
    await message.answer(
        "💬 *Опишите проблему подробнее*\n"
        "_Фото можно прислать после подтверждения заявки_\n\n"
        "Или нажмите «Пропустить» если всё понятно:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("👇", reply_markup=kb_skip())

@dp.message(Order.entering_phone)
async def enter_phone_text(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(Order.entering_comment)
    await message.answer(
        "💬 *Опишите проблему подробнее*\n"
        "_Фото можно прислать после подтверждения заявки_\n\n"
        "Или нажмите «Пропустить»:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("👇", reply_markup=kb_skip())

@dp.callback_query(F.data == "skip_comment", Order.entering_comment)
async def skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="нет")
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await cb.message.edit_text(
        order_summary(data) + "\n\n_Всё верно?_",
        parse_mode="Markdown",
        reply_markup=kb_confirm()
    )

@dp.message(Order.entering_comment)
async def enter_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    data = await state.get_data()
    await state.set_state(Order.confirm)
    await message.answer(
        order_summary(data) + "\n\n_Всё верно?_",
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
        "✅ *Заявка принята!*\n\n"
        "Мы свяжемся с вами в течение *15 минут*.\n\n"
        "📸 Если хотите — пришлите фото повреждения прямо в этот чат, "
        "это поможет точнее назвать цену.\n\n"
        "Спасибо, что выбрали VTehnike 24! 🤝",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 На главную", callback_data="back_main")]
        ])
    )

@dp.callback_query(F.data == "confirm_no", Order.confirm)
async def cancel_order(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(
        "Хорошо, начнём заново. Чем могу помочь?",
        reply_markup=kb_main()
    )

# ─── ФОТО от клиента ──────────────────────────────────────────────────────────

@dp.message(F.photo)
async def handle_photo(message: Message):
    # Пересылаем фото владельцу
    await bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
    await bot.send_message(
        OWNER_ID,
        f"📸 Фото от клиента: {message.from_user.full_name} "
        f"(ID: {message.from_user.id})"
    )
    await message.answer(
        "📸 Фото получено! Оценим и свяжемся с вами в течение 15 минут. 👍",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 На главную", callback_data="back_main")]
        ])
    )

# ─── ЛЮБОЕ ДРУГОЕ СООБЩЕНИЕ ───────────────────────────────────────────────────

@dp.message()
async def fallback(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        return  # Идёт заполнение формы — не мешаем
    await message.answer(
        "Не понял 🤔 Воспользуйтесь меню:",
        reply_markup=kb_main()
    )

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

async def main():
    print("✅ VTehnike 24 Bot запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
