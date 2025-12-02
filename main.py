# main.py — финальная версия под твои задачи
import os
import json
import asyncio
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton

bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ADMIN_ID = 692408588  # ← твой Telegram ID
CATALOG_FILE = "catalog.json"

# Загрузка/сохранение каталога
def load_catalog():
    if Path(CATALOG_FILE).exists():
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_catalog(data):
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

catalog = load_catalog()

# ====================== СОСТОЯНИЯ ======================
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
    waiting_address = State()

# ====================== КЛАВИАТУРА ======================
main_kb = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="Продать вещь")],
    [types.KeyboardButton(text="Актуальные лоты")],
    [types.KeyboardButton(text="Поддержка / вопрос")],
])

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "Привет! Это винтажный маркетплейс 🕰\n\n"
        "◾ Продать — заполни форму\n"
        "◾ Купить — выбери лот и напиши адрес\n"
        "◾ Вопросы — пиши в «Поддержка»",
        reply_markup=main_kb
    )

# ====================== ДОБАВЛЕНИЕ ЛОТА (ТОЛЬКО ТЫ) ======================
@dp.message(Command("add"))
async def add_lot(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("Ты не админ 😅")
        return
    await state.set_state(SellForm.photos)
    await m.answer("Пришли фото лота (1–10 шт)")

@dp.message(SellForm.photos, F.photo)
async def lot_photos(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(photos=[p.file_id for p in m.photo])
    await state.set_state(SellForm.title)
    await m.answer("Название + цена (например: Джинсы Levi’s 501 1966 — 68 000 ₽)")

@dp.message(SellForm.title)
async def lot_title(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    await state.update_data(title=m.text)
    await state.set_state(SellForm.comment)
    await m.answer("Описание (год, состояние, размер, комплект и т.д.)")

@dp.message(SellForm.comment)
async def lot_finish(m: types.Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    new_lot = {
        "id": len(catalog) + 1,
        "photos": data["photos"],
        "title": data["title"],
        "desc": m.text,
        "active": True
    }
    catalog.append(new_lot)
    save_catalog(catalog)
    await m.answer(f"Лот №{new_lot['id']} добавлен в каталог!")
    await state.clear()

# УДАЛЕНИЕ ЛОТА (команда /del 5)
@dp.message(Command("del"))
async def delete_lot(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        lot_id = int(m.text.split()[1])
        catalog = [l for l in catalog if l["id"] != lot_id]
        save_catalog(catalog)
        await m.answer(f"Лот №{lot_id} удалён")
    except:
        await m.answer("Использование: /del 5")

# ====================== КАТАЛОГ ======================
@dp.message(F.text == "Актуальные лоты")
async def show_catalog(m: types.Message):
    active_lots = [l for l in catalog if l.get("active", True)]
    if not active_lots:
        await m.answer("Пока ничего нет в продаже 😔\nСледи за обновлениями!")
        return

    await m.answer(f"Актуальные лоты ({len(active_lots)} шт.):")

    for lot in active_lots[::-1]:  # с конца (новые сверху)
        caption = f"№{lot['id']} • {lot['title']}\n\n{lot['desc']}\n\nНажми кнопку → напиши адрес доставки"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ХОЧУ КУПИТЬ ЭТУ ВЕЩЬ", callback_data=f"buy_{lot['id']}")]
        ])

        media = [InputMediaPhoto(media=lot['photos'][0], caption=caption)]
        for photo in lot['photos'][1:]:
            media.append(InputMediaPhoto(media=photo))

        await m.answer_media_group(media=media)
        await m.answer("👆", reply_markup=kb)
        await asyncio.sleep(0.5)

# ====================== ПОКУПКА ======================
@dp.callback_query(F.data.startswith("buy_"))
async def buy_lot(cb: types.CallbackQuery, state: FSMContext):
    lot_id = int(cb.data.split("_")[1])
    await state.update_data(lot_id=lot_id)
    await state.set_state(BuyAddress.waiting_address)
    await cb.message.answer(
        f"Отлично! Ты выбрал лот №{lot_id}\n\n"
        "Напиши свой адрес и телефон для доставки\n"
        "(например: Москва, ул. Ленина 10, +7 999 123-45-67)"
    )
    await cb.answer()

@dp.message(BuyAddress.waiting_address)
async def get_address(m: types.Message, state: FSMContext):
    data = await state.get_data()
    lot_id = data["lot_id"]

    text = f"""
НОВАЯ ЗАЯВКА НА ПОКУПКУ

Лот №{lot_id}
От: @{m.from_user.username or 'нет'} (ID: {m.from_user.id})
Имя: {m.from_user.full_name}

Адрес и телефон:
{m.text}
    """.strip()

    await bot.send_message(ADMIN_ID, text)
    await m.answer("Заявка отправлена! Скоро свяжусь с тобой лично ❤️")
    await state.clear()

# ====================== ПРОДАЖА ОТ ПОЛЬЗОВАТЕЛЕЙ ======================
@dp.message(SellForm.title)
async def user_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(SellForm.year)
    await m.answer("Год или эпоха")

@dp.message(SellForm.year)
async def user_year(m: types.Message, state: FSMContext):
    await state.update_data(year=m.text)
    await state.set_state(SellForm.condition)
    await m.answer("Состояние")

@dp.message(SellForm.condition)
async def user_condition(m: types.Message, state: FSMContext):
    await state.update_data(condition=m.text)
    await state.set_state(SellForm.size)
    await m.answer("Размер (или —)")

@dp.message(SellForm.size)
async def user_size(m: types.Message, state: FSMContext):
    await state.update_data(size=m.text)
    await state.set_state(SellForm.price)
    await m.answer("Цена чистыми")

@dp.message(SellForm.price)
async def user_price(m: types.Message, state: FSMContext):
    await state.update_data(price=m.text)
    await state.set_state(SellForm.city)
    await m.answer("Город вещи")

@dp.message(SellForm.city)
async def user_city(m: types.Message, state: FSMContext):
    await state.update_data(city=m.text)
    await state.set_state(SellForm.comment)
    await m.answer("Комментарий")

@dp.message(SellForm.comment)
async def user_sell_finish(m: types.Message, state: FSMContext):
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
Комментарий: {m.text}
    """.strip()

    await bot.send_message(ADMIN_ID, text)
    if data.get('photos'):
        media = [InputMediaPhoto(media=p) for p in data['photos'][:10]]
        await bot.send_media_group(ADMIN_ID, media)

    await m.answer("Заявка отправлена! Скоро напишу лично ✈️", reply_markup=main_kb)
    await state.clear()
