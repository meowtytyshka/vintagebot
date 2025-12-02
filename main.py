import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiohttp import web
from aiohttp.web import Request, Response

# Настройка логирования (для Render Logs)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен и порт (Render даёт PORT автоматически)
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))  # Render использует 10000
WEBHOOK_PATH = "/webhook"  # Путь для webhook
WEBHOOK_URL = f"https://your-service.onrender.com{WEBHOOK_PATH}"  # Замени на URL Render после деплоя
ADMIN_ID = 692408588  # Твой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! ВещьБот на Render живой! 🕰\n\n"
        "Тестируем webhook: /start работает. Скоро добавим каталог и формы!"
    )
    # Уведомление тебе
    await bot.send_message(ADMIN_ID, f"Пользователь {message.from_user.id} запустил бота на Render!")

# Health-check для Render (отвечает на /, чтобы сервис не спал)
async def health_check(request: Request) -> Response:
    return Response(text="OK", status=200)

# Webhook-эндпоинт (Telegram шлёт обновления сюда)
async def webhook_handler(request: Request) -> Response:
    update = await request.json()
    # Обрабатываем обновление через Dispatcher
    await dp.feed_update(bot, update)
    return Response(text="OK", status=200)

# Функции запуска/остановки
async def on_startup(_: web.Application) -> None:
    # Устанавливаем webhook в Telegram
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Webhook установлен!")
    await bot.send_message(ADMIN_ID, "🚀 Бот ожил на Render с webhook! Готов к заявкам.")
    logger.info("Бот запущен на Render!")

async def on_shutdown(_: web.Application) -> None:
    # Удаляем webhook при остановке
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Бот остановлен.")

# Создаём aiohttp app
app = web.Application()

# Регистрируем роуты
app.router.add_post(WEBHOOK_PATH, webhook_handler)
app.router.add_get("/", health_check)  # Health-check для Render

# Добавляем хендлеры для startup/shutdown
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# Регистрируем dispatcher
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

if __name__ == "__main__":
    logger.info("Запуск бота на Render...")
    web.run_app(app, host="0.0.0.0", port=PORT)
