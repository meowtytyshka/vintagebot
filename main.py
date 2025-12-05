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
        [KeyboardButton(text="🛒 Продать вещь")],
        [KeyboardButton(text="📦 Актуальные лоты")],
        [KeyboardButton(text="📞 Поддержка")],
    ],
)

cancel_kb = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
)

photos_kb = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[
        [KeyboardButton(text="➕ Добавить ещё фото")],
        [KeyboardButton(text="✅ Далее"), KeyboardButton(text="❌ Отмена")],
    ],
)

def yes_no_kb(ok_text: str, edit_text: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text=ok_text), KeyboardButton(text=edit_text)],
            [KeyboardButton(text="❌ Отмена")],
        ],
    )

def lot_inline_kb(lot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy:{lot_id}")],
        ],
    )

def catalog_menu_kb() -> InlineKeyboardMarkup:
    keyboard = []
    for item in catalog[:10]:  # Максимум 10 лотов в меню
        keyboard.append([InlineKeyboardButton(
            text=f"🖼️ {item['title'][:30]}... | {item['price']}₽",
            callback_data=f"lot:{item['id']}"
        )])
    if len(catalog) > 10:
        keyboard.append([InlineKeyboardButton(text="📜 Показать все", callback_data="show_all")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def approve_kb(pending_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{pending_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pending_id}"),
            ],
        ],
    )

# ========================== Общие команды ========================
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer(
        "🎉 Добро пожаловать в винтажный маркетплейс!\n\n"
        "🛒 *Продать* — разместите свою вещь\n"
        "📦 *Купить* — посмотрите актуальные лоты\n"
        "📞 *Поддержка* — вопросы и проблемы\n\n"
        "Выбирайте кнопку ниже 👇",
        reply_markup=main_kb,
        parse_mode="Markdown",
    )

@dp.message(F.text == "❌ Отмена")
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
        await m.answer(f"✅ Лот №{lot_id} удалён.")
    else:
        await m.answer("❌ Такого лота нет.")

# ========================== Продать вещь =========================
@dp.message(F.text == "🛒 Продать вещь")
async def user_sell(m: types.Message, state: FSMContext):
    await state.set_state(Form.photos)
    await state.update_data(
        photos=[],
        owner_id=m.from_user.id,
        owner_username=m.from_user.username,
    )
    await m.answer(
        "📸 Отправьте 1-10 фото вашей вещи\n"
        "💡 Можно альбомом или по одной\n\n"
        "Когда закончите — нажмите «✅ Далее»",
        reply_markup=photos_kb,
    )

# ----- загрузка фото -----
@dp.message(Form.photos, F.photo)
async def handle_photos(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if len(photos) >= 10:
        await m.answer("⚠️ Максимум 10 фото! Нажмите «✅ Далее»", reply_markup=photos_kb)
        return
    photos.append(m.photo[-1].file_id)
    await state.update_data(photos=photos)
    await m.answer(
        f"✅ Фото добавлено\n📊 Всего: *{len(photos)}/10*\n\n"
        "Можно добавить ещё или нажать «✅ Далее»",
        reply_markup=photos_kb,
        parse_mode="Markdown",
    )

@dp.message(Form.photos, F.text == "➕ Добавить ещё фото")
async def photos_more(m: types.Message, state: FSMContext):
    await m.answer("📸 Пришлите фото!", reply_markup=photos_kb)

@dp.message(Form.photos, F.text == "✅ Далее")
async def photos_next(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await m.answer("❌ Нужно хотя бы одно фото!", reply_markup=photos_kb)
        return
    await state.set_state(Form.photos_confirm)
    await m.answer(
        f"📸 Фото сохранены (*{len(photos)} шт*)\n\n"
        "✅ *Верно* — продолжить\n"
        "✏️ *Заново* — загрузить другие",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Заново"),
        parse_mode="Markdown",
    )

@dp.message(Form.photos_confirm, F.text == "✏️ Заново")
async def photos_reset(m: types.Message, state: FSMContext):
    await state.update_data(photos=[])
    await state.set_state(Form.photos)
    await m.answer("🗑️ Фото сброшены. Пришлите новые:", reply_markup=photos_kb)

@dp.message(Form.photos_confirm, F.text == "✅ Верно")
async def photos_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer("✏️ Введите *название вещи*\nПример: «Диван кожаный 80х»", reply_markup=cancel_kb, parse_mode="Markdown")

# ----- остальные поля формы (аналогично) -----
@dp.message(Form.title)
async def form_title(m: types.Message, state: FSMContext):
    title = m.text.strip()
    await state.update_data(title=title)
    await state.set_state(Form.title_confirm)
    await m.answer(
        f"📛 *Название*: `{title}`\n\n"
        "✅ *Верно* — продолжить\n"
        "✏️ *Изменить* — ввести другое",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Изменить"),
        parse_mode="Markdown",
    )

@dp.message(Form.title_confirm, F.text == "✏️ Изменить")
async def title_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer("✏️ Введите название заново:", reply_markup=cancel_kb)

@dp.message(Form.title_confirm, F.text == "✅ Верно")
async def title_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.year)
    await m.answer("🗓️ Укажите *год выпуска* или *возраст*\nПример: «1985» или «~40 лет»", reply_markup=cancel_kb, parse_mode="Markdown")

# ----- год -----
@dp.message(Form.year)
async def form_year(m: types.Message, state: FSMContext):
    year = m.text.strip()
    await state.update_data(year=year)
    await state.set_state(Form.year_confirm)
    await m.answer(
        f"🗓️ *Год/возраст*: `{year}`\n\n"
        "✅ *Верно* | ✏️ *Изменить*",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Изменить"),
        parse_mode="Markdown",
    )

@dp.message(Form.year_confirm, F.text == "✏️ Изменить")
async def year_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.year)
    await m.answer("🗓️ Введите год/возраст заново:", reply_markup=cancel_kb)

