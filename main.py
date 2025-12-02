import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook import aiosqlite
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import aiohttp.web

# Настройка логирования (чтобы видеть ошибки в Render Logs)
logging.basicConfig(level=logging.INFO)

# Токен и порт (Render даёт PORT автоматически)
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))  # Render использует 10000
ADMIN_ID = 692408588  # Твой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! ВещьБот на Render с webhooks — живой! 🕰\n\n"
        "Тестируем: /add для лотов, /start для меню. Скоро полный каталог!"
    )
    # Уведомление тебе
    await bot.send_message(ADMIN_ID, f"Пользователь {message.from_user.id} запустил бота!")

# Health-check для Render (отвечает на /, чтобы сервис не спал)
async def health_check(request: web.Request):
    return web.Response(text="OK", status=200)

# Главная функция
async def on_startup():
    print("Бот запущен на Render с webhooks!")
    await bot.send_message(ADMIN_ID, "🚀 Бот ожил на Render! Готов к заявкам.")

async def on_shutdown():
    print("Бот останавливается...")
    await bot.session.close()

# Создаём app для aiohttp
app = web.Application()
setup_application(app, dp, bot=bot)

# Добавляем health-check
app.router.add_get("/", health_check)

if __name__ == "__main__":
    # Запуск с webhook (автоматически на PORT)
    web.run_app(app, host="0.0.0.0", port=PORT)
