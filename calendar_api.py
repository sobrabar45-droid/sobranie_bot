from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime
from typing import List, Dict

def _cal(creds_path: str):
    scopes = ["https://www.googleapis.com/auth/calendar"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    return build("calendar", "v3", credentials=creds)

def list_events_between(calendar_id: str, creds_path: str, dt_from: datetime, dt_to: datetime) -> List[Dict]:
    service = _cal(creds_path)
    events = service.events().list(
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