@dp.message(Form.year_confirm, F.text == "✅ Верно")
async def year_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.condition)
    await m.answer(
        "⭐ Опишите *состояние вещи*\n"
        "Пример: «Отличное, царапин нет»",
        reply_markup=cancel_kb,
        parse_mode="Markdown",
    )

# ----- состояние -----
@dp.message(Form.condition)
async def form_condition(m: types.Message, state: FSMContext):
    cond = m.text.strip()
    await state.update_data(condition=cond)
    await state.set_state(Form.condition_confirm)
    await m.answer(
        f"⭐ *Состояние*: `{cond}`\n\n"
        "✅ *Верно* | ✏️ *Изменить*",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Изменить"),
        parse_mode="Markdown",
    )

@dp.message(Form.condition_confirm, F.text.in_(["✏️ Изменить", "Изменить"]))
async def condition_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.condition)
    await m.answer("⭐ Опишите состояние заново:", reply_markup=cancel_kb)

@dp.message(Form.condition_confirm, F.text == "✅ Верно")
async def condition_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.size)
    await m.answer("📏 Укажите *размер/габариты*\nПример: «200×90×90 см»", reply_markup=cancel_kb, parse_mode="Markdown")

# ----- размер -----
@dp.message(Form.size)
async def form_size(m: types.Message, state: FSMContext):
    size = m.text.strip()
    await state.update_data(size=size)
    await state.set_state(Form.size_confirm)
    await m.answer(
        f"📏 *Размер*: `{size}`\n\n"
        "✅ *Верно* | ✏️ *Изменить*",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Изменить"),
        parse_mode="Markdown",
    )

@dp.message(Form.size_confirm, F.text == "✏️ Изменить")
async def size_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.size)
    await m.answer("📏 Укажите размер заново:", reply_markup=cancel_kb)

@dp.message(Form.size_confirm, F.text == "✅ Верно")
async def size_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.price)
    await m.answer("💰 Укажите *чистую цену* в рублях\nПример: «5000»", reply_markup=cancel_kb, parse_mode="Markdown")

# ----- цена -----
@dp.message(Form.price)
async def form_price(m: types.Message, state: FSMContext):
    price = m.text.strip()
    await state.update_data(price=price)
    await state.set_state(Form.price_confirm)
    await m.answer(
        f"💰 *Цена*: `{price} ₽`\n\n"
        "✅ *Верно* | ✏️ *Изменить*",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Изменить"),
        parse_mode="Markdown",
    )

@dp.message(Form.price_confirm, F.text == "✏️ Изменить")
async def price_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.price)
    await m.answer("💰 Укажите цену заново:", reply_markup=cancel_kb)

@dp.message(Form.price_confirm, F.text == "✅ Верно")
async def price_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.city)
    await m.answer("📍 Укажите *город*\nПример: «Москва»", reply_markup=cancel_kb, parse_mode="Markdown")

# ----- город -----
@dp.message(Form.city)
async def form_city(m: types.Message, state: FSMContext):
    city = m.text.strip()
    await state.update_data(city=city)
    await state.set_state(Form.city_confirm)
    await m.answer(
        f"📍 *Город*: `{city}`\n\n"
        "✅ *Верно* | ✏️ *Изменить*",
        reply_markup=yes_no_kb("✅ Верно", "✏️ Изменить"),
        parse_mode="Markdown",
    )

