import os
import json
import logging
import asyncio
from pathlib import Path
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
    title = State()
    year = State()
    condition = State()
    size = State()
    city = State()
    price = State()
    comment = State()
    comment_confirm = State()

class BuyAddress(StatesGroup):
    waiting = State()

class Support(StatesGroup):
    waiting = State()

class SearchState(StatesGroup):
    waiting = State()

# ========================== Бот / диспетчер ======================
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
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

def lot_inline_kb(lot_id: int, current_page: int = None) -> InlineKeyboardMarkup:
    """Клавиатура для детального просмотра лота"""
    keyboard = [[InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy:{lot_id}")]]
    
    # Кнопки навигации если есть пагинация
    if current_page is not None:
        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Предыдущий", callback_data=f"page:{current_page-1}"))
        if current_page < len(catalog) - 1:
            nav_buttons.append(InlineKeyboardButton(text="Следующий ▶️", callback_data=f"page:{current_page+1}"))
        if nav_buttons:
            keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="📦 К каталогу", callback_data="catalog:0")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def catalog_menu_kb(page: int = 0, items_per_page: int = 1) -> InlineKeyboardMarkup:
    """Создает клавиатуру для галереи лотов с пагинацией"""
    keyboard = []
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"page:{page-1}"))
    
    if (page + 1) * items_per_page < len(catalog):
        nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"page:{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Кнопка просмотра текущего лота
    if catalog:
        current_item = catalog[min(page * items_per_page, len(catalog) - 1)]
        keyboard.append([InlineKeyboardButton(
            text="👁️ Посмотреть", 
            callback_data=f"lot:{current_item['id']}"
        )])
    
    # Кнопки фильтра, поиска и списка
    keyboard.append([
        InlineKeyboardButton(text="🎯 Фильтр", callback_data="filter_menu"),
        InlineKeyboardButton(text="🔍 Поиск", callback_data="search_menu")
    ])
    
    # Кнопка списка всех лотов
    if len(catalog) > 1:
        keyboard.append([InlineKeyboardButton(
            text="📋 Список всех лотов", 
            callback_data="list_all"
        )])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_main")])
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
    status_msg_id = data.get("status_msg_id")
    
    # Обработка альбома или одного фото
    if m.media_group_id:
        # Альбом - сохраняем все фото с порядком по message_id
        if "media_groups" not in data:
            data["media_groups"] = {}
        if m.media_group_id not in data["media_groups"]:
            data["media_groups"][m.media_group_id] = []
        data["media_groups"][m.media_group_id].append({
            "file_id": m.photo[-1].file_id,
            "message_id": m.message_id
        })
        await state.update_data(**data)
        
        # Обновляем статус после небольшой задержки, чтобы собрать все фото из альбома
        async def update_status_after_delay():
            await asyncio.sleep(1)  # Ждем 1 секунду для сбора всех фото из альбома
            data = await state.get_data()
            media_groups = data.get("media_groups", {})
            if m.media_group_id in media_groups:
                group_photos = media_groups[m.media_group_id]
                # Сортируем по message_id для правильного порядка
                sorted_group = sorted(group_photos, key=lambda x: x["message_id"])
                current_photos = data.get("photos", [])
                for p in sorted_group:
                    if p["file_id"] not in current_photos and len(current_photos) < 10:
                        current_photos.append(p["file_id"])
                await state.update_data(photos=current_photos)
                
                # Обновляем статусное сообщение
                status_msg_id = data.get("status_msg_id")
                status_text = f"📸 Фото прикреплены\n📊 Всего: *{len(current_photos)}/10*\n\nМожно добавить ещё или нажать «✅ Далее»"
                if status_msg_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=m.chat.id,
                            message_id=status_msg_id,
                            text=status_text,
                            reply_markup=photos_kb,
                            parse_mode="Markdown",
                        )
                    except:
                        pass
        
        # Запускаем обновление статуса
        asyncio.create_task(update_status_after_delay())
        return
    else:
        # Одно фото - добавляем сразу
        if len(photos) >= 10:
            if status_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=m.chat.id,
                        message_id=status_msg_id,
                        text="⚠️ Максимум 10 фото! Нажмите «✅ Далее»",
                        reply_markup=photos_kb,
                    )
                except:
                    pass
            else:
                await m.answer("⚠️ Максимум 10 фото! Нажмите «✅ Далее»", reply_markup=photos_kb)
            return
        
        photos.append(m.photo[-1].file_id)
        await state.update_data(photos=photos)
    
    # Обновляем или создаем статусное сообщение
    status_text = f"📸 Фото прикреплены\n📊 Всего: *{len(photos)}/10*\n\nМожно добавить ещё или нажать «✅ Далее»"
    
    if status_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=m.chat.id,
                message_id=status_msg_id,
                text=status_text,
                reply_markup=photos_kb,
                parse_mode="Markdown",
            )
        except:
            msg = await m.answer(status_text, reply_markup=photos_kb, parse_mode="Markdown")
            await state.update_data(status_msg_id=msg.message_id)
    else:
        msg = await m.answer(status_text, reply_markup=photos_kb, parse_mode="Markdown")
        await state.update_data(status_msg_id=msg.message_id)

