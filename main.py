import os
import json
import logging
from pathlib import Path
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
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================== Настройки ============================
TOKEN = os.getenv("BOT_TOKEN")  # Получаем из переменных окружения
ADMIN_ID = int(os.getenv("ADMIN_ID", "692408588"))
CATALOG_FILE = Path("catalog.json")
PENDING_FILE = Path("pending.json")

# Для Render
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

# ========================== Работа с файлами =====================
def load_json(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            return []
    return []

def save_json(path: Path, data: list[dict]):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
    title = State()
    year = State()
    condition = State()
    size = State()
    city = State()
    price = State()
    comment = State()
    confirm = State()

class BuyAddress(StatesGroup):
    waiting = State()

class Support(StatesGroup):
    waiting = State()

# ========================== Инициализация ========================
bot = Bot(token=TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========================== Клавиатуры ==========================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Продать вещь")],
            [KeyboardButton(text="📦 Актуальные лоты")],
            [KeyboardButton(text="📞 Поддержка")],
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def get_photos_keyboard(photos_count):
    buttons = []
    if photos_count < 10:
        buttons.append([KeyboardButton(text="➕ Добавить ещё фото")])
    buttons.append([
        KeyboardButton(text="✅ Далее"),
        KeyboardButton(text="❌ Отмена")
    ])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_confirm_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Отправить на модерацию"), KeyboardButton(text="✏️ Исправить")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )

def get_lot_keyboard(lot_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy:{lot_id}")],
            [InlineKeyboardButton(text="📋 Назад", callback_data="back_to_catalog")]
        ]
    )

def get_catalog_keyboard():
    keyboard = []
    for item in catalog[:10]:  # Показываем первые 10 лотов
        keyboard.append([InlineKeyboardButton(
            text=f"🖼️ {item['title'][:25]}... | {item['price']}₽",
            callback_data=f"lot:{item['id']}"
        )])
    keyboard.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_approve_keyboard(pending_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{pending_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pending_id}"),
            ],
        ]
    )

# ========================== Команды =============================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Добро пожаловать в винтажный маркетплейс!</b>\n\n"
        "🛒 <b>Продать</b> — разместите свою вещь на продажу\n"
        "📦 <b>Купить</b> — посмотрите актуальные лоты\n"
        "📞 <b>Поддержка</b> — задайте вопрос или сообщите о проблеме\n\n"
        "👇 Выбирайте кнопку ниже:",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "❌ Отмена")
@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())

# ========================== Продать вещь ========================
@dp.message(F.text == "🛒 Продать вещь")
async def start_selling(message: types.Message, state: FSMContext):
    await state.set_state(Form.photos)
    await state.update_data(photos=[], owner_id=message.from_user.id)
    await message.answer(
        "📸 <b>Шаг 1 из 9: Фотографии</b>\n\n"
        "Пришлите 1-10 фото вашей вещи.\n"
        "Можно по одной или альбомом.\n\n"
        "Когда добавите все фото — нажмите <b>✅ Далее</b>",
        reply_markup=get_photos_keyboard(0)
    )

