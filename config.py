import os
from pathlib import Path

# Пути к файлам
BASE_DIR = Path(__file__).parent
CATALOG_FILE = BASE_DIR / "data" / "catalog.json"
PENDING_FILE = BASE_DIR / "data" / "pending.json"
USERS_FILE = BASE_DIR / "data" / "users.json"

# Создаем директории если их нет
for path in [CATALOG_FILE.parent, BASE_DIR / "logs"]:
    path.mkdir(exist_ok=True, parents=True)

# Настройки бота
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "692408588"))

# Webhook настройки (для Render)
PORT = int(os.getenv("PORT", 10000))
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vintagebot-97dr.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

# Настройки бота
MAX_PHOTOS = 10
ITEMS_PER_PAGE = 8  # Количество лотов на странице
