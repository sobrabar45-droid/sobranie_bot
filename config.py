import os
from dotenv import load_dotenv
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
DEFAULT_AUTHOR = os.getenv("AUTHOR_NAME", "В.П.")
TZ = os.getenv("TZ", "Europe/Moscow")
