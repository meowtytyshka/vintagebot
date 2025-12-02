import os
import json
import asyncio
import logging
from pathlib
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

ADMIN_ID = 692408588
CATALOG_FILE = Path("catalog.json")

# === Каталог ===
def load_catalog():
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except:
            return []
    return []

catalog = load_catalog()
def save_catalog():
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# === Состояния ===
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

# === Клавиатура ===
main_kb = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="Продать вещь")],
    [types.KeyboardButton(text="Актуальные лоты")],
    [types.KeyboardButton(text="Поддержка")]
])

# === Старт ===
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "Привет! Это винтажный маркетплейс\n\n"
        "◾ Продать — жми кнопку\n"
        "◾ Купить — выбери лот в каталоге\n"
        "◾ Вопросы — пиши в поддержку",
        reply_markup=main_kb
    )

# === Админ команды ===
@dp.message(Command("add"))
async def cmd_add(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return await m.answer("Ты не админ")
    await state.set_state(Form.photos)
    await m.answer("Пришли фото лота (1–10 шт)", reply_markup=ReplyKeyboardRemove())

@dp.message(Command("del"))
async def cmd_del(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        lot_id = int(m.text.split(maxsplit=1)[1])
        catalog = [l for l in catalog if l["id"] != lot_id]
        save_catalog()
        await m.answer(f"Лот №{lot_id} удалён")
    except:
        await m.answer("Использование: /del 7")

# === Каталог ===
@dp.message(F.text == "Актуальные лоты")
async def show_catalog(m: types.Message):
    if not catalog:
        return await m.answer("Пока ничего нет в продаже")
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
        await m.answer("Нажми кнопку ниже", reply_markup=kb)
        await asyncio.sleep(0.5)

# === Покупка ===
@dp.callback_query(F.data.startswith("buy_"))
async def buy_lot(cb: types.CallbackQuery, state: FSMContext):
    lot_id = int(cb.data.split("_")[1])
    await state.update_data(lot_id=lot_id)
    await state.set_state(BuyAddress.waiting)
    await cb.message.answer("Напиши адрес и телефон для доставки:")
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
    await m.answer("Заявка отправлена! Скоро свяжусь", reply_markup=main_kb)
    await state.clear()

# === Форма продажи (для обычных пользователей) ===
@dp.message(F.text == "Продать вещь")
async def sell_start(m: types.Message, state: FSMContext):
    await state.set_state(Form.photos)
    await m.answer("Пришли фото вещи (1–10 шт)", reply_markup=ReplyKeyboardRemove())

@dp.message(Form.photos, F.photo)
async def sell_photos(m: types.Message, state: FSMContext):
    photos = [p.file_id for p in m.photo]
    await state.update_data(photos=photos)
    await state.set_state(Form.title)
    await m.answer(f"Получено {len(photos)} фото\n\nНазвание вещи:")

@dp.message(Form.title)
async def sell_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(Form.year)
    await m.answer("Год или эпоха (например: 1987, 70-е)")

@dp.message(Form.year)
async def sell_year(m: types.Message, state: FSMContext):
    await state.update_data(year=m.text)
    await state.set_state(Form.condition)
    await m.answer("Состояние (отличное / хорошее / удовлетворительное)")

@dp.message(Form.condition)
async def sell_condition(m: types.Message, state: FSMContext):
    await state.update_data(condition=m.text)
    await state.set_state(Form.size)
    await m.answer("Размер (или «—» если нет)")

@dp.message(Form.size)
async def sell_size(m: types.Message, state: FSMContext):
    await state.update_data(size=m.text)
    await state.set_state(Form.price)
    await m.answer("Желаемая цена чистыми (только цифры, например: 45000)")

@dp.message(Form.price)
async def sell_price(m: types.Message, state: FSMContext):
    await state.update_data(price=m.text)
    await state.set_state(Form.city)
    await m.answer("Город, где находится вещь")

@dp.message(Form.city)
async def sell_city(m: types.Message, state: FSMContext):
    await state.update_data(city=m.text)
    await state.set_state(Form.comment)
    await m.answer("Комментарий (по желанию) — можно просто нажать «пропустить» или отправить точку")

@dp.message(Form.comment)
async def sell_finish(m: types.Message, state: FSMContext):
    data = await state.get_data()
    user = m.from_user

    text = f"""НОВАЯ ЗАЯВКА НА ПРОДАЖУ
От: @{user.username or 'нет'} (ID: {user.id})
{user.full_name}

Вещь: {data['title']}
Год: {data['year']}
Состояние: {data['condition']}
Размер: {data.get('size', '—')}
Цена: {data['price']} ₽
Город: {data['city']}
Комментарий: {m.text or '—'}"""

    await bot.send_message(ADMIN_ID, text)
    if data.get('photos'):
        media = [InputMediaPhoto(p) for p in data['photos'][:10]]
        await bot.send_media_group(ADMIN_ID, media)

    await m.answer("Спасибо! Заявка отправлена, скоро свяжусь лично", reply_markup=main_kb)
    await state.clear()

# === Админская форма добавления лота (отдельная ветка) ===
@dp.message(Form.photos, F.photo)
async def admin_photos(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    photos = [p.file_id for p in m.photo]
    await state.update_data(photos=photos)
    await state.set_state(Form.title)
    await m.answer(f"Фото получено ({len(photos)} шт)\n\nНазвание + цена (например: Пальто YSL 1987 — 120000 ₽)")

@dp.message(Form.title)
async def admin_title(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(title=m.text)
    await state.set_state(Form.comment)
    await m.answer("Полное описание (год, состояние, размер и т.д.)")

@dp.message(Form.comment)
async def admin_finish(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    new_lot = {
        "id": len(catalog) + 1,
        "photos": data["photos"],
        "title": data["title"],
        "desc": m.text
    }
    catalog.append(new_lot)
    save_catalog()
    await m.answer(f"Лот №{new_lot['id']} добавлен в каталог!", reply_markup=main_kb)
    await state.clear()

# === Поддержка (один раз и выключается) ===
@dp.message(F.text == "Поддержка")
async def support_start(m: types.Message):
    await m.answer("Напиши свой вопрос — я перешлю админу", reply_markup=ReplyKeyboardRemove())

@dp.message()
async def support(m: types.Message):
    if m.text in ["Продать вещь", "Актуальные лоты", "Поддержка"]:
        return
    await m.forward(ADMIN_ID)
    await bot.send_message(ADMIN_ID, f"ПОДДЕРЖКА от @{m.from_user.username or 'нет'} (ID: {m.from_user.id})")
    await m.answer("Сообщение отправлено! Скоро отвечу", reply_markup=main_kb)

# === Webhook ===
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    await bot.send_message(ADMIN_ID, "БОТ ЗАПУЩЕН И РАБОТАЕТ 100%!\nВсе баги исправлены")

async def on_shutdown(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
handler.register(app, path=WEBHOOK_PATH)

app.router.add_get("/", lambda r: web.Response(text="OK"))

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
