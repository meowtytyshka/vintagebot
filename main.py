import os
import json
import logging
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================== Настройки ============================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")

WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

ADMIN_ID = int(os.getenv("ADMIN_ID", "692408588"))

CATALOG_FILE = Path("catalog.json")
PENDING_FILE = Path("pending.json")

# ========================== Работа с файлами =====================

def load_json(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.exception(f"Ошибка загрузки {path}: {e}")
    return []

def save_json(path: Path, data: list[dict]):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.exception(f"Ошибка сохранения {path}: {e}")

catalog: list[dict] = load_json(CATALOG_FILE)
pending: list[dict] = load_json(PENDING_FILE)

def save_catalog():
    save_json(CATALOG_FILE, catalog)

def save_pending():
    save_json(PENDING_FILE, pending)

def next_lot_id() -> int:
    if not catalog:
        return 1
    return max(item["id"] for item in catalog) + 1

# ========================== FSM =================================

class Form(StatesGroup):
    photos = State()
    photos_confirm = State()
    title = State()
    title_confirm = State()
    year = State()
    year_confirm = State()
    condition = State()
    condition_confirm = State()
    size = State()
    size_confirm = State()
    price = State()
    price_confirm = State()
    city = State()
    city_confirm = State()
    comment = State()
    comment_confirm = State()

class BuyAddress(StatesGroup):
    waiting = State()

# ========================== Бот / диспетчер ======================

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========================== Клавиатуры ===========================

main_kb = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[
        [KeyboardButton(text="Продать вещь")],
        [KeyboardButton(text="Актуальные лоты")],
        [KeyboardButton(text="Поддержка")],
    ],
)

cancel_kb = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[[KeyboardButton(text="/cancel")]],
)

photos_kb = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[
        [KeyboardButton(text="Добавить ещё фото")],
        [KeyboardButton(text="Дальше"), KeyboardButton(text="/cancel")],
    ],
)

def yes_no_kb(ok_text: str, edit_text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text=ok_text), KeyboardButton(text=edit_text)],
            [KeyboardButton(text="/cancel")],
        ],
    )

def lot_inline_kb(lot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить", callback_data=f"buy:{lot_id}")],
        ]
    )

def approve_kb(pending_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Апрув", callback_data=f"approve:{pending_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pending_id}"),
            ]
        ]
    )

# ========================== Общие команды ========================

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Это винтажный маркетплейс.\n\n"
        "◾ Продать — жми «Продать вещь»\n"
        "◾ Купить — «Актуальные лоты»\n"
        "◾ Вопросы — «Поддержка»",
        reply_markup=main_kb,
    )

