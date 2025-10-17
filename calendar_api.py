import os
import json
import datetime as dt
from typing import List, Dict, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dateutil import tz as _tz

# Читаем дефолты из окружения (можно переопределять аргументами функций)
CALENDAR_ID = os.getenv("CALENDAR_ID", "").strip()
CREDS_INPUT = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
TZ = os.getenv("TZ", "Europe/Berlin")


def _load_credentials(creds_input: str) -> Credentials:
    """
    Принимает либо путь к JSON-файлу сервис-аккаунта,
    либо «цельный» JSON-текст (как в Render Environment).
    Возвращает объект Credentials.
    """
    scopes = ["https://www.googleapis.com/auth/calendar"]
    if not creds_input:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON is empty")

    # Если это путь к существующему файлу — читаем с диска
    if os.path.exists(creds_input):
        return Credentials.from_service_account_file(creds_input, scopes=scopes)

    # Иначе считаем, что это цельный JSON
    try:
        info = json.loads(creds_input)
        return Credentials.from_service_account_info(info, scopes=scopes)
    except Exception as e:
        raise RuntimeError(f"Cannot parse GOOGLE_CREDENTIALS_JSON: {e}")


def _service(creds_input: Optional[str] = None):
    creds = _load_credentials(creds_input or CREDS_INPUT)
    return build("calendar", "v3", credentials=creds)


def _to_rfc3339(dt_obj: dt.datetime) -> str:
    """
    Преобразует datetime → RFC3339 в UTC с Z на конце.
    Если datetime «наивный» — считаем, что он в локальной TZ из переменной TZ.
    """
    if dt_obj.tzinfo is None:
        local = _tz.gettz(TZ or "Europe/Berlin")
        dt_obj = dt_obj.replace(tzinfo=local)
    return dt_obj.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def list_events_between(
    calendar_id: str,
    creds_input: str,
    dt_from: dt.datetime,
    dt_to: dt.datetime,
    max_results: int = 100,
) -> List[Dict]:
    """
    Возвращает события календаря в интервале [dt_from, dt_to).
    Параметры:
      - calendar_id: ID календаря (…@group.calendar.google.com)
      - creds_input: путь к файлу или «цельный» JSON сервис-аккаунта
    """
    svc = _service(creds_input)
    time_min = _to_rfc3339(dt_from)
    time_max = _to_rfc3339(dt_to)

    resp = (
        svc.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        )
        .execute()
    )
    return resp.get("items", [])


def add_event(
    summary: str,
    minutes: int = 60,
    start_dt: Optional[dt.datetime] = None,
    description: str = "",
    calendar_id: Optional[str] = None,
    creds_input: Optional[str] = None,
) -> Dict:
    """
    Создаёт событие в календаре.
    Если start_dt не указан — создаёт завтра в 06:00 по TZ.
    Можно передать calendar_id/creds_input; иначе берутся из ENV.
    """
    cid = (calendar_id or CALENDAR_ID).strip()
    if not cid:
        raise RuntimeError("CALENDAR_ID is not set")

    svc = _service(creds_input or CREDS_INPUT)

    # Старт по умолчанию — завтра 06:00 локальной TZ
    local_tz = _tz.gettz(TZ or "Europe/Berlin")
    now_local = dt.datetime.now(local_tz)
    if start_dt is None:
        start_dt = (now_local + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    elif start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=local_tz)

    end_dt = start_dt + dt.timedelta(minutes=int(minutes))

    body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": str(start_dt.tzinfo) if start_dt.tzinfo else TZ,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": str(end_dt.tzinfo) if end_dt.tzinfo else TZ,
        },
    }

    created = svc.events().insert(calendarId=cid, body=body).execute()
    return created


def pretty_events(events: List[Dict]) -> str:
    """
    Читабельный список событий: дата/время — заголовок (описание).
    """
    if not events:
        return "—"

    lines = []
    for e in events:
        start = e.get("start", {})
        dt_str = start.get("dateTime") or start.get("date") or ""
        summary = e.get("summary", "(без названия)")
        desc = e.get("description", "")

        # Укоротим описание
        if desc:
            desc = desc.strip().replace("\n", " ")
            if len(desc) > 90:
                desc = desc[:90] + "…"

        # Красиво дата/время
        try:
            # Пытаемся распарсить dateTime
            when = dt.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            # в локальной TZ
            local = when.astimezone(_tz.gettz(TZ or "Europe/Berlin"))
            show = local.strftime("%d.%m %H:%M")
        except Exception:
            # Если был all-day (date без времени)
            show = dt_str

        if desc:
            lines.append(f"• {show} — {summary} ({desc})")
        else:
            lines.append(f"• {show} — {summary}")

    return "\n".join(lines)
