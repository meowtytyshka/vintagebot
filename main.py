import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    FSInputFile,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from config import *

# ========================== Настройка логирования ========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========================== Работа с файлами =============================
def load_json(path: Path, default=[]) -> list:
    """Загрузка данных из JSON файла"""
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки {path}: {e}")
    return default if default is not None else []

def save_json(path: Path, data: list):
    """Сохранение данных в JSON файл"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Данные сохранены в {path}")
    except Exception as e:
        logger.error(f"Ошибка сохранения {path}: {e}")

# Загружаем данные
catalog: list[dict] = load_json(CATALOG_FILE)
pending: list[dict] = load_json(PENDING_FILE)

# ========================== FSM состояния ================================
class SellForm(StatesGroup):
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

# ========================== Инициализация бота ===========================
bot = Bot(token=TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========================== Клавиатуры ===================================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍️ Продать вещь")],
            [KeyboardButton(text="📦 Актуальные лоты")],
            [KeyboardButton(text="❓ Поддержка/Вопрос")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_photos_keyboard(photos_count: int) -> ReplyKeyboardMarkup:
    """Клавиатура при загрузке фото"""
    buttons = []
    if photos_count < MAX_PHOTOS:
        buttons.append([KeyboardButton(text="📸 Добавить ещё фото")])
    buttons.append([
        KeyboardButton(text="✅ Далее"),
        KeyboardButton(text="🚫 Отмена")
    ])
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )

def get_confirm_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для подтверждения заявки"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Отправить на модерацию"), KeyboardButton(text="✏️ Исправить")],
            [KeyboardButton(text="🚫 Отмена")]
        ],
        resize_keyboard=True
    )

def get_lot_keyboard(lot_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для лота"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить этот лот", callback_data=f"buy:{lot_id}")],
            [InlineKeyboardButton(text="📋 Вернуться к списку", callback_data="back_to_list")]
        ]
    )

def get_catalog_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура каталога с пагинацией"""
    if not catalog:
        return InlineKeyboardMarkup(inline_keyboard=[])
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    keyboard = []
    for lot in catalog[start_idx:end_idx]:
        title_short = lot['title'][:25] + "..." if len(lot['title']) > 25 else lot['title']
        keyboard.append([
            InlineKeyboardButton(
                text=f"🖼️ {title_short} | {lot['price']}₽",
                callback_data=f"view:{lot['id']}"
            )
        ])
    
    # Кнопки пагинации
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page:{page-1}"))
    
    total_pages = (len(catalog) - 1) // ITEMS_PER_PAGE + 1
    if page < total_pages - 1:
        navigation.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page:{page+1}"))
    
    if navigation:
        keyboard.append(navigation)
    
    keyboard.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_approve_keyboard(pending_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для админа (одобрить/отклонить)"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve:{pending_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pending_id}")
            ]
        ]
    )

# ========================== Команды ======================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    welcome_text = """
<b>👋 Добро пожаловать в Vintage Marketplace!</b>

✨ <b>Продать</b> — разместите свою винтажную вещь на продажу
🛍️ <b>Купить</b> — выберите из коллекции уникальных лотов
💬 <b>Поддержка</b> — задайте вопрос или сообщите о проблеме

👇 Выберите действие ниже:
    """
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Справка по командам"""
    help_text = """
<b>ℹ️ Справка по боту</b>

Основные возможности:
• <b>Продать вещь</b> — разместить винтажный лот на продажу
• <b>Актуальные лоты</b> — просмотр доступных к покупке вещей
• <b>Поддержка</b> — связь с администратором

<b>Команды:</b>
/start — Главное меню
/help — Эта справка
/catalog — Посмотреть каталог
/my_lots — Мои лоты (в разработке)
/cancel — Отменить текущее действие
    """
    await message.answer(help_text, reply_markup=get_main_keyboard())