@dp.message(Form.photos, F.text == "➕ Добавить ещё фото")
async def photos_more(m: types.Message, state: FSMContext):
    await m.answer("📸 Пришлите фото!", reply_markup=photos_kb)

@dp.message(Form.photos, F.text == "✅ Далее")
async def photos_next(m: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    
    # Обрабатываем медиа-группы если есть
    if "media_groups" in data:
        for group_id, group_photos in data["media_groups"].items():
            # Сортируем по message_id (они идут по порядку) и добавляем в правильном порядке
            sorted_photos = sorted(group_photos, key=lambda x: x["message_id"])
            for p in sorted_photos:
                if p["file_id"] not in photos and len(photos) < 10:
                    photos.append(p["file_id"])
        await state.update_data(photos=photos)
        data = await state.get_data()
        photos = data.get("photos", [])
    
    if not photos:
        await m.answer("❌ Нужно хотя бы одно фото!", reply_markup=photos_kb)
        return
    
    # Удаляем статусное сообщение если есть
    status_msg_id = data.get("status_msg_id")
    if status_msg_id:
        try:
            await bot.delete_message(chat_id=m.chat.id, message_id=status_msg_id)
        except:
            pass
    
    # Убираем промежуточное подтверждение, сразу переходим к названию
    await state.set_state(Form.title)
    await state.update_data(status_msg_id=None, media_groups=None)
    await m.answer("✏️ Напишите название вещи", reply_markup=cancel_kb)


# ----- остальные поля формы (аналогично) -----
@dp.message(Form.title)
async def form_title(m: types.Message, state: FSMContext):
    title = m.text.strip()
    await state.update_data(title=title)
    await state.set_state(Form.year)
    await m.answer("🗓️ Укажите год выпуска или возраст\nПример: «1985» или «~40 лет»", reply_markup=cancel_kb)


# ----- год -----
@dp.message(Form.year)
async def form_year(m: types.Message, state: FSMContext):
    year = m.text.strip()
    await state.update_data(year=year)
    await state.set_state(Form.condition)
    await m.answer("⭐ Опишите состояние вещи\nПример: «Отличное, царапин нет»", reply_markup=cancel_kb)

# ----- состояние -----
@dp.message(Form.condition)
async def form_condition(m: types.Message, state: FSMContext):
    cond = m.text.strip()
    await state.update_data(condition=cond)
    await state.set_state(Form.size)
    await m.answer("📏 Укажите размер (габариты)\nПример: «200×90×90 см»", reply_markup=cancel_kb)

# ----- размер -----
@dp.message(Form.size)
async def form_size(m: types.Message, state: FSMContext):
    size = m.text.strip()
    await state.update_data(size=size)
    await state.set_state(Form.city)
    await m.answer("📍 Укажите город\nПример: «Москва»", reply_markup=cancel_kb)

# ----- город -----
@dp.message(Form.city)
async def form_city(m: types.Message, state: FSMContext):
    city = m.text.strip()
    await state.update_data(city=city)
    await state.set_state(Form.price)
    await m.answer("💰 Укажите чистую цену продажи в рублях\nПример: «5000»", reply_markup=cancel_kb)

# ----- цена -----
@dp.message(Form.price)
async def form_price(m: types.Message, state: FSMContext):
    price = m.text.strip()
    await state.update_data(price=price)
    await state.set_state(Form.comment)
    await m.answer(
        "💬 Добавьте дополнительный комментарий (по желанию)\n"
        "Или напишите «-» если нет",
        reply_markup=cancel_kb,
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
        f"Название: {data['title']}\n"
        f"Год/возраст: {data['year']}\n"
        f"Состояние: {data['condition']}\n"
        f"Размер: {data['size']}\n"
        f"Цена: {data['price']} ₽\n"
        f"Город: {data['city']}\n"
        f"Комментарий: {data['comment']}\n\n"
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
        f"Название: *{request_item['title']}*\n"
        f"Год/возраст: {request_item['year']}\n"
        f"Состояние: {request_item['condition']}\n"
        f"Размер: {request_item['size']}\n"
        f"Цена: {request_item['price']} ₽\n"
        f"Город: {request_item['city']}\n"
        f"Комментарий: {request_item['comment']}\n\n"
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

    # Обновляем сообщение админу
    try:
        if call.message.caption:
            new_caption = call.message.caption + f"\n\n✅ *ОПУБЛИКОВАНО* как лот №{lot_id}"
            await call.message.edit_caption(
                caption=new_caption,
                parse_mode="Markdown",
                reply_markup=None,
            )
        else:
            await call.message.edit_text(
                text=call.message.text + f"\n\n✅ *ОПУБЛИКОВАНО* как лот №{lot_id}",
                parse_mode="Markdown",
                reply_markup=None,
            )
    except Exception as e:
        logger.exception(f"Ошибка обновления сообщения: {e}")
    
    await call.answer("✅ Опубликовано!")

    # Уведомление юзеру
    try:
        await bot.send_message(
            item["owner_id"],
            f"🎉 Ваша заявка *одобрена*!\n\n"
            f"🆔 Лот №{lot_id} опубликован в каталоге!",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception(f"Не удалось уведомить владельца: {e}")
    
    # Уведомление админу
    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ Заявка #{pending_id} одобрена и опубликована как лот №{lot_id}",
        )
    except Exception as e:
        logger.exception(f"Ошибка отправки уведомления админу: {e}")

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

    # Обновляем сообщение админу
    try:
        if call.message.caption:
            new_caption = call.message.caption + "\n\n❌ *ОТКЛОНЕНО*"
            await call.message.edit_caption(
                caption=new_caption,
                parse_mode="Markdown",
                reply_markup=None,
            )
        else:
            await call.message.edit_text(
                text=call.message.text + "\n\n❌ *ОТКЛОНЕНО*",
                parse_mode="Markdown",
                reply_markup=None,
            )
    except Exception as e:
        logger.exception(f"Ошибка обновления сообщения: {e}")
    
    await call.answer("❌ Отклонено")

    # Уведомление юзеру
    try:
        await bot.send_message(
            item["owner_id"],
            "😔 К сожалению, ваша заявка отклонена модератором.",
        )
    except Exception as e:
        logger.exception(f"Не удалось уведомить владельца: {e}")
    
    # Уведомление админу
    try:
        await bot.send_message(
            ADMIN_ID,
            f"❌ Заявка #{pending_id} отклонена",
        )
    except Exception as e:
        logger.exception(f"Ошибка отправки уведомления админу: {e}")

# ========================== Каталог ==============================
@dp.message(F.text == "📦 Актуальные лоты")
async def user_catalog(m: types.Message):
    if not catalog:
        await m.answer("📭 Сейчас лотов нет.\n\nОбновите позже!", reply_markup=main_kb)
        return
    
    # Показываем первый лот как карточку
    await show_catalog_page(m.chat.id, 0)

async def show_catalog_page(chat_id: int, page: int):
    """Показывает страницу каталога с лотом"""
    if not catalog or page < 0 or page >= len(catalog):
        return
    
    item = catalog[page]
    
    # Формируем красивое описание карточки
    caption = (
        f"📦 *ВИНТАЖНАЯ ГАЛЕРЕЯ*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{item['title'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {item['year']}\n"
        f"⭐ {item['condition']}\n"
        f"📏 {item['size']}\n"
        f"📍 {item['city']}\n\n"
        f"💰 *{item['price']} ₽*\n\n"
    )
    
    if item.get('comment') and item['comment'] != '-':
        caption += f"💬 {item['comment']}\n\n"
    
    caption += f"📄 Страница {page + 1} из {len(catalog)}"
    
    # Отправляем фото с описанием
    try:
        media = [InputMediaPhoto(media=item["photos"][0], caption=caption, parse_mode="Markdown")]
        for p in item["photos"][1:]:
            media.append(InputMediaPhoto(media=p))
        
        msgs = await bot.send_media_group(chat_id=chat_id, media=media)
        await msgs[-1].reply(
            "👇 Выберите действие:",
            reply_markup=catalog_menu_kb(page=page)
        )
    except Exception as e:
        logger.exception(f"Ошибка отправки карточки лота: {e}")

@dp.callback_query(F.data.startswith("lot:"))
async def show_lot(call: types.CallbackQuery):
    lot_id = int(call.data.split(":")[1])
    item = next((x for x in catalog if x["id"] == lot_id), None)
    if not item:
        await call.answer("❌ Лот удалён", show_alert=True)
        return

    # Находим индекс текущего лота для пагинации
    current_page = next((i for i, x in enumerate(catalog) if x["id"] == lot_id), 0)

    # Красивое оформление детальной карточки
    caption = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{item['title'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Год/возраст:* {item['year']}\n"
        f"⭐ *Состояние:* {item['condition']}\n"
        f"📏 *Размер:* {item['size']}\n"
        f"📍 *Город:* {item['city']}\n\n"
        f"💰 *{item['price']} ₽*\n\n"
    )
    
    if item.get('comment') and item['comment'] != '-':
        caption += f"💬 *Описание:*\n{item['comment']}\n\n"
    
    caption += f"🆔 Лот №{item['id']}"
    
    try:
        # Удаляем старое сообщение
        try:
            await call.message.delete()
        except:
            pass
        
        # Отправляем медиа-группу с фото
        media = [InputMediaPhoto(media=item["photos"][0], caption=caption, parse_mode="Markdown")]
        for p in item["photos"][1:]:
            media.append(InputMediaPhoto(media=p))
        
        msgs = await bot.send_media_group(chat_id=call.message.chat.id, media=media)
        await msgs[-1].reply(
            "💡 Выберите действие:",
            reply_markup=lot_inline_kb(lot_id, current_page=current_page)
        )
    except Exception as e:
        logger.exception(f"Ошибка показа лота: {e}")
        await call.answer("❌ Ошибка загрузки лота", show_alert=True)
    
    await call.answer()

@dp.callback_query(F.data.startswith("page:"))
async def show_page(call: types.CallbackQuery):
    """Обработка пагинации каталога"""
    page = int(call.data.split(":")[1])
    
    if page < 0 or page >= len(catalog):
        await call.answer("❌ Страница не найдена", show_alert=True)
        return
    
    try:
        # Удаляем старое сообщение
        await call.message.delete()
    except:
        pass
    
    await show_catalog_page(call.message.chat.id, page)
    await call.answer()

@dp.callback_query(F.data.startswith("catalog:"))
async def back_to_catalog(call: types.CallbackQuery):
    """Возврат к каталогу"""
    page = int(call.data.split(":")[1])
    
    try:
        await call.message.delete()
    except:
        pass
    
    await show_catalog_page(call.message.chat.id, page)
    await call.answer()

@dp.callback_query(F.data == "filter_menu")
async def filter_menu(call: types.CallbackQuery):
    """Меню фильтров"""
    keyboard = [
        [InlineKeyboardButton(text="📍 По городу", callback_data="filter:city")],
        [InlineKeyboardButton(text="💰 По цене", callback_data="filter:price")],
        [InlineKeyboardButton(text="📅 По году", callback_data="filter:year")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="catalog:0")]
    ]
    
    try:
        await call.message.edit_text(
            "🎯 *ФИЛЬТРЫ*\n\nВыберите параметр для фильтрации:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    except:
        await call.message.answer(
            "🎯 *ФИЛЬТРЫ*\n\nВыберите параметр для фильтрации:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    await call.answer()

@dp.callback_query(F.data == "search_menu")
async def search_menu(call: types.CallbackQuery, state: FSMContext):
    """Меню поиска"""
    await state.set_state(SearchState.waiting)
    
    try:
        await call.message.edit_text(
            "🔍 *ПОИСК ПО КАТАЛОГУ*\n\n"
            "Введите название или ключевое слово для поиска:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_search")]]
            )
        )
    except:
        await call.message.answer(
            "🔍 *ПОИСК ПО КАТАЛОГУ*\n\n"
            "Введите название или ключевое слово для поиска:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_search")]]
            )
        )
    await call.answer()

