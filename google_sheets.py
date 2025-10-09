import gspread, datetime
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SHEET_INBOX = "09_Inbox_Ideas"
SHEET_OPS = "02_Operations_Sobranie"
SHEET_KPI = "03_Finance_KPI"
SHEET_EFF = "10_Effectiveness_Checklist"

def _open(sheet_id, creds_path):
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)

def append_inbox(sheet_id, creds_path, text, category="", due_str="", author="В.П."):
    sh = _open(sheet_id, creds_path)
    ws = sh.worksheet(SHEET_INBOX)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    ws.append_row([now, category, text, due_str, "Новая", "", author], value_input_option="USER_ENTERED")
    return True

def fetch_kpi(sheet_id, creds_path):
    sh = _open(sheet_id, creds_path)
    ws = sh.worksheet(SHEET_KPI)
    recs = ws.get_all_records()
    return recs[-1] if recs else {}

def fetch_ops_tasks(sheet_id, creds_path, limit=50):
    import datetime as dt
    sh = _open(sheet_id, creds_path)
    ws = sh.worksheet(SHEET_OPS)
    recs = ws.get_all_records()
    recs = [r for r in recs if str(r.get("Статус","")).lower() in ("в работе","не начато","ожидание","новая")]
    def to_date(s):
        try: return dt.datetime.strptime(str(s), "%Y-%m-%d").date()
        except: return dt.date.max
    recs.sort(key=lambda r: to_date(r.get("Дедлайн","")))
    return recs[:limit]

def fetch_eff_actions(sheet_id, creds_path, limit=50):
    sh = _open(sheet_id, creds_path)
    ws = sh.worksheet(SHEET_EFF)
    return ws.get_all_records()[:limit]