@dp.message(Form.city_confirm, F.text == "✏️ Изменить")
async def city_edit(m: types.Message, state: FSMContext):
    await state.set_state(Form.city)
    await m.answer("📍 Укажите город заново:", reply_markup=cancel_kb)

@dp.message(Form.city_confirm, F.text == "✅ Верно")
async def city_ok(m: types.Message, state: FSMContext):
    await state.set_state(Form.comment)
    await m.answer(
        "💬 Добавьте *комментарий* (по желанию)\n"
        "Или напишите «-» если нет",
        reply_markup=cancel_kb,
        parse_mode="Markdown",
    )

# ----- финальное подтверждение -----
@dp.message(Form.comment)
async def form_comment(m: types.Message, state: FSMContext):
    comment = m.text.strip()
    await state.update_data(comment=comment)
    await state.set_state(Form.comment_confirm)

    data = await state.get_data()
    preview = (
        "🔍 *ПРОВЕРЬТЕ ЗАЯВКУ*\n\n"
        f"📛 {data['title']}\n"
        f"🗓️ {data['year']}\n"
        f"⭐ {data['condition']}\n"
        f"📏 {data['size']}\n"
        f"💰 {data['price']} ₽\n"
        f"📍 {data['city']}\n"
        f"💬 {data['comment']}\n\n"
        "✅ *Одобрить* — отправить на модерацию\n"
        "✏️ *Исправить* — вернуться к началу"
    )
    await m.answer(preview, reply_markup=yes_no_kb("✅ Одобрить", "✏️ Исправить"), parse_mode="Markdown")

@dp.message(Form.comment_confirm, F.text == "✏️ Исправить")
async def comment_fix(m: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await m.answer("✏️ Начнём с названия. Введите заново:", reply_markup=cancel_kb)

@dp.message(Form.comment_confirm, F.text == "✅ Одобрить")
async def comment_ok(m: types.Message, state: FSMContext):
    data = await state.get_data()
    global pending
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

    # Отправка пользователю
    await m.answer("🎉 Заявка отправлена на модерацию!\n⏳ Скоро получите ответ.", reply_markup=main_kb)

    # Отправка админу
    caption = (
        f"🆕 НОВАЯ ЗАЯВКА #{pending_id}\n\n"
        f"📛 *{request_item['title']}*\n"
        f"🗓️ {request_item['year']}\n"
        f"⭐ {request_item['condition']}\n"
        f"📏 {request_item['size']}\n"
        f"💰 {request_item['price']} ₽\n"
        f"📍 {request_item['city']}\n"
        f"💬 {request_item['comment']}\n\n"
        f"👤 @{request_item['owner_username']} (ID: {request_item['owner_id']})"
    )
    media = [InputMediaPhoto(media=request_item["photos"][0], caption=caption, parse_mode="Markdown")]
    for p in request_item["photos"][1:]:
        media.append(InputMediaPhoto(media=p))
    
    msgs = await bot.send_media_group(chat_id=ADMIN_ID, media=media)
    await msgs[-1].reply(
        f"Заявка #{pending_id}. Что делаем?",
        reply_markup=approve_kb(pending_id),
    )

# ========================== Апрув / отклонение ===================
@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("🚫 Нет прав.", show_alert=True)
        return

    global pending
    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        await call.answer("❌ Заявка не найдена.", show_alert=True)
        return

    global catalog
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

    await call.message.edit_caption(
        caption=call.message.caption + f"\n\n✅ *ОПУБЛИКОВАНО* как лот №{lot_id}",
        parse_mode="Markdown",
        reply_markup=None,
    )
    await call.answer("✅ Опубликовано!")

    try:
        await bot.send_message(
            lot["owner_id"],
            f"🎉 Ваша заявка *одобрена*!\n\n"
            f"🆔 Лот №{lot_id} опубликован в каталоге!",
            parse_mode="Markdown",
        )
    except Exception:
        logger.info("Не удалось уведомить владельца")

@dp.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("🚫 Нет прав.", show_alert=True)
        return

    global pending
    pending_id = int(call.data.split(":")[1])
    item = next((x for x in pending if x["pending_id"] == pending_id), None)
    if not item:
        await call.answer("❌ Заявка не найдена.", show_alert=True)
        return

    pending = [x for x in pending if x["pending_id"] != pending_id]
    save_pending()

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n❌ *ОТКЛОНЕНО*",
        parse_mode="Markdown",
        reply_markup=None,
    )
    await call.answer("❌ Отклонено")

    try:
        await bot.send_message(
            item["owner_id"],
            "😔 К сожалению, ваша заявка отклонена модератором.",
        )
    except Exception:
        logger.info("Не удалось уведомить владельца")

