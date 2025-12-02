import os
import logging
import json
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from aiohttp.web import Request, Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render автоматически ставит эту переменную
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ADMIN_ID = 692408588
CATALOG_FILE = Path("catalog.json")
catalog = []

if CATALOG_FILE.exists():
    catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))

# === Состояния ===
class SellForm(StatesGroup):
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

# === Клавиатура ===
main_kb = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="Продать вещь")],
    [types.KeyboardButton(text="Актуальные лоты")],
    [types.KeyboardButton(text="Поддержка")]
])

# === Команды админа ===
@dp.message(Command("add"))
async def cmd_add(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.set_state(SellForm.photos)
    await m.answer("Пришли фото лота (1–10 шт)")

# (все остальные хендлеры добавления лота — в конце сообщения, чтобы не резало)

@dp.message(Command("del"))
async def cmd_del(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        lot_id = int(m.text.split()[1])
        global catalog
        catalog = [l for l in catalog if l["id"] != lot_id]
        CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        await m.answer(f"Лот №{lot_id} удалён")
    except:
        await m.answer("Использование: /del 7")

# === Старт ===
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "Привет! Это винтажный маркетплейс 🕰\n\n"
        "◾ Продать — жми кнопку\n"
        "◾ Купить — выбери лот в каталоге\n"
        "◾ Вопросы — пиши в поддержку",
        reply_markup=main_kb
    )

# === Остальной код (каталог, покупка, продажа, поддержка) ===
# (всё ниже — просто вставь в конец main.py)

# Актуальные лоты
@dp.message(F.text == "Актуальные лоты")
async def show_catalog(m: types.Message):
    if not catalog:
        await m.answer("Пока ничего нет в продаже 😔")
        return
    await m.answer("Актуальные лоты:")
    for lot in catalog[::-1]:
        caption = f"№{lot['id']} • {lot['title']}\n\n{lot['desc']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="ХОЧУ КУПИТЬ", callback_data=f"buy_{lot['id']}")
        ]])
        media = [InputMediaPhoto(media=lot['photos'][0], caption=caption)]
        for p in lot['photos'][1:]:
            media.append(InputMediaPhoto(media=p))
        await m.answer_media_group(media)
        await m.answer("↓ Нажми кнопку ↓", reply_markup=kb)

# Покупка
@dp.callback_query(F.data.startswith("buy_"))
async def buy_lot(cb: types.CallbackQuery, state: FSMContext):
    lot_id = int(cb.data.split("_")[1])
    await state.update_data(lot_id=lot_id)
    await state.set_state(BuyAddress.waiting)
    await cb.message.answer(f"Выбран лот №{lot_id}\nНапиши адрес и телефон для доставки:")
    await cb.answer()

@dp.message(BuyAddress.waiting)
async def get_address(m: types.Message, state: FSMContext):
    data = await state.get_data()
    text = f"""НОВАЯ ПОКУПКА
Лот №{data['lot_id']}
От: @{m.from_user.username or 'нет'} (ID: {m.from_user.id})
{m.from_user.full_name}

Адрес/телефон:
{m.text}"""
    await bot.send_message(ADMIN_ID, text)
    await m.answer("Заявка отправлена! Скоро напишу лично ❤️")
    await state.clear()

# Продажа от пользователей
@dp.message(F.text == "Продать вещь")
async def sell_start(m: types.Message, state: FSMContext):
    await state.set_state(SellForm.photos)
    await m.answer("Пришли фото вещи (1–10 шт)", reply_markup=types.ReplyKeyboardRemove())

# (все шаги формы продажи — вставь из предыдущих сообщений, они идентичны)

# Поддержка — всё остальное
@dp.message()
async def support(m: types.Message):
    if m.text in ["Продать вещь", "Актуальные лоты", "Поддержка"]:
        return
    await m.forward(ADMIN_ID)
    await bot.send_message(ADMIN_ID, f"Поддержка от @{m.from_user.username or 'нет'} ({m.from_user.id})")
    await m.answer("Сообщение отправлено, отвечу скоро ✍️")

# === Добавление лота админом (продолжение команды /add) ===
@dp.message(SellForm.photos, F.photo)
async def admin_photos(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(photos=[p.file_id for p in m.photo])
    await state.set_state(SellForm.title)
    await m.answer("Название + цена (например: Пальто Dior 1987 — 85 000 ₽)")

@dp.message(SellForm.title)
async def admin_title(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(title=m.text)
    await state.set_state(SellForm.comment)
    await m.answer("Описание (год, состояние, размер и т.д.)")

@dp.message(SellForm.comment)
async def admin_save(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    new_lot = {
        "id": len(catalog) + 1,
        "photos": data["photos"],
        "title": data["title"],
        "desc": m.text
    }
    catalog.append(new_lot)
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    await m.answer(f"Лот №{new_lot['id']} добавлен!")
    await state.clear()

# === Webhook и запуск ===
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    await bot.send_message(ADMIN_ID, "Бот перезапущен и готов к работе!")

app = web.Application()
app.router.add_post(WEBHOOK_PATH, lambda r: dp.feed_webhook_update(bot, r))
app.router.add_get("/", lambda r: Response(text="OK"))
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