@dp.message(Form.photos, F.photo)
async def handle_photos(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    
    if len(photos) >= 10:
        await message.answer("⚠️ Максимум 10 фото! Нажмите <b>✅ Далее</b>", reply_markup=get_photos_keyboard(10))
        return
    
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    
    await message.answer(
        f"✅ Фото добавлено!\n"
        f"📊 Загружено: <b>{len(photos)}/10</b>\n\n"
        "Можно добавить ещё или нажать <b>✅ Далее</b>",
        reply_markup=get_photos_keyboard(len(photos))
    )

@dp.message(Form.photos, F.text == "➕ Добавить ещё фото")
async def add_more_photos(message: types.Message):
    await message.answer("📸 Отправьте следующее фото...")

@dp.message(Form.photos, F.text == "✅ Далее")
async def photos_next(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    
    if not photos:
        await message.answer("❌ Нужно хотя бы одно фото!", reply_markup=get_photos_keyboard(0))
        return
    
    await state.set_state(Form.title)
    await message.answer(
        "✏️ <b>Шаг 2 из 9: Название вещи</b>\n\n"
        "Напишите краткое и понятное название:\n"
        "<i>Пример: «Винтажная кожаная куртка 80-х»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.title)
async def form_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(Form.year)
    await message.answer(
        "🗓️ <b>Шаг 3 из 9: Год или возраст</b>\n\n"
        "Укажите примерный год выпуска или возраст:\n"
        "<i>Пример: «1985» или «~40 лет»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.year)
async def form_year(message: types.Message, state: FSMContext):
    await state.update_data(year=message.text.strip())
    await state.set_state(Form.condition)
    await message.answer(
        "⭐ <b>Шаг 4 из 9: Состояние</b>\n\n"
        "Опишите состояние вещи:\n"
        "<i>Пример: «Отличное, мелкие потертости»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.condition)
async def form_condition(message: types.Message, state: FSMContext):
    await state.update_data(condition=message.text.strip())
    await state.set_state(Form.size)
    await message.answer(
        "📏 <b>Шаг 5 из 9: Размер</b>\n\n"
        "Укажите размер или габариты:\n"
        "<i>Пример: «48 размер» или «150×80×80 см»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.size)
async def form_size(message: types.Message, state: FSMContext):
    await state.update_data(size=message.text.strip())
    await state.set_state(Form.city)
    await message.answer(
        "📍 <b>Шаг 6 из 9: Город</b>\n\n"
        "Где находится вещь?\n"
        "<i>Пример: «Москва»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.city)
async def form_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await state.set_state(Form.price)
    await message.answer(
        "💰 <b>Шаг 7 из 9: Цена</b>\n\n"
        "Укажите цену в рублях:\n"
        "<i>Пример: «5000»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.price)
async def form_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text.strip())
    await state.set_state(Form.comment)
    await message.answer(
        "💬 <b>Шаг 8 из 9: Комментарий</b>\n\n"
        "Добавьте дополнительную информацию (по желанию):\n"
        "<i>Пример: «Есть оригинальные бирки»</i>\n\n"
        "Если не нужно — напишите <b>«-»</b>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.comment)
async def form_comment(message: types.Message, state: FSMContext):
    comment = message.text.strip()
    if comment == "-":
        comment = "Без комментариев"
    
    await state.update_data(comment=comment)
    await state.set_state(Form.confirm)
    
    data = await state.get_data()
    
    preview = f"""
📋 <b>ПРЕДПРОСМОТР ЗАЯВКИ</b>

<b>📸 Фото:</b> {len(data['photos'])} шт.
<b>🏷️ Название:</b> {data['title']}
<b>🗓️ Год:</b> {data['year']}
<b>⭐ Состояние:</b> {data['condition']}
<b>📏 Размер:</b> {data['size']}
<b>📍 Город:</b> {data['city']}
<b>💰 Цена:</b> {data['price']} ₽
<b>💬 Комментарий:</b> {data['comment']}

<b>Всё верно?</b>
"""
    await message.answer(preview, reply_markup=get_confirm_keyboard())

@dp.message(Form.confirm, F.text == "✏️ Исправить")
async def edit_form(message: types.Message, state: FSMContext):
    await state.set_state(Form.title)
    await message.answer("✏️ Начнём заново. Введите название вещи:", reply_markup=get_cancel_keyboard())

@dp.message(Form.confirm, F.text == "✅ Отправить на модерацию")
async def submit_form(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    # Создаем заявку
    pending_id = len(pending) + 1
    application = {
        "id": pending_id,
        "owner_id": data["owner_id"],
        "photos": data["photos"],
        "title": data["title"],
        "year": data["year"],
        "condition": data["condition"],
        "size": data["size"],
        "city": data["city"],
        "price": data["price"],
        "comment": data["comment"],
        "username": message.from_user.username
    }
    
    pending.append(application)
    save_pending()
    await state.clear()
    
    # Уведомляем пользователя
    await message.answer(
        "🎉 <b>Заявка отправлена на модерацию!</b>\n\n"
        "⏳ Обычно это занимает до 24 часов.\n"
        "Мы уведомим вас, когда лот будет опубликован.",
        reply_markup=get_main_keyboard()
    )
    
    # Уведомляем админа
    caption = f"""
🆕 <b>НОВАЯ ЗАЯВКА #{pending_id}</b>

<b>🏷️ Название:</b> {application['title']}
<b>🗓️ Год:</b> {application['year']}
<b>⭐ Состояние:</b> {application['condition']}
<b>📏 Размер:</b> {application['size']}
<b>📍 Город:</b> {application['city']}
<b>💰 Цена:</b> {application['price']} ₽
<b>💬 Комментарий:</b> {application['comment']}

<b>👤 Продавец:</b> @{application.get('username', 'нет')}
<b>🆔 ID:</b> {application['owner_id']}
"""
    
    if application['photos']:
        media = [InputMediaPhoto(media=application['photos'][0], caption=caption, parse_mode="HTML")]
        for photo in application['photos'][1:]:
            media.append(InputMediaPhoto(media=photo))
        
        messages = await bot.send_media_group(chat_id=ADMIN_ID, media=media)
        await messages[-1].reply(
            f"Заявка #{pending_id}. Что делаем?",
            reply_markup=get_admin_approve_keyboard(pending_id)
        )

# ========================== Модерация ============================
@dp.callback_query(F.data.startswith("approve:"))
async def approve_application(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет прав", show_alert=True)
        return
    
    pending_id = int(callback.data.split(":")[1])
    app = next((a for a in pending if a["id"] == pending_id), None)
    
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Создаем лот
    lot_id = next_lot_id()
    lot = {
        "id": lot_id,
        "title": app["title"],
        "year": app["year"],
        "condition": app["condition"],
        "size": app["size"],
        "city": app["city"],
        "price": app["price"],
        "comment": app["comment"],
        "photos": app["photos"],
        "owner_id": app["owner_id"],
        "owner_username": app.get("username")
    }
    
    catalog.append(lot)
    save_catalog()
    
    # Удаляем из ожидающих
    pending[:] = [a for a in pending if a["id"] != pending_id]
    save_pending()
    
    # Уведомляем продавца
    try:
        await bot.send_message(
            app["owner_id"],
            f"🎉 <b>Ваша заявка одобрена!</b>\n\n"
            f"🏷️ Лот: {app['title']}\n"
            f"💰 Цена: {app['price']} ₽\n"
            f"🆔 Номер лота: #{lot_id}\n\n"
            f"Теперь ваш лот виден всем в каталоге!",
            parse_mode="HTML"
        )
    except:
        pass
    
    # Обновляем сообщение админу
    try:
        await callback.message.edit_caption(
            caption=callback.message.caption + "\n\n✅ <b>ОПУБЛИКОВАНО</b>",
            parse_mode="HTML"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    
    await callback.answer(f"✅ Лот #{lot_id} опубликован")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_application(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет прав", show_alert=True)
        return
    
    pending_id = int(callback.data.split(":")[1])
    app = next((a for a in pending if a["id"] == pending_id), None)
    
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Удаляем из ожидающих
    pending[:] = [a for a in pending if a["id"] != pending_id]
    save_pending()
    
    # Уведомляем продавца
    try:
        await bot.send_message(
            app["owner_id"],
            "😔 <b>Ваша заявка отклонена</b>\n\n"
            "К сожалению, заявка не прошла модерацию.\n"
            "Вы можете создать новую заявку с исправлениями.",
            parse_mode="HTML"
        )
    except:
        pass
    
    # Обновляем сообщение админу
    try:
        await callback.message.edit_caption(
            caption=callback.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>",
            parse_mode="HTML"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    
    await callback.answer("❌ Заявка отклонена")

# ========================== Каталог ==============================
@dp.message(F.text == "📦 Актуальные лоты")
async def show_catalog(message: types.Message):
    if not catalog:
        await message.answer(
            "📭 <b>Сейчас лотов нет.</b>\n\n"
            "Обновите позже!",
            reply_markup=get_main_keyboard()
        )
        return
    
    await message.answer(
        f"📦 <b>АКТУАЛЬНЫЕ ЛОТЫ</b> ({len(catalog)} шт)\n\n"
        "👇 Выберите интересующий лот:",
        reply_markup=get_catalog_keyboard()
    )

@dp.callback_query(F.data.startswith("lot:"))
async def show_lot(callback: types.CallbackQuery):
    lot_id = int(callback.data.split(":")[1])
    item = next((x for x in catalog if x["id"] == lot_id), None)
    
    if not item:
        await callback.answer("❌ Лот удалён", show_alert=True)
        return
    
    caption = (
        f"🆔 <b>Лот №{item['id']}</b>\n\n"
        f"<b>🏷️ Название:</b> {item['title']}\n"
        f"<b>🗓️ Год/возраст:</b> {item['year']}\n"
        f"<b>⭐ Состояние:</b> {item['condition']}\n"
        f"<b>📏 Размер:</b> {item['size']}\n"
        f"<b>💰 Цена:</b> <b>{item['price']} ₽</b>\n"
        f"<b>📍 Город:</b> {item['city']}\n"
        f"<b>💬 Комментарий:</b> {item['comment']}"
    )
    
    try:
        # Удаляем старое сообщение
        await callback.message.delete()
    except:
        pass
    
    # Отправляем фото с описанием
    if item['photos']:
        media = [InputMediaPhoto(
            media=item['photos'][0],
            caption=caption,
            parse_mode="HTML"
        )]
        
        for photo in item['photos'][1:]:
            media.append(InputMediaPhoto(media=photo))
        
        messages = await bot.send_media_group(
            chat_id=callback.message.chat.id,
            media=media
        )
        
        # Добавляем кнопки к последнему сообщению
        await messages[-1].reply(
            "💡 Хотите купить этот лот?",
            reply_markup=get_lot_keyboard(lot_id)
        )
    
    await callback.answer()

@dp.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(callback: types.CallbackQuery):
    await callback.message.delete()
    await show_catalog(callback.message)

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_start(callback.message)

# ========================== Покупка ==============================
@dp.callback_query(F.data.startswith("buy:"))
async def start_buying(callback: types.CallbackQuery, state: FSMContext):
    lot_id = int(callback.data.split(":")[1])
    item = next((x for x in catalog if x["id"] == lot_id), None)
    
    if not item:
        await callback.answer("❌ Лот недоступен", show_alert=True)
        return
    
    await state.set_state(BuyAddress.waiting)
    await state.update_data(
        lot_id=lot_id,
        lot_title=item['title'],
        lot_price=item['price'],
        seller_id=item['owner_id']
    )
    
    await callback.message.answer(
        f"🛒 <b>ПОДТВЕРЖДЕНИЕ ПОКУПКИ</b>\n\n"
        f"<b>🆔 Лот:</b> #{lot_id} - {item['title']}\n"
        f"<b>💰 Цена:</b> {item['price']} ₽\n\n"
        f"<b>📝 Напишите ваши контакты:</b>\n"
        f"• Телефон\n"
        f"• Telegram\n"
        f"• Город для доставки\n\n"
        f"<i>Пример: «+7 (999) 123-45-67, @username, Москва»</i>",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(BuyAddress.waiting)
async def process_buyer_info(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Покупка отменена", reply_markup=get_main_keyboard())
        return
    
    data = await state.get_data()
    lot_id = data.get("lot_id")
    lot_title = data.get("lot_title")
    lot_price = data.get("lot_price")
    seller_id = data.get("seller_id")
    
    buyer_info = message.text
    
    # Отправляем админу
    await bot.send_message(
        ADMIN_ID,
        f"🛒 <b>НОВАЯ ЗАЯВКА НА ПОКУПКУ!</b>\n\n"
        f"<b>🆔 Лот:</b> #{lot_id} - {lot_title}\n"
        f"<b>💰 Цена:</b> {lot_price} ₽\n\n"
        f"<b>👤 Покупатель:</b>\n"
        f"• Имя: {message.from_user.full_name}\n"
        f"• Username: @{message.from_user.username or 'нет'}\n"
        f"• ID: {message.from_user.id}\n\n"
        f"<b>📞 Контакты:</b>\n{buyer_info}\n\n"
        f"<b>👤 Продавец:</b> ID: {seller_id}",
        parse_mode="HTML"
    )
    
    # Пытаемся уведомить продавца
    try:
        await bot.send_message(
            seller_id,
            f"🎉 <b>ПОКУПКА ВАШЕГО ЛОТА!</b>\n\n"
            f"<b>🆔 Лот:</b> #{lot_id} - {lot_title}\n"
            f"<b>💰 Цена:</b> {lot_price} ₽\n\n"
            f"<b>👤 Покупатель:</b>\n"
            f"• Имя: {message.from_user.full_name}\n"
            f"• Username: @{message.from_user.username or 'нет'}\n\n"
            f"<b>📞 Контакты покупателя:</b>\n{buyer_info}\n\n"
            f"<i>Свяжитесь с покупателем для уточнения деталей!</i>",
            parse_mode="HTML"
        )
    except:
        pass
    
    # Подтверждаем покупателю
    await message.answer(
        "✅ <b>Заявка отправлена!</b>\n\n"
        "📨 Продавец свяжется с вами в ближайшее время.\n"
        "Обычно это занимает несколько часов.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    
    await state.clear()

# ========================== Поддержка ============================
@dp.message(F.text == "📞 Поддержка")
async def start_support(message: types.Message, state: FSMContext):
    await state.set_state(Support.waiting)
    await message.answer(
        "💬 <b>Напишите ваш вопрос или проблему</b>\n\n"
        "Мы перешлём ваше сообщение администратору.\n"
        "Или нажмите <b>❌ Отмена</b> для выхода.",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Support.waiting)
async def process_support(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Обращение отменено", reply_markup=get_main_keyboard())
        return
    
    # Отправляем админу
    await bot.send_message(
        ADMIN_ID,
        f"📞 <b>СООБЩЕНИЕ В ПОДДЕРЖКУ</b>\n\n"
        f"<b>👤 От:</b> {message.from_user.full_name}\n"
        f"<b>📱 Username:</b> @{message.from_user.username or 'нет'}\n"
        f"<b>🆔 ID:</b> {message.from_user.id}\n\n"
        f"<b>💬 Сообщение:</b>\n{message.text}",
        parse_mode="HTML"
    )
    
    # Подтверждаем пользователю
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "⏳ Администратор получил ваше обращение\n"
        "и ответит в ближайшее время.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    
    await state.clear()

# ========================== Webhook ==============================
async def on_startup(app):
    try:
        await bot.set_webhook(WEBHOOK_URL)
        await bot.send_message(ADMIN_ID, "🚀 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
        logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Ошибка в on_startup: {e}")

async def on_shutdown(app):
    try:
        await bot.delete_webhook()
        await bot.session.close()
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.error(f"Ошибка в on_shutdown: {e}")

def create_app():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    
    async def index(request):
        return web.Response(text="Bot is running")
    
    app.router.add_get("/", index)
    app.router.add_get("/health", index)
    
    return app

if __name__ == "__main__":
    if not TOKEN:
        logger.error("Не указан BOT_TOKEN!")
        exit(1)
    
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=PORT
    )