# ========================== Каталог ==============================
@dp.message(F.text == "📦 Актуальные лоты")
async def user_catalog(m: types.Message):
    if not catalog:
        await m.answer("📭 Сейчас лотов нет.\n\nОбновите позже!", reply_markup=main_kb)
        return
    
    await m.answer(
        f"📦 *АКТУАЛЬНЫЕ ЛОТЫ* ({len(catalog)} шт)\n\n"
        "Выберите интересующий 👇",
        reply_markup=catalog_menu_kb(),
        parse_mode="Markdown",
    )

@dp.callback_query(F.data.startswith("lot:"))
async def show_lot(call: types.CallbackQuery):
    lot_id = int(call.data.split(":")[1])
    item = next((x for x in catalog if x["id"] == lot_id), None)
    if not item:
        await call.answer("❌ Лот удалён", show_alert=True)
        return

    caption = (
        f"🆔 Лот №{item['id']}\n\n"
        f"📛 *{item['title']}*\n"
        f"🗓️ {item['year']}\n"
        f"⭐ {item['condition']}\n"
        f"📏 {item['size']}\n"
        f"💰 *{item['price']} ₽*\n"
        f"📍 {item['city']}\n"
        f"💬 {item['comment']}"
    )
    
    media = [InputMediaPhoto(media=item["photos"][0], caption=caption, parse_mode="Markdown")]
    for p in item["photos"][1:]:
        media.append(InputMediaPhoto(media=p))
    
    await call.message.edit_media(media=media)
    await call.message.answer("💡 Хотите купить? Нажмите кнопку:", reply_markup=lot_inline_kb(lot_id))
    await call.answer()

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    await call.message.edit_text(
        "🏠 Главное меню",
        reply_markup=main_kb,
    )
    await call.answer()

# ========================== Покупка ==============================
@dp.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: types.CallbackQuery, state: FSMContext):
    lot_id = int(call.data.split(":")[1])
    item = next((x for x in catalog if x["id"] == lot_id), None)
    if not item:
        await call.answer("❌ Лот недоступен", show_alert=True)
        return

    await state.set_state(BuyAddress.waiting)
    await state.update_data(buy_lot_id=lot_id)
    await call.message.answer(
        f"🛒 *ПОДТВЕРЖДЕНИЕ ПОКУПКИ*\n\n"
        f"Лот №{lot_id}: {item['title']}\n"
        f"💰 {item['price']} ₽\n\n"
        "📝 Напишите ваши контакты:\n"
        "• Телефон\n"
        "• Telegram\n"
        "• Адрес самовывоза",
        parse_mode="Markdown",
    )
    await call.answer()

@dp.message(BuyAddress.waiting)
async def buy_address(m: types.Message, state: FSMContext):
    data = await state.get_data()
    lot_id = data["buy_lot_id"]
    item = next((x for x in catalog if x["id"] == lot_id), None)

    await bot.send_message(
        ADMIN_ID,
        f"🛒 *НОВАЯ ЗАЯВКА НА ПОКУПКУ*\n\n"
        f"🆔 Лот №{lot_id} ({item['title'] if item else 'UNKNOWN'})\n"
        f"💰 {item['price'] if item else 'N/A'} ₽\n\n"
        f"👤 @{m.from_user.username} (ID: {m.from_user.id})\n\n"
        f"📞 *Контакты*:\n{m.text}",
        parse_mode="Markdown",
    )

    await state.clear()
    await m.answer(
        "✅ Заявка отправлена!\n"
        "📨 С вами свяжется продавец в ближайшее время.",
        reply_markup=main_kb,
    )

# ========================== Поддержка ============================
@dp.message(F.text == "📞 Поддержка")
async def user_support(m: types.Message):
    await m.answer(
        "💬 Напишите ваш вопрос или проблему\n"
        "📤 Перешлём администратору",
        reply_markup=cancel_kb,
    )

@dp.message(F.text, ~F.text.in_(["🛒 Продать вещь", "📦 Актуальные лоты", "📞 Поддержка", "❌ Отмена"]))
async def support_message(m: types.Message):
    if m.from_user.id == ADMIN_ID:
        return  # Админские сообщения игнорируем
    
    await bot.send_message(
        ADMIN_ID,
        f"📞 *СООБЩЕНИЕ В ПОДДЕРЖКУ*\n\n"
        f"👤 @{m.from_user.username} (ID: {m.from_user.id})\n\n"
        f"{m.text}",
        parse_mode="Markdown",
    )
    await m.answer("✅ Сообщение отправлено!\n⏳ Ожидайте ответа.")

# ========================== Webhook ==============================
async def on_startup(app: web.Application):
    try:
        await bot.set_webhook(WEBHOOK_URL)
        await bot.send_message(ADMIN_ID, "🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
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