@dp.message(Command("cancel"))
async def cmd_cancel(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Действие отменено.", reply_markup=main_kb)

# ========================== Админ-команды ========================

@dp.message(Command("del"))
async def cmd_del(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        lot_id = int(m.text.split()[1])
    except Exception:
        await m.answer("Использование: /del 7")
        return

    global catalog
    before = len(catalog)
    catalog = [l for l in catalog if l["id"] != lot_id]
    save_catalog()
    if len(catalog) < before:
        await m.answer(f"Лот №{lot_id} удалён.")
    else:
        await m.answer("Такого лота нет.")

# ========================== Продать вещь =========================

@dp.message(F.text == "Продать вещь")
async def user_sell(m: types.Message, state: FSMContext):
    await state.set_state(Form.photos)
    await state.update_data(
        photos=[],
        owner_id=m.from_user.id,
        owner_username=m.from_user.username,
    )
    await m.answer(
        "Пришли фото вещи (1–10 шт). Можно альбомом.\n"
        "Затем нажми «Дальше».",
        reply_markup=photos_kb,
    )

# ----- загрузка фото -----

@dp.message(Form.photos, F.photo)
async def handle_photos(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(m.photo[-1].file_id)
    await state.update_data(photos=photos)
    await m.answer(
        f"Фото добавлено. Всего: {len(photos)}.\n"
        "Можешь прислать ещё или нажать «Дальше».",
        reply_markup=photos_kb,
    )

@dp.message(Form.photos, F.text == "Добавить ещё фото")
async def photos_more(m: types.Message, state: FSMContext):
    await m.answer("Пришли ещё фото сообщением с картинкой.", reply_markup=photos_kb)

@dp.message(Form.photos, F.text == "Дальше")
async def photos_next(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await m.answer("Сначала пришли хотя бы одно фото.", reply_markup=photos_kb)
        return
    await state.set_state(Form.photos_confirm)
    await m.answer(
        f"Фото сохранены ({len(photos)} шт).\n"
        "Всё верно?",
        reply_markup=yes_no_kb("✅ Фото верные", "✏️ Загрузить заново"),
    )

@dp.message(Form.photos_confirm, F.text == "✏️ Загрузить заново")
async def photos_reset(m: types.Message, state: FSMContext):
    await state.update_data(photos=[])
    await state.set_state(Form.photos)
    await m.answer(
        "Окей, пришли фото ещё раз (1–10 шт).",
        reply_markup=photos_kb,
    )

@dp.message(Form.photos_confirm, F.text == "✅ Фото верные")
async def photos_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer(
        "Теперь введи название вещи.",
        reply_markup=cancel_kb,
    )

# ----- название -----

@dp.message(Form.title)
async def form_title(m: types.Message, state: FSMContext):
    title = m.text.strip()
    await state.update_data(title=title)
    await state.set_state(Form.title_confirm)
    await m.answer(
        f"Название: «{title}».\n"
        "Если всё ок — нажми «✅ Название верное», иначе «✏️ Изменить название».",
        reply_markup=yes_no_kb("✅ Название верное", "✏️ Изменить название"),
    )

@dp.message(Form.title_confirm, F.text == "✏️ Изменить название")
async def title_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer("Введи название ещё раз.", reply_markup=cancel_kb)

@dp.message(Form.title_confirm, F.text == "✅ Название верное")
async def title_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.year)
    await m.answer("Теперь введи год или эпоху (можно примерный).", reply_markup=cancel_kb)

# ----- год -----

@dp.message(Form.year)
async def form_year(m: types.Message, state: FSMContext):
    year = m.text.strip()
    await state.update_data(year=year)
    await state.set_state(Form.year_confirm)
    await m.answer(
        f"Год/эпоха: «{year}».\n"
        "Нажми «✅ Год верный» или «✏️ Изменить год».",
        reply_markup=yes_no_kb("✅ Год верный", "✏️ Изменить год"),
    )

@dp.message(Form.year_confirm, F.text == "✏️ Изменить год")
async def year_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.year)
    await m.answer("Введи год или эпоху ещё раз.", reply_markup=cancel_kb)

@dp.message(Form.year_confirm, F.text == "✅ Год верный")
async def year_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.condition)
    await m.answer(
        "Опиши состояние вещи (например: отличное, есть потёртости).",
        reply_markup=cancel_kb,
    )

# ----- состояние -----

@dp.message(Form.condition)
async def form_condition(m: types.Message, state: FSMContext):
    cond = m.text.strip()
    await state.update_data(condition=cond)
    await state.set_state(Form.condition_confirm)
    await m.answer(
        f"Состояние: «{cond}».\n"
        "Нажми «✅ Состояние верное» или «✏️ Изменить состояние».",
        reply_markup=yes_no_kb("✅ Состояние верное", "✏️ Изменить состояние"),
    )

@dp.message(Form.condition_confirm, F.text == "✏️ Изменить состояние")
async def condition_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.condition)
    await m.answer("Опиши состояние ещё раз.", reply_markup=cancel_kb)

@dp.message(Form.condition_confirm, F.text == "✅ Состояние верное")
async def condition_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.size)
    await m.answer("Укажи размер или габариты.", reply_markup=cancel_kb)

# ----- размер -----

@dp.message(Form.size)
async def form_size(m: types.Message, state: FSMContext):
    size = m.text.strip()
    await state.update_data(size=size)
    await state.set_state(Form.size_confirm)
    await m.answer(
        f"Размер/габариты: «{size}».\n"
        "Нажми «✅ Размер верный» или «✏️ Изменить размер».",
        reply_markup=yes_no_kb("✅ Размер верный", "✏️ Изменить размер"),
    )

@dp.message(Form.size_confirm, F.text == "✏️ Изменить размер")
async def size_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.size)
    await m.answer("Укажи размер/габариты ещё раз.", reply_markup=cancel_kb)

@dp.message(Form.size_confirm, F.text == "✅ Размер верный")
async def size_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.price)
    await m.answer("Укажи цену в рублях.", reply_markup=cancel_kb)

# ----- цена -----