@dp.message(Command("cancel"))
@dp.message(F.text.in_(["🚫 Отмена", "отмена", "Отмена"]))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена текущего действия"""
    current_state = await state.get_state()
    if current_state is None:
        return
    
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n"
        "Вы вернулись в главное меню.",
        reply_markup=get_main_keyboard()
    )

# ========================== Продать вещь =================================
@dp.message(F.text == "🛍️ Продать вещь")
async def start_selling(message: types.Message, state: FSMContext):
    """Начало процесса продажи"""
    await state.set_state(SellForm.photos)
    await state.update_data(
        photos=[],
        owner_id=message.from_user.id,
        owner_username=message.from_user.username,
        owner_full_name=message.from_user.full_name
    )
    
    await message.answer(
        "<b>📸 Шаг 1 из 8: Фотографии</b>\n\n"
        "Пришлите 1-10 фотографий вашей вещи.\n"
        "Можно отправлять по одной или альбомом.\n\n"
        "Когда все фото будут готовы — нажмите <b>✅ Далее</b>",
        reply_markup=get_photos_keyboard(0)
    )

@dp.message(SellForm.photos, F.photo)
async def process_photos(message: types.Message, state: FSMContext):
    """Обработка загружаемых фото"""
    data = await state.get_data()
    photos = data.get("photos", [])
    
    if len(photos) >= MAX_PHOTOS:
        await message.answer(
            f"⚠️ Вы уже загрузили максимум ({MAX_PHOTOS}) фото.\n"
            "Нажмите <b>✅ Далее</b> для продолжения.",
            reply_markup=get_photos_keyboard(len(photos))
        )
        return
    
    # Получаем file_id самого качественного фото
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    
    await state.update_data(photos=photos)
    
    await message.answer(
        f"✅ Фото добавлено!\n"
        f"📊 Загружено: <b>{len(photos)}/{MAX_PHOTOS}</b>\n\n"
        "Можно добавить ещё фото или нажать <b>✅ Далее</b>",
        reply_markup=get_photos_keyboard(len(photos))
    )

@dp.message(SellForm.photos, F.text == "📸 Добавить ещё фото")
async def add_more_photos(message: types.Message):
    """Запрос дополнительных фото"""
    await message.answer("📸 Отправьте следующее фото...")

@dp.message(SellForm.photos, F.text == "✅ Далее")
async def photos_next_step(message: types.Message, state: FSMContext):
    """Переход к следующему шагу после фото"""
    data = await state.get_data()
    photos = data.get("photos", [])
    
    if not photos:
        await message.answer(
            "❌ Нужно добавить хотя бы одну фотографию!",
            reply_markup=get_photos_keyboard(0)
        )
        return
    
    await state.set_state(SellForm.title)
    await message.answer(
        "<b>✏️ Шаг 2 из 8: Название вещи</b>\n\n"
        "Напишите краткое и понятное название:\n"
        "<i>Пример: «Винтажная кожаная куртка 80-х»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.title)
async def process_title(message: types.Message, state: FSMContext):
    """Обработка названия"""
    title = message.text.strip()
    if len(title) < 3:
        await message.answer("❌ Название слишком короткое. Введите ещё раз:")
        return
    
    await state.update_data(title=title)
    await state.set_state(SellForm.year)
    
    await message.answer(
        "<b>🗓️ Шаг 3 из 8: Год или возраст</b>\n\n"
        "Укажите примерный год выпуска или возраст вещи:\n"
        "<i>Пример: «1985» или «~40 лет»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.year)
async def process_year(message: types.Message, state: FSMContext):
    """Обработка года"""
    await state.update_data(year=message.text.strip())
    await state.set_state(SellForm.condition)
    
    await message.answer(
        "<b>⭐ Шаг 4 из 8: Состояние</b>\n\n"
        "Опишите состояние вещи подробно:\n"
        "<i>Пример: «Отличное состояние, мелкие потертости на манжетах, молния работает идеально»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.condition)
async def process_condition(message: types.Message, state: FSMContext):
    """Обработка состояния"""
    await state.update_data(condition=message.text.strip())
    await state.set_state(SellForm.size)
    
    await message.answer(
        "<b>📏 Шаг 5 из 8: Размеры</b>\n\n"
        "Укажите размер или габариты:\n"
        "<i>Пример: «48 размер (европейский)» или «Высота: 150см, Ширина: 80см»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.size)
async def process_size(message: types.Message, state: FSMContext):
    """Обработка размеров"""
    await state.update_data(size=message.text.strip())
    await state.set_state(SellForm.city)
    
    await message.answer(
        "<b>📍 Шаг 6 из 8: Город</b>\n\n"
        "В каком городе находится вещь?\n"
        "<i>Пример: «Москва» или «Санкт-Петербург, м. Площадь Восстания»</i>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.city)
async def process_city(message: types.Message, state: FSMContext):
    """Обработка города"""
    await state.update_data(city=message.text.strip())
    await state.set_state(SellForm.price)
    
    await message.answer(
        "<b>💰 Шаг 7 из 8: Цена</b>\n\n"
        "Укажите цену в рублях:\n"
        "<i>Пример: «5000» или «15000 руб.»</i>\n\n"
        "💡 Указывайте конечную цену, по которой готовы продать",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.price)
async def process_price(message: types.Message, state: FSMContext):
    """Обработка цены"""
    price_text = message.text.strip()
    
    # Извлекаем только цифры из текста
    price_digits = ''.join(filter(str.isdigit, price_text))
    if not price_digits:
        await message.answer("❌ Цена должна содержать цифры. Введите ещё раз:")
        return
    
    price = int(price_digits)
    if price <= 0:
        await message.answer("❌ Цена должна быть больше нуля. Введите ещё раз:")
        return
    
    await state.update_data(price=price)
    await state.set_state(SellForm.comment)
    
    await message.answer(
        "<b>💬 Шаг 8 из 8: Дополнительно</b>\n\n"
        "Добавьте комментарий если нужно:\n"
        "<i>Пример: «Есть оригинальные бирки», «Требуется химчистка»</i>\n\n"
        "Если комментарий не нужен — напишите <b>«-»</b> или <b>«нет»</b>",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(SellForm.comment)
async def process_comment(message: types.Message, state: FSMContext):
    """Обработка комментария и показ превью"""
    comment = message.text.strip()
    if comment.lower() in ['-', 'нет', 'no', 'без комментариев']:
        comment = 'Без комментариев'
    
    await state.update_data(comment=comment)
    
    # Получаем все данные
    data = await state.get_data()
    
    # Формируем превью заявки
    preview = f"""
