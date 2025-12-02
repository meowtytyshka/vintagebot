import os
import json
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
from aiohttp.web import Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")  # ← твоя ссылка
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"  # ← ЭТА СТРОКА БЫЛА ПРОПУЩЕНА!

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

# === ВСЁ ОСТАЛЬНОЕ (состояния, хендлеры, формы) — оставь как было в предыдущем сообщении ===
# (я вставлю только ключевые части, чтобы не резало)

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

main_kb = types.ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [types.KeyboardButton(text="Продать вещь")],
    [types.KeyboardButton(text="Актуальные лоты")],
    [types.KeyboardButton(text="Поддержка")]
])

# (все хендлеры из предыдущего сообщения — /add, /del, /start, каталог, покупка, продажа, поддержка — оставь без изменений)

# === Webhook ===
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    await bot.send_message(ADMIN_ID, "Бот запущен на Render и полностью готов!\nТестируй /start, добавляй лоты через /add")

async def on_shutdown(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# Правильный webhook через SimpleRequestHandler
handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
handler.register(app, path=WEBHOOK_PATH)

# Health-check
async def health(request):
    return Response(text="OK", status=200)
app.router.add_get("/", health)

if __name__ == "__main__":
    logger.info("Запуск бота на Render...")
    web.run_app(app, host="0.0.0.0", port=PORT)