@dp.message(Form.price)
async def form_price(m: types.Message, state: FSMContext):
    price = m.text.strip()
    await state.update_data(price=price)
    await state.set_state(Form.price_confirm)
    await m.answer(
        f"Цена: «{price} ₽».\n"
        "Нажми «✅ Цена верная» или «✏️ Изменить цену».",
        reply_markup=yes_no_kb("✅ Цена верная", "✏️ Изменить цену"),
    )

@dp.message(Form.price_confirm, F.text == "✏️ Изменить цену")
async def price_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.price)
    await m.answer("Укажи цену ещё раз.", reply_markup=cancel_kb)

@dp.message(Form.price_confirm, F.text == "✅ Цена верная")
async def price_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.city)
    await m.answer("Укажи город.", reply_markup=cancel_kb)

# ----- город -----

@dp.message(Form.city)
async def form_city(m: types.Message, state: FSMContext):
    city = m.text.strip()
    await state.update_data(city=city)
    await state.set_state(Form.city_confirm)
    await m.answer(
        f"Город: «{city}».\n"
        "Нажми «✅ Город верный» или «✏️ Изменить город».",
        reply_markup=yes_no_kb("✅ Город верный", "✏️ Изменить город"),
    )

@dp.message(Form.city_confirm, F.text == "✏️ Изменить город")
async def city_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.city)
    await m.answer("Укажи город ещё раз.", reply_markup=cancel_kb)

@dp.message(Form.city_confirm, F.text == "✅ Город верный")
async def city_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.comment)
    await m.answer(
        "Добавь комментарий для покупателя (можно просто «-»).",
        reply_markup=cancel_kb,
    )

# ----- комментарий и финальное подтверждение -----

@dp.message(Form.comment)
async def form_comment(m: types.Message, state: FSMContext):
    comment = m.text.strip()
    await state.update_data(comment=comment)
    await state.set_state(Form.comment_confirm)

    data = await state.get_data()
    preview = (
        f"Проверь карточку лота:\n\n"
        f"Название: {data['title']}\n"
        f"Год/эпоха: {data['year']}\n"
        f"Состояние: {data['condition']}\n"
        f"Размер: {data['size']}\n"
        f"Цена: {data['price']} ₽\n"
        f"Город: {data['city']}\n"
        f"Комментарий: {data['comment']}\n\n"
        f"Если всё ок — нажми «✅ Отправить на модерацию», "
        f"если надо что‑то исправить — «✏️ Исправить поля»."
    )

    await m.answer(
        preview,
        reply_markup=yes_no_kb("✅ Отправить на модерацию", "✏️ Исправить поля"),
    )

