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

# ========================== Настройки ==========================
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"
ADMIN_ID = int(os.getenv("ADMIN_ID", "692408588"))

CATALOG_FILE = Path("catalog.json")
PENDING_FILE = Path("pending.json")

# ========================== Работа с JSON ==========================
def load_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.exception(f"Ошибка загрузки {path}: {e}")
    return []

def save_json(path: Path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.exception(f"Ошибка сохранения {path}: {e}")

catalog = load_json(CATALOG_FILE)
pending = load_json(PENDING_FILE)

def save_catalog(): save_json(CATALOG_FILE, catalog)
def save_pending(): save_json(PENDING_FILE, pending)

def next_lot_id() -> int:
    return max((item.get("id", 0) for item in catalog), default=0) + 1

# ========================== Состояния ==========================
class Form(StatesGroup):
    photos = State()
    title = State()
    year = State()
    condition = State()
    size = State()
    price = State()
    city = State()
    comment = State()

class BuyAddress(StatesGroup):
    waiting = State()

# ========================== Бот ==========================
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========================== Клавиатуры ==========================
main_kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="Продать вещь")],
    [KeyboardButton(text="Актуальные лоты")],
    [KeyboardButton(text="Поддержка")],
])

cancel_kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[[KeyboardButton(text="/cancel")]])

def lot_inline_kb(lot_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Купить", callback_data=f"buy:{lot_id}")]])

def approve_kb(pending_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Апрув", callback_data=f"approve:{pending_id}"),
        InlineKeyboardButton(text="Отклонить", callback_data=f"reject:{pending_id}"),
    ]])

# ========================== Команды ==========================
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Это винтажный маркетплейс.\n\n"
        "◾ Продать — жми «Продать вещь»\n"
        "◾ Купить — раздел «Актуальные лоты»\n"
        "◾ Вопросы — «Поддержка»",
        reply_markup=main_kb,
    )

