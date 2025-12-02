import os
import json
import asyncio
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiohttp.web import Request, Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_PATH = f"/webhook/{TOKEN}"  # Путь с токеном для безопасности (как в docs)
ADMIN_ID = 692408588
CATALOG_FILE = Path("catalog.json")

# Загрузка каталога
def load_catalog():
    if CATALOG_FILE.exists():
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return []

catalog = load_catalog()

def save_catalog():
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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
    if m.from_user.id != ADMIN_ID:
        await m.answer("Ты не админ! 😅")
        return
    await state.set_state(SellForm.photos)
    await m.answer("Пришли фото лота (1–10 шт)")

@dp.message(Command("del"))
async def cmd_del(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        lot_id = int(m.text.split()[1])
        global catalog
        catalog = [l for l in catalog if l["id"] != lot_id]
        save_catalog()
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

# === Актуальные лоты ===
@dp.message(F.text == "Актуальные лоты")
async def show_catalog(m: types.Message):
    if not catalog:
        await m.answer("Пока ничего нет в продаже 😔")
        return
    await m.answer("Актуальные лоты:")
    for lot in catalog[::-1]:  # Новые сверху
        caption = f"№{lot['id']} • {lot['title']}\n\n{lot['desc']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ХОЧУ КУПИТЬ", callback_data=f"buy_{lot['id']}")]
        ])
        media = [InputMediaPhoto(media=lot['photos'][0], caption=caption)]
        for p in lot['photos'][1:]:
            media.append(InputMediaPhoto(media=p))
        await m.answer_media_group(media)
        await m.answer("👇 Нажми кнопку для покупки", reply_markup=kb)

# === Покупка ===
@dp.callback_query(F.data.startswith("buy_"))
async def buy_lot(cb: types.CallbackQuery, state: FSMContext):
    lot_id = int(cb.data.split("_")[1])
    await state.update_data(lot_id=lot_id)
    await state.set_state(BuyAddress.waiting)
    await cb.message.answer(f"Выбрал лот №{lot_id}!\n\nНапиши адрес доставки и телефон (например: Москва, ул. Ленина 10, +7 999 123-45-67)")
    await cb.answer()

@dp.message(BuyAddress.waiting)
async def get_address(m: types.Message, state: FSMContext):
    data = await state.get_data()
    text = f"""НОВАЯ ЗАЯВКА НА ПОКУПКУ

Лот №{data['lot_id']}
От: @{m.from_user.username or 'нет'} (ID: {m.from_user.id})
Имя: {m.from_user.full_name}

Адрес/телефон: {m.text}"""
    await bot.send_message(ADMIN_ID, text)
    await m.answer("Заявка отправлена! Скоро свяжусь с тобой ❤️", reply_markup=main_kb)
    await state.clear()

# === Продажа от пользователей ===
@dp.message(F.text == "Продать вещь")
async def sell_start(m: types.Message, state: FSMContext):
    await state.set_state(SellForm.photos)
    await m.answer("Пришли фото вещи (1–10 шт)", reply_markup=types.ReplyKeyboardRemove())

@dp.message(SellForm.photos, F.photo)
async def sell_photos(m: types.Message, state: FSMContext):
    await state.update_data(photos=[p.file_id for p in m.photo])
    await state.set_state(SellForm.title)
    await m.answer("Название вещи (например: Куртка Levi’s 1950-х)")

@dp.message(SellForm.title)
async def sell_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(SellForm.year)
    await m.answer("Год или эпоха (например: 1968, 1970-е)")

@dp.message(SellForm.year)
async def sell_year(m: types.Message, state: FSMContext):
    await state.update_data(year=m.text)
    await state.set_state(SellForm.condition)
    await m.answer("Состояние (отличное/хорошее/удовлетворительное)")

@dp.message(SellForm.condition)
async def sell_condition(m: types.Message, state: FSMContext):
    await state.update_data(condition=m.text)
    await state.set_state(SellForm.size)
    await m.answer("Размер (или —)")

@dp.message(SellForm.size)
async def sell_size(m: types.Message, state: FSMContext):
    await state.update_data(size=m.text)
    await state.set_state(SellForm.price)
    await m.answer("Желаемая цена чистыми (например: 45000)")

@dp.message(SellForm.price)
async def sell_price(m: types.Message, state: FSMContext):
    await state.update_data(price=m.text)
    await state.set_state(SellForm.city)
    await m.answer("Город, где вещь")

@dp.message(SellForm.city)
async def sell_city(m: types.Message, state: FSMContext):
    await state.update_data(city=m.text)
    await state.set_state(SellForm.comment)
    await m.answer("Комментарий (состояние, комплект и т.д.)")

@dp.message(SellForm.comment)
async def sell_finish(m: types.Message, state: FSMContext):
    data = await state.get_data()
    user = m.from_user
    text = f"""НОВАЯ ЗАЯВКА НА ПРОДАЖУ

От: @{user.username or 'нет'} (ID: {user.id})
Имя: {user.full_name}

Вещь: {data['title']}
Год: {data['year']}
Состояние: {data['condition']}
Размер: {data.get('size', '—')}
Цена: {data['price']} ₽
Город: {data['city']}
Комментарий: {m.text}"""
    await bot.send_message(ADMIN_ID, text)
    if 'photos' in data:
        media = [InputMediaPhoto(media=p) for p in data['photos'][:10]]
        await bot.send_media_group(ADMIN_ID, media)
    await m.answer("Заявка отправлена! Скоро напишу лично ✈️", reply_markup=main_kb)
    await state.clear()

# === Добавление лота админом ===
@dp.message(SellForm.photos, F.photo)  # Отдельный хендлер для админа
async def admin_photos(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(photos=[p.file_id for p in m.photo])
    await state.set_state(SellForm.title)
    await m.answer("Название + цена (например: Сумка Chanel 1980 — 150000 ₽)")

@dp.message(SellForm.title)  # Админ
async def admin_title(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(title=m.text)
    await state.set_state(SellForm.comment)
    await m.answer("Описание (год, состояние, размер и т.д.)")

@dp.message(SellForm.comment)  # Админ
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
    await m.answer(f"Лот №{new_lot['id']} добавлен в каталог!")
    await state.clear()

# === Поддержка ===
@dp.message(F.text == "Поддержка")
async def support_start(m: types.Message):
    await m.answer("Напиши свой вопрос — перешлю админу")

@dp.message()  # Любое другое сообщение — поддержка
async def support(m: types.Message):
    if m.text in ["Продать вещь", "Актуальные лоты", "Поддержка"]:
        return
    await m.forward(ADMIN_ID)
    await bot.send_message(ADMIN_ID, f"ПОДДЕРЖКА / ВОПРОС\nОт: @{m.from_user.username or 'нет'} (ID: {m.from_user.id})\n{m.from_user.full_name}")
    await m.answer("Сообщение отправлено! Ответим скоро ✍️", reply_markup=main_kb)

# === Webhook ===
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Webhook установлен!")
    await bot.send_message(ADMIN_ID, "🚀 Бот полностью готов на Render! Тестируй /start")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# Правильная настройка webhook с SimpleRequestHandler
handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
handler.register(app, path=WEBHOOK_PATH)

# Health-check для Render
async def health(request: Request):
    return Response(text="OK", status=200)

app.router.add_get("/", health)

if __name__ == "__main__":
    logger.info("Запуск бота...")
    web.run_app(app, host="0.0.0.0", port=PORT)
