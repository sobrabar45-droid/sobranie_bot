import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import pytz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# ---------- внутреннее: подключение к Google Calendar ----------
def _service(creds_path: str):
    scopes = ["https://www.googleapis.com/auth/calendar"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    return build("calendar", "v3", credentials=creds)


# ---------- чтение событий за интервал ----------
def list_events_between(calendar_id: str, creds_path: str,
                        dt_from: datetime, dt_to: datetime) -> List[Dict]:
    svc = _service(creds_path)
    events = svc.events().list(
        calendarId=calendar_id,
        timeMin=dt_from.isoformat(),
        timeMax=dt_to.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])
    return events


def pretty_events(events: List[Dict]) -> str:
    def start_str(e):
        st = e.get("start", {})
        return st.get("dateTime") or st.get("date") or "?"
    lines = []
    for e in events:
        lines.append(f"- {start_str(e)} — {e.get('summary', '(без названия)')}")
    return "\n".join(lines) if lines else "—"


# ---------- создание события ----------
def add_event(summary: str,
              minutes: int = 60,
              start_dt: Optional[datetime] = None,
              description: str = "",
              calendar_id: Optional[str] = None,
              creds_path: Optional[str] = None) -> Dict:
    """
    Создать событие в календаре.
    - summary: заголовок
    - minutes: длительность (мин)
    - start_dt: datetime с tz; если None → завтра 06:00 по TZ из окружения
    - description: описание
    - calendar_id: по умолчанию берём из ENV CALENDAR_ID
    - creds_path: по умолчанию берём из ENV GOOGLE_CREDENTIALS_JSON
    Возвращает словарь созданного события (в т.ч. htmlLink).
    """
    if calendar_id is None:
        calendar_id = os.getenv("CALENDAR_ID", "").strip()
    if not calendar_id:
        raise RuntimeError("CALENDAR_ID is not set in environment")

    if creds_path is None:
        creds_path = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not creds_path:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON is not set in environment")

    tz_name = os.getenv("TZ", "Europe/Berlin")
    tz = pytz.timezone(tz_name)

    # если start_dt не задан — завтра 06:00 локального TZ
    if start_dt is None:
        now = datetime.now(tz)
        start_dt = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

    # убедимся, что у даты есть tzinfo
    if start_dt.tzinfo is None:
        start_dt = tz.localize(start_dt)

    end_dt = start_dt + timedelta(minutes=minutes)

    body = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }

    svc = _service(creds_path)
    created = svc.events().insert(calendarId=calendar_id, body=body).execute()
    return created