@dp.message(Command("cancel"))
async def cmd_cancel(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Действие отменено.", reply_markup=main_kb)

@dp.message(Command("del"))
async def cmd_del(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        lot_id = int(m.text.split(maxsplit=1)[1])
    except:
        return await m.answer("Использование: /del 7")
    global catalog
    catalog = [l for l in catalog if l.get("id") != lot_id]
    save_catalog()
    await m.answer(f"Лот №{lot_id} удалён.")

# ========================== Продажа вещи ==========================
@dp.message(F.text == "Продать вещь")
async def user_sell(m: types.Message, state: FSMContext):
    await state.set_state(Form.photos)
    await state.update_data(photos=[], owner_id=m.from_user.id, owner_username=m.from_user.username or "unknown")
    await m.answer(
        "Пришли фото вещи (1–10 шт). Можно альбомом.\n"
        "Когда закончишь — просто отправь любое текстовое сообщение.",
        reply_markup=ReplyKeyboardRemove(),
    )

# КЛЮЧЕВОЙ ХЭНДЛЕР — работает с одиночными фото и альбомами (aiogram 3.9+)
@dp.message(Form.photos, F.content_type.in_({'photo'}))
async def handle_photos(m: types.Message, state: FSMContext, album: list[types.Message] | None = None):
    data = await state.get_data()
    photos: list = data.get("photos", [])

    if album:  # пришёл альбом
        for msg in album:
            if msg.photo:
                photos.append(msg.photo[-1].file_id)
        text = f"Альбом принят! Всего фото: {len(photos)}"
    else:  # одиночное фото
        photos.append(m.photo[-1].file_id)
        text = f"Фото добавлено. Всего: {len(photos)}"

    await state.update_data(photos=photos)
    await m.answer(text)

    if len(photos) >= 10:
        await m.answer("Достигнут лимит в 10 фото.")
        await state.set_state(Form.title)
        await m.answer("Теперь введи название вещи.", reply_markup=cancel_kb)

# Если прислали НЕ фото — считаем, что фото закончились
@dp.message(Form.photos)
async def finish_photos_phase(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await m.answer("Ты не прислал ни одного фото. Начни заново.")
        await state.clear()
        return
    await state.set_state(Form.title)
    await m.answer("Отлично! Теперь введи название вещи.", reply_markup=cancel_kb)

# Остальные шаги формы (без изменений)
@dp.message(Form.title, F.text)
async def form_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(Form.year)
    await m.answer("Год или эпоха")

@dp.message(Form.year, F.text)
async def form_year(m: types.Message, state: FSMContext):
    await state.update_data(year=m.text.strip())
    await state.set_state(Form.condition)
    await m.answer("Состояние")

@dp.message(Form.condition, F.text)
async def form_condition(m: types.Message, state: FSMContext):
    await state.update_data(condition=m.text.strip())
    await state.set_state(Form.size)
    await m.answer("Размер")

@dp.message(Form.size, F.text)
async def form_size(m: types.Message, state: FSMContext):
    await state.update_data(size=m.text.strip())
    await state.set_state(Form.price)
    await m.answer("Цена в рублях")

@dp.message(Form.price, F.text)
async def form_price(m: types.Message, state: FSMContext):
    await state.update_data(price=m.text.strip())
    await state.set_state(Form.city)
    await m.answer("Город")

@dp.message(Form.city, F.text)
async def form_city(m: types.Message, state: FSMContext):
    await state.update_data(city=m.text.strip())
    await state.set_state(Form.comment)
    await m.answer("Комментарий (по желанию)")

@dp.message(Form.comment, F.text)
async def form_comment(m: types.Message, state: FSMContext):
    data = await state.get_data()
    pending_id = len(pending) + 1

    item = {
        "pending_id": pending_id,
        "owner_id": data["owner_id"],
        "owner_username": data["owner_username"],
        "photos": data["photos"][:10],
        "title": data["title"],
        "year": data["year"],
        "condition": data["condition"],
        "size": data["size"],
        "price": data["price"],
        "city": data["city"],
        "comment": m.text.strip() or "—",
    }
    pending.append(item)
    save_pending()

    # Пользователю
    await m.answer("Заявка отправлена на модерацию!", reply_markup=main_kb)

    # Админу
    caption = (
        f"Заявка #{pending_id}\n"
        f"{item['title']}\n"
        f"Год: {item['year']}\n"
        f"Состояние: {item['condition']}\n"
        f"Размер: {item['size']}\n"
        f"Цена: {item['price']} ₽\n"
        f"Город: {item['city']}\n\n"
        f"{item['comment']}\n\n"
        f"От: @{item['owner_username']} (id {item['owner_id']})"
    )
    media = [InputMediaPhoto(media=item["photos"][0], caption=caption)]
    for p in item["photos"][1:]:
        media.append(InputMediaPhoto(media=p))

    sent = await bot.send_media_group(ADMIN_ID, media)
    await sent[-1].answer("Апрувнуть?", reply_markup=approve_kb(pending_id))

    await state.clear()

# ========================== Модерация ==========================
@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет прав", show_alert=True)
    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        return await call.answer("Заявка уже обработана", show_alert=True)

    lot_id = next_lot_id()
    catalog.append({**item, "id": lot_id})
    save_catalog()

    pending[:] = [x for x in pending if x["pending_id"] != pending_id]  # без global!
    save_pending()

    await call.message.edit_text(f"Заявка #{pending_id} → Лот №{lot_id} опубликован")
    await call.answer("Опубликовано")
    try:
        await bot.send_message(item["owner_id"], f"Твоя вещь опубликована как лот №{lot_id}!")
    except:
        pass

@dp.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет прав", show_alert=True)
    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        return await call.answer_answer("Заявка уже обработана", show_alert=True)

    pending[:] = [x for x in pending if x["pending_id"] != pending_id]
    save_pending()

    await call.message.edit_text(f"Заявка #{pending_id} отклонена")
    await call.answer("Отклонено")
    try:
        await bot.send_message(item["owner_id"], "Твоя заявка отклонена.")
    except:
        pass

# ========================== Каталог и покупка ==========================
@dp.message(F.text == "Актуальные лоты")
async def user_catalog(m: types.Message):
    if not catalog:
        return await m.answer("Пока ничего нет в продаже", reply_markup=main_kb)
    for lot in catalog:
        caption = f"№{lot['id']} • {lot['title']}\nЦена: {lot['price']} ₽ • {lot['city']}"
        media = [InputMediaPhoto(media=lot["photos"][0], caption=caption)]
        for p in lot["photos"][1:]:
            media.append(InputMediaPhoto(media=p))
        sent = await bot.send_media_group