@dp.callback_query(F.data == "cancel_search")
async def cancel_search(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.delete()
    except:
        pass
    await call.answer("Поиск отменён")

@dp.message(SearchState.waiting)
async def handle_search(m: types.Message, state: FSMContext):
    """Обработка поискового запроса"""
    # Проверяем отмену
    if m.text == "❌ Отмена":
        await state.clear()
        await m.answer("Поиск отменён.", reply_markup=main_kb)
        return
    
    search_query = m.text.lower().strip()
    
    if not search_query:
        await m.answer("❌ Введите поисковый запрос.", reply_markup=main_kb)
        await state.clear()
        return
    
    # Поиск по названию, году, состоянию, городу
    found = []
    for i, item in enumerate(catalog):
        if (search_query in item['title'].lower() or
            search_query in str(item['year']).lower() or
            search_query in item['condition'].lower() or
            search_query in item['city'].lower() or
            (item.get('comment') and search_query in item['comment'].lower())):
            found.append(i)
    
    if not found:
        await m.answer(
            f"❌ По запросу «{m.text}» ничего не найдено.\n\n"
            "Попробуйте другой запрос или используйте фильтры.",
            reply_markup=main_kb
        )
        await state.clear()
        return
    
    # Показываем первый найденный лот
    await show_catalog_page(m.chat.id, found[0])
    await m.answer(
        f"✅ Найдено лотов: {len(found)}\n"
        f"Показан первый результат. Используйте навигацию для просмотра остальных.",
        reply_markup=main_kb
    )
    await state.clear()

@dp.callback_query(F.data == "list_all")
async def list_all_lots(call: types.CallbackQuery):
    """Показать список всех лотов"""
    if not catalog:
        await call.answer("📭 Лотов нет", show_alert=True)
        return
    
    # Создаем список лотов (максимум 50)
    keyboard = []
    for item in catalog[:50]:
        keyboard.append([InlineKeyboardButton(
            text=f"{item['title'][:35]}... | {item['price']}₽",
            callback_data=f"lot:{item['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="🔙 К каталогу", callback_data="catalog:0")])
    
    try:
        await call.message.edit_text(
            f"📋 *СПИСОК ВСЕХ ЛОТОВ* ({len(catalog)} шт)\n\n"
            "Выберите лот для просмотра:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    except:
        await call.message.answer(
            f"📋 *СПИСОК ВСЕХ ЛОТОВ* ({len(catalog)} шт)\n\n"
            "Выберите лот для просмотра:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    await call.answer()

@dp.callback_query(F.data.startswith("filter:"))
async def handle_filter(call: types.CallbackQuery):
    """Обработка фильтров"""
    filter_type = call.data.split(":")[1]
    
    if filter_type == "city":
        # Получаем список уникальных городов
        cities = sorted(set(item['city'] for item in catalog))
        keyboard = []
        for city in cities[:10]:  # Максимум 10 городов
            keyboard.append([InlineKeyboardButton(
                text=f"📍 {city}",
                callback_data=f"filter_city:{city}"
            )])
        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="filter_menu")])
        
        await call.message.edit_text(
            "📍 *ФИЛЬТР ПО ГОРОДУ*\n\nВыберите город:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    elif filter_type == "price":
        keyboard = [
            [InlineKeyboardButton(text="💰 До 5000₽", callback_data="filter_price:0:5000")],
            [InlineKeyboardButton(text="💰 5000-10000₽", callback_data="filter_price:5000:10000")],
            [InlineKeyboardButton(text="💰 10000-20000₽", callback_data="filter_price:10000:20000")],
            [InlineKeyboardButton(text="💰 От 20000₽", callback_data="filter_price:20000:999999")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="filter_menu")]
        ]
        await call.message.edit_text(
            "💰 *ФИЛЬТР ПО ЦЕНЕ*\n\nВыберите диапазон:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    elif filter_type == "year":
        await call.answer(
            "📅 Фильтр по году будет добавлен в следующем обновлении!",
            show_alert=True
        )
    
    await call.answer()

@dp.callback_query(F.data.startswith("filter_city:"))
async def apply_city_filter(call: types.CallbackQuery):
    """Применение фильтра по городу"""
    city = call.data.split(":", 1)[1]
    filtered = [i for i, item in enumerate(catalog) if item['city'] == city]
    
    if not filtered:
        await call.answer(f"❌ Лотов в городе {city} не найдено", show_alert=True)
        return
    
    # Показываем первый отфильтрованный лот
    await call.message.delete()
    await show_catalog_page(call.message.chat.id, filtered[0])
    await call.answer()

@dp.callback_query(F.data.startswith("filter_price:"))
async def apply_price_filter(call: types.CallbackQuery):
    """Применение фильтра по цене"""
    _, min_price, max_price = call.data.split(":")
    min_price = int(min_price)
    max_price = int(max_price)
    
    filtered = []
    for i, item in enumerate(catalog):
        try:
            price = int(''.join(filter(str.isdigit, str(item['price']))))
            if min_price <= price <= max_price:
                filtered.append(i)
        except:
            continue
    
    if not filtered:
        await call.answer("❌ Лотов в этом диапазоне цен не найдено", show_alert=True)
        return
    
    # Показываем первый отфильтрованный лот
    try:
        await call.message.delete()
    except:
        pass
    await show_catalog_page(call.message.chat.id, filtered[0])
    await call.answer()

@dp.callback_query(F.data.startswith("sold:"))
async def mark_as_sold(call: types.CallbackQuery):
    """Пометить лот как проданный и удалить из каталога"""
    if call.from_user.id != ADMIN_ID:
        await call.answer("🚫 Нет прав.", show_alert=True)
        return
    
    lot_id = int(call.data.split(":")[1])
    global catalog
    
    # Удаляем лот из каталога
    before = len(catalog)
    catalog = [l for l in catalog if l["id"] != lot_id]
    save_catalog()
    
    if len(catalog) < before:
        await call.message.edit_text(
            call.message.text + f"\n\n✅ *ЛОТ ПРОДАН И УДАЛЁН ИЗ КАТАЛОГА*",
            parse_mode="Markdown",
            reply_markup=None,
        )
        await call.answer("✅ Лот удалён из каталога")
    else:
        await call.answer("❌ Лот не найден", show_alert=True)

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    try:
        await call.message.delete()
    except:
        pass
    await bot.send_message(
        call.message.chat.id,
        "🏠 *Главное меню*",
        reply_markup=main_kb,
        parse_mode="Markdown"
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
        reply_markup=cancel_kb,
    )
    await call.answer()

@dp.message(BuyAddress.waiting)
async def buy_address(m: types.Message, state: FSMContext):
    # Проверяем отмену
    if m.text == "❌ Отмена":
        await state.clear()
        await m.answer("Действие отменено.", reply_markup=main_kb)
        return
    
    data = await state.get_data()
    lot_id = data["buy_lot_id"]
    item = next((x for x in catalog if x["id"] == lot_id), None)

    # Клавиатура для админа с кнопкой удаления лота
    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продано (удалить лот)", callback_data=f"sold:{lot_id}")],
        ]
    )

    await bot.send_message(
        ADMIN_ID,
        f"🛒 *НОВАЯ ЗАЯВКА НА ПОКУПКУ*\n\n"
        f"🆔 Лот №{lot_id} ({item['title'] if item else 'UNKNOWN'})\n"
        f"💰 {item['price'] if item else 'N/A'} ₽\n\n"
        f"👤 @{m.from_user.username or 'без username'} (ID: {m.from_user.id})\n\n"
        f"📞 *Контакты*:\n{m.text}",
        parse_mode="Markdown",
        reply_markup=admin_kb,
    )

    await state.clear()
    await m.answer(
        "✅ Заявка отправлена!\n"
        "📨 С вами свяжется продавец в ближайшее время.",
        reply_markup=main_kb,
    )

# ========================== Поддержка ============================
@dp.message(F.text == "📞 Поддержка")
async def user_support(m: types.Message, state: FSMContext):
    await state.set_state(Support.waiting)
    await m.answer(
        "💬 Напишите ваш вопрос или проблему\n"
        "📤 Перешлём администратору",
        reply_markup=cancel_kb,
    )

@dp.message(Support.waiting)
async def support_message(m: types.Message, state: FSMContext):
    # Проверяем отмену первым делом
    if m.text == "❌ Отмена":
        await state.clear()
        await m.answer("Действие отменено.", reply_markup=main_kb)
        return
    
    if m.from_user.id == ADMIN_ID:
        await state.clear()
        return
    
    # Отправляем админу
    try:
        await bot.send_message(
            ADMIN_ID,
            f"📞 *СООБЩЕНИЕ В ПОДДЕРЖКУ*\n\n"
            f"👤 @{m.from_user.username or 'без username'} (ID: {m.from_user.id})\n\n"
            f"{m.text}",
            parse_mode="Markdown",
        )
        await m.answer("✅ Сообщение отправлено!\n⏳ Ожидайте ответа.", reply_markup=main_kb)
    except Exception as e:
        logger.exception(f"Ошибка отправки сообщения в поддержку: {e}")
        await m.answer("❌ Ошибка отправки сообщения. Попробуйте позже.", reply_markup=main_kb)
    
    await state.clear()


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
