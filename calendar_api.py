# calendar_api.py
import os
import json
import base64
from datetime import datetime, timedelta
from dateutil import tz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TZ = os.getenv("TZ", "Europe/Berlin")  # можно поставить твою зону

def _creds_from_env():
    src = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not src:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON is empty")

    if src.startswith("{"):
        info = json.loads(src)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    # путь к файлу
    try:
        with open(src, "r", encoding="utf-8") as f:
            info = json.load(f)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        # возможно base64
        try:
            decoded = base64.b64decode(src).decode("utf-8")
            info = json.loads(decoded)
            return Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            raise RuntimeError("GOOGLE_CREDENTIALS_JSON is not a valid path/json/base64") from e

def _service():
    creds = _creds_from_env()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

def add_event(summary: str, minutes: int, start_dt: datetime | None = None, description: str = "") -> dict:
    """
    Создаёт событие продолжительностью minutes в календаре CALENDAR_ID.
    Если start_dt не передан — ставим на завтра 06:00 локального TZ.
    """
    calendar_id = os.getenv("CALENDAR_ID", "").strip()
    if not calendar_id:
        raise RuntimeError("CALENDAR_ID env is empty")

    local = tz.gettz(TZ)

    if start_dt is None:
        # завтра в 06:00 локального времени
        now_local = datetime.now(local)
        start_dt = (now_local + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

    end_dt = start_dt + timedelta(minutes=minutes)

    # в RFC3339
    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }

    service = _service()
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created
