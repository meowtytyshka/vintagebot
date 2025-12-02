import os
import json
import asyncio
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

# ========================== Логирование ==========================

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

# ========================== Каталог ==============================

def load_catalog() -> list[dict]:
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.exception(f"Ошибка загрузки каталога: {e}")
            return []
    return []


catalog: list[dict] = load_catalog()


def save_catalog() -> None:
    try:
        CATALOG_FILE.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.exception(f"Ошибка сохранения каталога: {e}")


def next_lot_id() -> int:
    if not catalog:
        return 1
    return max(item["id"] for item in catalog) + 1


# ========================== FSM =================================

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


def lot_inline_kb(lot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить", callback_data=f"buy:{lot_id}")],
        ]
    )


# ========================== Старт / отмена =======================

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer(
        "Привет! Это винтажный маркетплейс.\n\n"
        "◾ Продать — жми «Продать вещь»\n"
        "◾ Купить — раздел «Актуальные лоты»\n"
        "◾ Вопросы — кнопка «Поддержка»",
        reply_markup=main_kb,
    )


@dp.message(Command("cancel"))
async def cmd_cancel(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Действие отменено.", reply_markup=main_kb)


# ========================== Админ / каталог ======================

@dp.message(Command("add"))
async def cmd_add(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("Ты не админ.")
        return

    await state.set_state(Form.photos)
    await state.update_data(photos=[])
    await m.answer(
        "Пришли фото лота (1–10 шт). Можно альбомом.\n"
        "Когда закончишь — просто напиши любое сообщение.",
        reply_markup=ReplyKeyboardRemove(),
    )


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


# ===================== Приём фото (1–10) ========================

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
    # Любой не‑фото апдейт в этом состоянии считается окончанием загрузки
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await m.answer("Сначала пришли хотя бы одно фото.")
        return

    await ask_title(m, state)


async def ask_title(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer("Введи название вещи.", reply_markup=cancel_kb)


# ====================== Остальные шаги формы =====================

@dp.message(Form.title)
async def form_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(Form.year)
    await m.answer("Год или эпоха (можно примерный).", reply_markup=cancel_kb)


@dp.message(Form.year)
async def form_year(m: types.Message, state: FSMContext):
    await state.update_data(year=m.text.strip())
    await state.set_state(Form.condition)
    await m.answer("Состояние (например: отличное, есть потёртости).")


@dp.message(Form.condition)
async def form_condition(m: types.Message, state: FSMContext):
    await state.update_data(condition=m.text.strip())
    await state.set_state(Form.size)
    await m.answer("Размер (одежда/обувь) или габариты.")


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

    lot_id = next_lot_id()
    item = {
        "id": lot_id,
        "photos": data["photos"],
        "title": data["title"],
        "year": data["year"],
        "condition": data["condition"],
        "size": data["size"],
        "price": data["price"],
        "city": data["city"],
        "comment": data["comment"],
    }

    catalog.append(item)
    save_catalog()

    await state.clear()

    caption = (
        f"Лот №{lot_id}\n"
        f"{item['title']}\n"
        f"Год: {item['year']}\n"
        f"Состояние: {item['condition']}\n"
        f"Размер: {item['size']}\n"
        f"Цена: {item['price']} ₽\n"
        f"Город: {item['city']}\n\n"
        f"{item['comment']}"
    )

    media = [InputMediaPhoto(media=item["photos"][0], caption=caption)]
    for p in item["photos"][1:]:
        media.append(InputMediaPhoto(media=p))

    await m.answer("Лот сохранён и добавлен в каталог.", reply_markup=main_kb)
    await bot.send_media_group(chat_id=ADMIN_ID, media=media)


# ====================== Пользователь: меню =======================

@dp.message(F.text == "Продать вещь")
async def user_sell(m: types.Message, state: FSMContext):
    await cmd_add(m, state)


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
        msg_group = await bot.send_media_group(chat_id=m.chat.id, media=media)
        # Кнопку «Купить» вешаем на последнее сообщение альбома
        await msg_group[-1].answer(
            "Если хочешь купить, жми кнопку:",
            reply_markup=lot_inline_kb(item["id"]),
        )


@dp.message(F.text == "Поддержка")
async def user_support(m: types.Message):
    await m.answer(
        "Напиши свой вопрос — передадим его администратору.",
        reply_markup=main_kb,
    )
    await bot.send_message(ADMIN_ID, f"Вопрос от @{m.from_user.username}: {m.text}")


# ====================== Покупка лота =============================

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
        "Напиши данные для отправки (ФИО, телефон, адрес или твой @username)."
    )
    await call.answer()


@dp.message(BuyAddress.waiting)
async def buy_address(m: types.Message, state: FSMContext):
    data = await state.get_data()
    lot_id = data["buy_lot_id"]
    item = next((x for x in catalog if x["id"] == lot_id), None)

    await bot.send_message(
        ADMIN_ID,
        f"Новая заявка на лот №{lot_id} ({item['title'] if item else 'UNKNOWN'})\n\n"
        f"От: @{m.from_user.username} (id {m.from_user.id})\n"
        f"Контакты/адрес:\n{m.text}",
    )

    await state.clear()
    await m.answer(
        "Заявка отправлена продавцу. Он свяжется с тобой в ближайшее время.",
        reply_markup=main_kb,
    )


# ========================== Webhook ==============================

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

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    ).register(app, path=WEBHOOK_PATH)

    # health-check
    async def index(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.router.add_get("/", index)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
