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

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")

WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

ADMIN_ID = int(os.getenv("ADMIN_ID", "692408588"))

CATALOG_FILE = Path("catalog.json")
PENDING_FILE = Path("pending.json")  # заявки в ожидании апрува

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

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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

# ============ Админ: удаление уже апрувнутого лота ============
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

# =================== Любой пользователь: продать =================
@dp.message(F.text == "Продать вещь")
async def user_sell(m: types.Message, state: FSMContext):
    await state.set_state(Form.photos)
    await state.update_data(photos=[], owner_id=m.from_user.id, owner_username=m.from_user.username)
    await m.answer(
        "Пришли фото вещи (1–10 шт). Можно альбомом.\n"
        "Когда закончишь — отправь любое не‑фото сообщение.",
        reply_markup=ReplyKeyboardRemove(),
    )

# ---------- фото -----------
@dp.message(Form.photos, F.photo)
async def handle_photos(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(m.photo[-1].file_id)
    await state.update_data(photos=photos)
    await m.answer(f"Фото добавлено. Всего: {len(photos)}")
    if len(photos) >= 10:
        await m.answer("10 фото — максимум.")
        await ask_title(m, state)

@dp.message(Form.photos)
async def finish_photos(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await m.answer("Сначала пришли хотя бы одно фото.")
        return
    await ask_title(m, state)

async def ask_title(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer("Введи название вещи.", reply_markup=cancel_kb)

# ---------- остальные поля формы ----------
@dp.message(Form.title)
async def form_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(Form.year)
    await m.answer("Год или эпоха (можно примерный).")

@dp.message(Form.year)
async def form_year(m: types.Message, state: FSMContext):
    await state.update_data(year=m.text.strip())
    await state.set_state(Form.condition)
    await m.answer("Состояние (например: отличное, есть потёртости).")

@dp.message(Form.condition)
async def form_condition(m: types.Message, state: FSMContext):
    await state.update_data(condition=m.text.strip())
    await state.set_state(Form.size)
    await m.answer("Размер/габариты.")

@dp.message(Form.size)
async def form_size(m: types.Message, state: FSMContext):
    await state.update_data(size=m.text.strip())
    await state.set_state(Form.price)
    await m.answer("Цена в рублях.")

@dp.message(Form.price)
async def form_price(m: types.Message, state: FSMContext):
    await state.update_data(price=m.text.strip())
    await state.set_state(Form.city)
    await m.answer("Город.")

@dp.message(Form.city)
async def form_city(m: types.Message, state: FSMContext):
    await state.update_data(city=m.text.strip())
    await state.set_state(Form.comment)
    await m.answer("Комментарий для покупателя (опционально).")

@dp.message(Form.comment)
async def form_comment(m: types.Message, state: FSMContext):
    data = await state.get_data()
    data["comment"] = m.text.strip()

    # создаём заявку, но не публикуем сразу
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

    # пользователю: заявка отправлена
    await m.answer("Заявка отправлена на модерацию. Ожидай решения админа.", reply_markup=main_kb)

    # админу: медиагруппа + кнопки апрува
    msgs = await bot.send_media_group(chat_id=ADMIN_ID, media=media)
    await msgs[-1].answer(
        f"Заявка #{pending_id}. Апрувнуть?",
        reply_markup=approve_kb(pending_id),
    )

# =================== Апрув / отклонение админом =================
@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет прав.", show_alert=True)
        return

    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        await call.answer("Заявка не найдена.", show_alert=True)
        return

    # переносим в каталог
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

    # удаляем из pending
    global pending
    pending = [x for x in pending if x["pending_id"] != pending_id]
    save_pending()

    await call.message.edit_text(f"Заявка #{pending_id} апрувнута как лот №{lot_id}.")
    await call.answer("Апрувнуто.")

    # уведомляем автора
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

    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        await call.answer("Заявка не найдена.", show_alert=True)
        return

    global pending
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

# =================== Актуальные лоты / покупка ==================
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
    await bot.send_message(ADMIN_ID, f"Вопрос от @{m.from_user.username}: {m.text}")

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

# =================== Webhook / запуск ===========================
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    await bot.send_message(ADMIN_ID, "БОТ ЗАПУЩЕН!")
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Бот остановлен.")

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