@dp.message(Form.comment_confirm, F.text == "✏️ Исправить поля")
async def comment_fix(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer(
        "Окей, начнём правку с названия. Введи название ещё раз.",
        reply_markup=cancel_kb,
    )

@dp.message(Form.comment_confirm, F.text == "✅ Отправить на модерацию")
async def comment_ok(m: types.Message, state: FSMContext):
    data = await state.get_data()

    pending_id = len(pending) + 1
    request_item = {
        "pending_id": pending_id,
        "owner_id": data["owner_id"],
        "owner_username": data["owner_username"],
        "photos": data["photos"],
        "title": data["title"],
        "year": data["year"],
        "condition": data["condition"],
        "size": data["size"],
        "price": data["price"],
        "city": data["city"],
        "comment": data["comment"],
    }
    pending.append(request_item)
    save_pending()
    await state.clear()

    caption = (
        f"Заявка #{pending_id}\n"
        f"{request_item['title']}\n"
        f"Год: {request_item['year']}\n"
        f"Состояние: {request_item['condition']}\n"
        f"Размер: {request_item['size']}\n"
        f"Цена: {request_item['price']} ₽\n"
        f"Город: {request_item['city']}\n\n"
        f"{request_item['comment']}\n\n"
        f"От: @{request_item['owner_username']} (id {request_item['owner_id']})"
    )

    media = [InputMediaPhoto(media=request_item["photos"][0], caption=caption)]
    for p in request_item["photos"][1:]:
        media.append(InputMediaPhoto(media=p))

    await m.answer(
        "Заявка отправлена на модерацию. Ожидай решения админа.",
        reply_markup=main_kb,
    )

    msgs = await bot.send_media_group(chat_id=ADMIN_ID, media=media)
    await msgs[-1].answer(
        f"Заявка #{pending_id}. Апрувнуть?",
        reply_markup=approve_kb(pending_id),
    )

# ========================== Апрув / отклонение ==================

@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет прав.", show_alert=True)
        return

    global pending

    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        await call.answer("Заявка не найдена.", show_alert=True)
        return

    lot_id = next_lot_id()
    lot = {
        "id": lot_id,
        "photos": item["photos"],
        "title": item["title"],
        "year": item["year"],
        "condition": item["condition"],
        "size": item["size"],
        "price": item["price"],
        "city": item["city"],
        "comment": item["comment"],
        "owner_id": item["owner_id"],
    }
    catalog.append(lot)
    save_catalog()

    pending = [x for x in pending if x["pending_id"] != pending_id]
    save_pending()

    await call.message.edit_text(f"Заявка #{pending_id} апрувнута как лот №{lot_id}.")
    await call.answer("Апрувнуто.")

    try:
        await bot.send_message(
            lot["owner_id"],
            f"Твоя заявка одобрена и опубликована как лот №{lot_id}!",
        )
    except Exception:
        logger.info("Не удалось написать пользователю после апрува.")

@dp.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет прав.", show_alert=True)
        return

    global pending

    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        await call.answer("Заявка не найдена.", show_alert=True)
        return

    pending = [x for x in pending if x["pending_id"] != pending_id]
    save_pending()

    await call.message.edit_text(f"Заявка #{pending_id} отклонена.")
    await call.answer("Отклонено.")

    try:
        await bot.send_message(
            item["owner_id"],
            "К сожалению, твоя заявка на продажу отклонена.",
        )
    except Exception:
        logger.info("Не удалось написать пользователю после отклонения.")

# ========================== Каталог / покупка ====================

@dp.message(F.text == "Актуальные лоты")
async def user_catalog(m: types.Message):
    if not catalog:
        await m.answer("Сейчас лотов нет.", reply_markup=main_kb)
        return

    for item in catalog:
        caption = (
            f"Лот №{item['id']}\n"
            f"{item['title']}\n"
            f"Цена: {item['price']} ₽\n"
            f"Город: {item['city']}"
        )
        media = [InputMediaPhoto(media=item["photos"][0], caption=caption)]
        for p in item["photos"][1:]:
            media.append(InputMediaPhoto(media=p))
        msgs = await bot.send_media_group(chat_id=m.chat.id, media=media)
        await msgs[-1].answer(
            "Если хочешь купить, жми кнопку:",
            reply_markup=lot_inline_kb(item["id"]),
        )

@dp.message(F.text == "Поддержка")
async def user_support(m: types.Message):
    await m.answer("Напиши свой вопрос одним сообщением — передадим админу.")
    await bot.send_message(
        ADMIN_ID,
        f"Вопрос от @{m.from_user.username}: {m.text}",
    )

@dp.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: types.CallbackQuery, state: FSMContext):
    lot_id = int(call.data.split(":")[1])
    item = next((x for x in catalog if x["id"] == lot_id), None)
    if not item:
        await call.message.answer("Лот уже недоступен.")
        await call.answer()
        return

    await state.set_state(BuyAddress.waiting)
    await state.update_data(buy_lot_id=lot_id)
    await call.message.answer(
        "Напиши данные для отправки (ФИО, телефон, адрес или @username)."
    )
    await call.answer()

@dp.message(BuyAddress.waiting)
async def buy_address(m: types.Message, state: FSMContext):
    data = await state.get_data()
    lot_id = data["buy_lot_id"]
    item = next((x for x in catalog if x["id"] == lot_id), None)

    await bot.send_message(
        ADMIN_ID,
        f"Новая заявка на покупку лота №{lot_id} ({item['title'] if item else 'UNKNOWN'})\n\n"
        f"От: @{m.from_user.username} (id {m.from_user.id})\n"
        f"Контакты/адрес:\n{m.text}",
    )

    await state.clear()
    await m.answer("Заявка отправлена продавцу.", reply_markup=main_kb)

# ========================== Webhook / запуск =====================

async def on_startup(app: web.Application):
    try:
        await bot.set_webhook(WEBHOOK_URL)
        await bot.send_message(ADMIN_ID, "БОТ ЗАПУЩЕН!")
        logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    except Exception:
        logger.exception("Ошибка в on_startup")

async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook()
        await bot.session.close()
        logger.info("Бот остановлен.")
    except Exception:
        logger.exception("Ошибка в on_shutdown")

def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)

    async def index(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.router.add_get("/", index)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