<b>📋 ПРЕДПРОСМОТР ЗАЯВКИ</b>

<b>📸 Фото:</b> {len(data['photos'])} шт.
<b>🏷️ Название:</b> {data['title']}
<b>🗓️ Год/возраст:</b> {data['year']}
<b>⭐ Состояние:</b> {data['condition']}
<b>📏 Размер:</b> {data['size']}
<b>📍 Город:</b> {data['city']}
<b>💰 Цена:</b> {data['price']} ₽
<b>💬 Комментарий:</b> {data['comment']}

<i>Всё верно? Отправляем на модерацию?</i>
    """
    
    await state.set_state(SellForm.confirm)
    await message.answer(preview, reply_markup=get_confirm_keyboard())

@dp.message(SellForm.confirm, F.text == "✅ Отправить на модерацию")
async def submit_for_moderation(message: types.Message, state: FSMContext):
    """Отправка заявки на модерацию"""
    data = await state.get_data()
    
    # Генерируем ID для заявки
    pending_id = len(pending) + 1
    
    # Создаем заявку
    application = {
        "id": pending_id,
        "owner_id": data['owner_id'],
        "owner_username": data.get('owner_username'),
        "owner_full_name": data.get('owner_full_name'),
        "photos": data['photos'],
        "title": data['title'],
        "year": data['year'],
        "condition": data['condition'],
        "size": data['size'],
        "city": data['city'],
        "price": data['price'],
        "comment": data['comment'],
        "created_at": datetime.now().isoformat(),
        "status": "pending"
    }
    
    # Сохраняем заявку
    pending.append(application)
    save_json(PENDING_FILE, pending)
    
    # Очищаем состояние
    await state.clear()
    
    # Уведомляем пользователя
    await message.answer(
        "🎉 <b>Заявка отправлена на модерацию!</b>\n\n"
        "⏳ Обычно модерация занимает до 24 часов.\n"
        "Мы уведомим вас, когда лот будет опубликован.",
        reply_markup=get_main_keyboard()
    )
    
    # Отправляем админу
    await notify_admin_about_new_application(application)

@dp.message(SellForm.confirm, F.text == "✏️ Исправить")
async def edit_application(message: types.Message, state: FSMContext):
    """Редактирование заявки (начинаем сначала)"""
    await state.set_state(SellForm.photos)
    await message.answer(
        "🔄 Начинаем заполнение заново.\n\n"
        "<b>📸 Шаг 1: Фотографии</b>\n"
        "Пришлите фотографии вещи...",
        reply_markup=get_photos_keyboard(0)
    )

async def notify_admin_about_new_application(application: dict):
    """Уведомление админа о новой заявке"""
    try:
        # Формируем подпись для админа
        caption = f"""
<b>🆕 НОВАЯ ЗАЯВКА #{application['id']}</b>

<b>🏷️ Название:</b> {application['title']}
<b>🗓️ Год/возраст:</b> {application['year']}
<b>⭐ Состояние:</b> {application['condition']}
<b>📏 Размер:</b> {application['size']}
<b>📍 Город:</b> {application['city']}
<b>💰 Цена:</b> {application['price']} ₽
<b>💬 Комментарий:</b> {application['comment']}

<b>👤 Продавец:</b> {application.get('owner_full_name', 'Не указано')}
<b>📱 Username:</b> @{application.get('owner_username', 'отсутствует')}
<b>🆔 ID:</b> {application['owner_id']}
        """
        
        # Отправляем фото с подписью
        if application['photos']:
            media = [InputMediaPhoto(
                media=application['photos'][0], 
                caption=caption,
                parse_mode="HTML"
            )]
            
            # Добавляем остальные фото
            for photo in application['photos'][1:]:
                media.append(InputMediaPhoto(media=photo))
            
            # Отправляем медиагруппу
            messages = await bot.send_media_group(
                chat_id=ADMIN_ID,
                media=media
            )
            
            # Добавляем кнопки к последнему сообщению
            await messages[-1].reply(
                "Что делаем с заявкой?",
                reply_markup=get_admin_approve_keyboard(application['id'])
            )
        else:
            # Если нет фото, отправляем просто текст
            await bot.send_message(
                ADMIN_ID,
                caption + "\n\n⚠️ <b>В заявке нет фотографий!</b>",
                parse_mode="HTML",
                reply_markup=get_admin_approve_keyboard(application['id'])
            )
            
    except Exception as e:
        logger.error(f"Ошибка отправки заявки админу: {e}")

# ========================== Модерация (админ) =============================
@dp.callback_query(F.data.startswith("approve:"))
async def approve_application(callback: types.CallbackQuery):
    """Одобрение заявки"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 У вас нет прав для этого действия", show_alert=True)
        return
    
    pending_id = int(callback.data.split(":")[1])
    
    # Находим заявку
    application = next((app for app in pending if app["id"] == pending_id), None)
    if not application:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Создаем лот для каталога
    lot_id = max([lot.get("id", 0) for lot in catalog], default=0) + 1
    
    lot = {
        "id": lot_id,
        "title": application["title"],
        "year": application["year"],
        "condition": application["condition"],
        "size": application["size"],
        "city": application["city"],
        "price": application["price"],
        "comment": application["comment"],
        "photos": application["photos"],
        "owner_id": application["owner_id"],
        "owner_username": application.get("owner_username"),
        "created_at": datetime.now().isoformat(),
        "views": 0,
        "status": "active"
    }
    
    # Добавляем в каталог
    catalog.append(lot)
    save_json(CATALOG_FILE, catalog)
    
    # Удаляем из ожидающих
    pending[:] = [app for app in pending if app["id"] != pending_id]
    save_json(PENDING_FILE, pending)
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            application["owner_id"],
            f"🎉 <b>Ваш лот опубликован!</b>\n\n"
            f"🏷️ <b>Название:</b> {application['title']}\n"
            f"💰 <b>Цена:</b> {application['price']} ₽\n"
            f"🆔 <b>Номер лота:</b> #{lot_id}\n\n"
            f"Теперь ваш лот виден всем пользователям в каталоге!",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя: {e}")
    
    # Обновляем сообщение админа
    try:
        await callback.message.edit_caption(
            caption=callback.message.caption + "\n\n✅ <b>ОПУБЛИКОВАНО</b>",
            parse_mode="HTML"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        try:
            await callback.message.edit_text(
                text=callback.message.text + "\n\n✅ <b>ОПУБЛИКОВАНО</b>",
                parse_mode="HTML"
            )
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
    
    await callback.answer(f"✅ Лот #{lot_id} опубликован")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_application(callback: types.CallbackQuery):
    """Отклонение заявки"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 У вас нет прав для этого действия", show_alert=True)
        return
    
    pending_id = int(callback.data.split(":")[1])
    
    # Находим заявку
    application = next((app for app in pending if app["id"] == pending_id), None)
    if not application:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    # Удаляем из ожидающих
    pending[:] = [app for app in pending if app["id"] != pending_id]
    save_json(PENDING_FILE, pending)
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            application["owner_id"],
            "😔 <b>Ваша заявка отклонена</b>\n\n"
            "К сожалению, ваша заявка не прошла модерацию.\n"
            "Это могло произойти по нескольким причинам:\n"
            "• Некорректное описание\n"
            "• Некачественные фотографии\n"
            "• Нарушение правил размещения\n\n"
            "Вы можете создать новую заявку с исправлениями.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя: {e}")
    
    # Обновляем сообщение админа
    try:
        await callback.message.edit_caption(
            caption=callback.message.caption + "\n\n❌ <b>ОТКЛОНЕНО</b>",
            parse_mode="HTML"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        try:
            await callback.message.edit_text(
                text=callback.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>",
                parse_mode="HTML"
            )
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
    
    await callback.answer("❌ Заявка отклонена")

# ========================== Каталог лотов ================================
@dp.message(F.text == "📦 Актуальные лоты")
async def show_catalog(message: types.Message):
    """Показать каталог лотов"""
    if not catalog:
        await message.answer(
            "📭 <b>Каталог пуст</b>\n\n"
            "Здесь пока нет ни одного лота.\n"
            "Будьте первым, кто разместит винтажную вещь!",
            reply_markup=get_main_keyboard()
        )
        return
    
    total_items = len(catalog)
    await message.answer(
        f"📦 <b>АКТУАЛЬНЫЕ ЛОТЫ</b>\n\n"
        f"🏷️ <b>Найдено лотов:</b> {total_items}\n"
        f"👇 Выберите интересующий лот:",
        reply_markup=get_catalog_keyboard(page=0)
    )

@dp.callback_query(F.data.startswith("page:"))
async def change_catalog_page(callback: types.CallbackQuery):
    """Смена страницы в каталоге"""
    page = int(callback.data.split(":")[1])
    
    await callback.message.edit_text(
        f"📦 <b>АКТУАЛЬНЫЕ ЛОТЫ</b> (страница {page + 1})\n\n"
        f"🏷️ <b>Всего лотов:</b> {len(catalog)}\n"
        f"👇 Выберите интересующий лот:",
        reply_markup=get_catalog_keyboard(page=page),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("view:"))
async def view_lot_detail(callback: types.CallbackQuery):
    """Просмотр деталей лота"""
    lot_id = int(callback.data.split(":")[1])
    
    # Находим лот
    lot = next((item for item in catalog if item["id"] == lot_id), None)
    if not lot:
        await callback.answer("❌ Лот не найден или был удалён", show_alert=True)
        return
    
    # Увеличиваем счетчик просмотров
    lot["views"] = lot.get("views", 0) + 1
    save_json(CATALOG_FILE, catalog)
    
    # Формируем описание лота
    description = f"""
<b>🖼️ Лот #{lot['id']}</b>

<b>🏷️ Название:</b> {lot['title']}
<b>🗓️ Год/возраст:</b> {lot['year']}
<b>⭐ Состояние:</b> {lot['condition']}
<b>📏 Размер:</b> {lot['size']}
<b>📍 Город:</b> {lot['city']}
<b>💰 Цена:</b> <b>{lot['price']} ₽</b>
<b>💬 Комментарий:</b> {lot['comment']}

<b>👁️ Просмотров:</b> {lot.get('views', 0)}
    """
    
    try:
        # Удаляем старое сообщение
        await callback.message.delete()
    except:
        pass
    
    # Отправляем фото с описанием
    if lot['photos']:
        media = [InputMediaPhoto(
            media=lot['photos'][0],
            caption=description,
            parse_mode="HTML"
        )]
        
        for photo in lot['photos'][1:]:
            media.append(InputMediaPhoto(media=photo))
        
        messages = await bot.send_media_group(
            chat_id=callback.message.chat.id,
            media=media
        )
        
        # Добавляем кнопки к последнему сообщению
        await messages[-1].reply(
            "💡 Хотите купить этот лот?",
            reply_markup=get_lot_keyboard(lot['id'])
        )
    else:
        # Если нет фото (не должно быть, но на всякий случай)
        await bot.send_message(
            callback.message.chat.id,
            description + "\n\n⚠️ <b>Фотографии отсутствуют</b>",
            parse_mode="HTML",
            reply_markup=get_lot_keyboard(lot['id'])
        )
    
    await callback.answer()

@dp.callback_query(F.data == "back_to_list")
async def back_to_catalog_list(callback: types.CallbackQuery):
    """Возврат к списку лотов"""
    await callback.message.delete()
    await show_catalog(callback.message)

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.delete()
    await cmd_start(callback.message)

# ========================== Покупка лота =================================
@dp.callback_query(F.data.startswith("buy:"))
async def start_buying_process(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса покупки"""
    lot_id = int(callback.data.split(":")[1])
    
    # Находим лот
    lot = next((item for item in catalog if item["id"] == lot_id), None)
    if not lot:
        await callback.answer("❌ Лот не найден", show_alert=True)
        return
    
    # Сохраняем данные о покупке
    await state.set_state(BuyAddress.waiting)
    await state.update_data(
        lot_id=lot_id,
        lot_title=lot['title'],
        lot_price=lot['price'],
        seller_id=lot['owner_id']
    )
    
    await callback.message.answer(
        f"🛒 <b>ПОДТВЕРЖДЕНИЕ ПОКУПКИ</b>\n\n"
        f"🏷️ <b>Лот:</b> #{lot_id} - {lot['title']}\n"
        f"💰 <b>Цена:</b> {lot['price']} ₽\n"
        f"📍 <b>Город:</b> {lot['city']}\n\n"
        f"<b>📝 Чтобы завершить покупку, напишите:</b>\n"
        f"• Ваш номер телефона\n"
        f"• Предпочтительный способ связи (Telegram/WhatsApp)\n"
        f"• Город для доставки/самовывоза\n\n"
        f"<i>Пример: «+7 (999) 123-45-67, Telegram, Москва, могу забрать самовывозом»</i>\n\n"
        f"Или нажмите <b>🚫 Отмена</b>, чтобы вернуться",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(BuyAddress.waiting)
async def process_buyer_info(message: types.Message, state: FSMContext):
    """Обработка информации от покупателя"""
    buyer_info = message.text.strip()
    
    if buyer_info == "🚫 Отмена":
        await state.clear()
        await message.answer("❌ Покупка отменена", reply_markup=get_main_keyboard())
        return
    
    data = await state.get_data()
    lot_id = data.get("lot_id")
    lot_title = data.get("lot_title")
    lot_price = data.get("lot_price")
    seller_id = data.get("seller_id")
    
    # Уведомляем админа
    await bot.send_message(
        ADMIN_ID,
        f"🛒 <b>НОВАЯ ЗАЯВКА НА ПОКУПКУ!</b>\n\n"
        f"<b>🏷️ Лот:</b> #{lot_id} - {lot_title}\n"
        f"<b>💰 Цена:</b> {lot_price} ₽\n\n"
        f"<b>👤 Покупатель:</b>\n"
        f"• Имя: {message.from_user.full_name}\n"
        f"• Username: @{message.from_user.username or 'нет'}\n"
        f"• ID: {message.from_user.id}\n\n"
        f"<b>📞 Контакты покупателя:</b>\n{buyer_info}\n\n"
        f"<b>👤 Продавец:</b> ID: {seller_id}",
        parse_mode="HTML"
    )
    
    # Пытаемся уведомить продавца
    try:
        await bot.send_message(
            seller_id,
            f"🎉 <b>ПОКУПКА ВАШЕГО ЛОТА!</b>\n\n"
            f"<b>🏷️ Лот:</b> #{lot_id} - {lot_title}\n"
            f"<b>💰 Цена:</b> {lot_price} ₽\n\n"
            f"<b>👤 Покупатель:</b>\n"
            f"• Имя: {message.from_user.full_name}\n"
            f"• Username: @{message.from_user.username or 'нет'}\n\n"
            f"<b>📞 Контакты покупателя:</b>\n{buyer_info}\n\n"
            f"<i>Свяжитесь с покупателем для уточнения деталей!</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить продавца {seller_id}: {e}")
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>Не удалось уведомить продавца!</b>\n"
            f"ID продавца: {seller_id}\n"
            f"Ошибка: {str(e)}",
            parse_mode="HTML"
        )
    
    # Подтверждаем покупателю
    await message.answer(
        "✅ <b>Заявка на покупку отправлена!</b>\n\n"
        "📨 Продавец свяжется с вами в ближайшее время\n"
        "для уточнения деталей покупки.\n\n"
        "💡 <i>Рекомендуем:\n"
        "• Обсудить способ оплаты\n"
        "• Уточнить детали доставки\n"
        "• Спросить о наличии дефектов</i>",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    
    await state.clear()

# ========================== Поддержка ====================================
@dp.message(F.text == "❓ Поддержка/Вопрос")
async def start_support(message: types.Message, state: FSMContext):
    """Начало диалога с поддержкой"""
    await state.set_state(Support.waiting)
    await message.answer(
        "💬 <b>ОПИШИТЕ ВАШ ВОПРОС ИЛИ ПРОБЛЕМУ</b>\n\n"
        "Напишите подробно, что произошло или какой вопрос у вас возник.\n"
        "Мы перешлём ваше сообщение администратору.\n\n"
        "<i>Примеры:\n"
        "• «Не могу разместить лот, фотографии не загружаются»\n"
        "• «Хочу уточнить правила размещения»\n"
        "• «Нашел ошибку в описании лота»</i>\n\n"
        "Или нажмите <b>🚫 Отмена</b> для выхода",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Support.waiting)
async def process_support_message(message: types.Message, state: FSMContext):
    """Обработка сообщения в поддержку"""
    support_text = message.text.strip()
    
    if support_text == "🚫 Отмена":
        await state.clear()
        await message.answer("❌ Обращение отменено", reply_markup=get_main_keyboard())
        return
    
    # Отправляем админу
    await bot.send_message(
        ADMIN_ID,
        f"📞 <b>НОВОЕ СООБЩЕНИЕ В ПОДДЕРЖКУ</b>\n\n"
        f"<b>👤 От:</b> {message.from_user.full_name}\n"
        f"<b>📱 Username:</b> @{message.from_user.username or 'нет'}\n"
        f"<b>🆔 ID:</b> {message.from_user.id}\n\n"
        f"<b>💬 Сообщение:</b>\n{support_text}\n\n"
        f"<i>Для ответа используйте команду /reply {message.from_user.id}</i>",
        parse_mode="HTML"
    )
    
    # Подтверждаем пользователю
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "⏳ Администратор получил ваше обращение\n"
        "и ответит в ближайшее время.\n\n"
        "📧 <i>Ответ придёт вам в этот же чат</i>",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    
    await state.clear()

# ========================== Админ команды ================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Панель администратора"""
    if message.from_user.id != ADMIN_ID:
        return
    
    stats_text = f"""
<b>📊 АДМИН ПАНЕЛЬ</b>

<b>📈 Статистика:</b>
• Лотов в каталоге: {len(catalog)}
• Заявок на модерации: {len(pending)}
• Активных лотов: {len([lot for lot in catalog if lot.get('status') == 'active'])}

<b>⚙️ Команды:</b>
/stats — Подробная статистика
/pending — Показать заявки на модерации
/broadcast — Рассылка всем пользователям
/reply [id] [текст] — Ответить пользователю

<b>📦 Управление лотами:</b>
/del [id] — Удалить лот из каталога
/ban [id] — Заблокировать пользователя
    """
    
    await message.answer(stats_text, parse_mode="HTML")

@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    """Подробная статистика"""
    if message.from_user.id != ADMIN_ID:
        return
    
    active_lots = [lot for lot in catalog if lot.get('status') == 'active']
    total_views = sum(lot.get('views', 0) for lot in catalog)
    
    stats_text = f"""
<b>📊 ПОДРОБНАЯ СТАТИСТИКА</b>

<b>📦 Лоты:</b>
• Всего: {len(catalog)}
• Активные: {len(active_lots)}
• На модерации: {len(pending)}

<b>👁️ Просмотры:</b>
• Всего: {total_views}
• Среднее на лот: {total_views / len(catalog) if catalog else 0:.1f}

<b>🏙️ По городам:</b>
"""
    
    # Статистика по городам
    cities = {}
    for lot in catalog:
        city = lot.get('city', 'Не указан')
        cities[city] = cities.get(city, 0) + 1
    
    for city, count in sorted(cities.items(), key=lambda x: x[1], reverse=True)[:5]:
        stats_text += f"• {city}: {count} лотов\n"
    
    stats_text += f"\n<b>💰 Цены:</b>"
    if catalog:
        prices = [lot.get('price', 0) for lot in catalog]
        stats_text += f"""
• Минимальная: {min(prices)} ₽
• Максимальная: {max(prices)} ₽
• Средняя: {sum(prices) / len(prices):.0f} ₽
        """
    
    await message.answer(stats_text, parse_mode="HTML")

@dp.message(Command("pending"))
async def show_pending(message: types.Message):
    """Показать заявки на модерации"""
    if message.from_user.id != ADMIN_ID:
        return
    
    if not pending:
        await message.answer("📭 Нет заявок на модерации")
        return
    
    pending_text = f"<b>📋 ЗАЯВКИ НА МОДЕРАЦИИ</b>\n\nВсего: {len(pending)}\n\n"
    
    for i, app in enumerate(pending[:10], 1):
        pending_text += f"{i}. <b>#{app['id']}</b> - {app['title']}\n"
        pending_text += f"   👤 @{app.get('owner_username', 'нет')}\n"
        pending_text += f"   💰 {app['price']} ₽ | 📍 {app['city']}\n\n"
    
    if len(pending) > 10:
        pending_text += f"\n<i>И ещё {len(pending) - 10} заявок...</i>"
    
    await message.answer(pending_text, parse_mode="HTML")

@dp.message(Command("del"))
async def delete_lot(message: types.Message):
    """Удалить лот из каталога"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        lot_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Использование: /del [номер_лота]\nПример: /del 5")
        return
    
    # Ищем лот
    lot_to_delete = None
    for i, lot in enumerate(catalog):
        if lot["id"] == lot_id:
            lot_to_delete = lot
            # Удаляем из каталога
            catalog.pop(i)
            save_json(CATALOG_FILE, catalog)
            break
    
    if lot_to_delete:
        # Уведомляем владельца
        try:
            await bot.send_message(
                lot_to_delete["owner_id"],
                f"⚠️ <b>ВАШ ЛОТ УДАЛЁН АДМИНИСТРАТОРОМ</b>\n\n"
                f"🏷️ Лот: #{lot_id} - {lot_to_delete['title']}\n"
                f"💰 Цена: {lot_to_delete['price']} ₽\n\n"
                f"<i>Лот был удалён из каталога.\n"
                f"Причина: нарушение правил размещения.</i>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить владельца лота: {e}")
        
        await message.answer(f"✅ Лот #{lot_id} удалён из каталога")
    else:
        await message.answer(f"❌ Лот #{lot_id} не найден")

@dp.message(Command("reply"))
async def reply_to_user(message: types.Message):
    """Ответить пользователю"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("Использование: /reply [user_id] [сообщение]")
            return
        
        user_id = int(parts[1])
        reply_text = parts[2]
        
        # Отправляем сообщение пользователю
        await bot.send_message(
            user_id,
            f"📨 <b>ОТВЕТ ОТ АДМИНИСТРАТОРА</b>\n\n"
            f"{reply_text}\n\n"
            f"<i>Для дальнейших вопросов используйте кнопку «Поддержка»</i>",
            parse_mode="HTML"
        )
        
        await message.answer(f"✅ Ответ отправлен пользователю ID: {user_id}")
        
    except ValueError:
        await message.answer("❌ Неверный формат ID пользователя")
    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")

# ========================== Webhook настройки ============================
async def on_startup(app: web.Application):
    """Действия при запуске бота"""
    try:
        # Устанавливаем webhook
        await bot.set_webhook(
            url=WEBHOOK_URL,
            drop_pending_updates=True
        )
        
        # Отправляем уведомление админу
        await bot.send_message(
            ADMIN_ID,
            f"🚀 <b>БОТ ЗАПУЩЕН!</b>\n\n"
            f"⏰ Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}\n"
            f"📊 Статистика:\n"
            f"• Лотов: {len(catalog)}\n"
            f"• Заявок: {len(pending)}\n"
            f"🌐 Webhook: {BASE_URL}",
            parse_mode="HTML"
        )
        
        logger.info(f"Бот запущен. Webhook: {WEBHOOK_URL}")
        
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")

async def on_shutdown(app: web.Application):
    """Действия при остановке бота"""
    logger.info("Остановка бота...")
    
    try:
        # Удаляем webhook
        await bot.delete_webhook()
        await bot.session.close()
        
        # Уведомляем админа
        await bot.send_message(
            ADMIN_ID,
            "🛑 <b>БОТ ОСТАНОВЛЕН</b>\n\n"
            f"⏰ Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при остановке: {e}")

def create_app() -> web.Application:
    """Создание aiohttp приложения"""
    app = web.Application()
    
    # Регистрируем обработчики
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    ).register(app, path=WEBHOOK_PATH)
    
    # Добавляем обработчики событий
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    # Добавляем health check
    async def health_check(request):
        return web.Response(text="Bot is running")
    
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
    return app

# ========================== Запуск приложения ============================
if __name__ == "__main__":
    # Проверяем наличие токена
    if not TOKEN:
        logger.error("Не указан BOT_TOKEN!")
        exit(1)
    
    logger.info(f"Запуск бота на порту {PORT}")
    
    # Запускаем приложение
    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=PORT,
        access_log=None  # Отключаем логи aiohttp, т.к. используем свои
    )
