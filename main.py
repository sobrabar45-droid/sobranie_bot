import os
import logging
import urllib.parse
import datetime as dt
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_TOKEN, GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, DEFAULT_AUTHOR, TZ
from google_sheets import append_inbox, fetch_ops_tasks, fetch_kpi, fetch_eff_actions
from logic import parse_due, pick_next
from gpt_brain import gpt_analyze_free, gpt_analyze_status, gpt_continue_status
from calendar_api import add_event

logging.basicConfig(level=logging.INFO)

# ====== UI ТЕКСТЫ ======
BTN_CAPTURE   = "➕ Внести"
BTN_TODAY     = "📅 Сегодня"
BTN_WEEK      = "🗓 Неделя"
BTN_MONTH     = "📆 Месяц"
BTN_CALENDAR  = "📎 Календарь"
BTN_FOCUS     = "🎯 Фокус"
BTN_KPI       = "📈 Статус KPI"
BTN_MENU      = "Меню"

MAIN_KB = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CAPTURE), KeyboardButton(BTN_TODAY), KeyboardButton(BTN_WEEK)],
     [KeyboardButton(BTN_MONTH), KeyboardButton(BTN_CALENDAR), KeyboardButton(BTN_FOCUS)],
     [KeyboardButton(BTN_KPI)]],
    resize_keyboard=True
)

# Флаг режима «жду следующего текста как задачу»
AWAITING_CAPTURE_FLAG = "awaiting_capture"

HELP = ("Кнопки доступны внизу. Могу:\n"
        f"• {BTN_CAPTURE} — быстро записать задачу (без /add)\n"
        f"• {BTN_TODAY}/{BTN_WEEK}/{BTN_MONTH} — список дел с приоритетом\n"
        f"• {BTN_CALENDAR} — ссылка и быстрые слоты\n"
        f"• {BTN_FOCUS} — рекомендованные 2–3 задачи и спринты\n"
        f"• {BTN_KPI} — короткий отчёт по KPI\n")

# ====== ВСПОМОГАТЕЛЬНОЕ ======
def detect_category(t: str):
    t = t.lower()
    if "#семья" in t or "семья" in t: return "Семья"
    if "#ремонт" in t: return "Ремонт"
    if "#личное" in t: return "Личное"
    if "#rnd" in t or "нейросет" in t or "gpt" in t: return "R&D"
    return "Собрание"

def format_tasks(tasks):
    lines = []
    for i, t in enumerate(tasks, 1):
        cat = t.get("Категория","?")
        proj = t.get("Проект","?")
        name = t.get("Задача","?")
        dedl = t.get("Дедлайн","—")
        prog = t.get("Прогресс_%","0")
        prio = t.get("Приоритет", t.get("Приоритет(1-3)","-"))
        lines.append(f"{i}) [{prio}] {name} — #{cat}/{proj} | дедлайн {dedl} | прогресс {prog}%")
    return "\n".join(lines) if lines else "Список пуст."

def telegram_calendar_link(calendar_id: str) -> str:
    # Показываем пользователю открытие своего календаря с добавленным источником
    # (этот линк не «секретный»)
    cid = urllib.parse.quote(calendar_id, safe='')
    return f"https://calendar.google.com/calendar/u/0/r?cid={cid}"

# ====== СТАРТ / МЕНЮ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Готов. Управляю приоритетами и временем.\n" + HELP,
        reply_markup=MAIN_KB
    )

# ====== КНОПКА «Внести» ======
async def handle_capture_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data[AWAITING_CAPTURE_FLAG] = True
    await update.message.reply_text(
        "Окей, пришли текст задачи одной строкой. Примеры:\n"
        "— купить картошки завтра #семья\n"
        "— позвонить поставщику кофе через 2 д #собрание",
        reply_markup=MAIN_KB
    )

async def handle_any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # Если пользователь в режиме «Внести» — пишем в Inbox
    if context.user_data.get(AWAITING_CAPTURE_FLAG):
        context.user_data[AWAITING_CAPTURE_FLAG] = False

        cat = detect_category(text)
        # Выделим простой срок (сегодня/завтра/через N д / dd.mm(/yyyy))
        due = ""
        for kw in ["сегодня", "завтра", "послезавтра"]:
            if kw in text.lower():
                due = kw
                break
        if not due and ("через" in text or "." in text):
            due = text
        due = parse_due(due)

        ok = append_inbox(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, text, category=cat, due_str=due, author=DEFAULT_AUTHOR)
        if ok:
            await update.message.reply_text(
                f"Записал в Inbox → [{cat}] {text}\nСрок: {due or '—'}",
                reply_markup=MAIN_KB
            )
        else:
            await update.message.reply_text("Не удалось записать (проверь доступы).", reply_markup=MAIN_KB)
        return

    # Иначе — позволим печатать «Меню» текстом
    if text.lower() in ("меню", "menu"):
        await start(update, context)
        return

    # Если это просто произвольный текст вне режима — мягко напомним про кнопку
    await update.message.reply_text(
        "Если хочешь быстро записать — нажми «Внести». Остальные функции — на кнопках ниже.",
        reply_markup=MAIN_KB
    )

# ====== KPI ======
async def kpi_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kpi = fetch_kpi(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON)
    if not kpi:
        await update.message.reply_text("KPI пока пусты.", reply_markup=MAIN_KB)
        return
    try:
        ng = kpi.get("%_НГ_дат_продано","")
        ngp = f"{int(float(ng)*100)}%" if ng not in ("", None) else "?"
    except:
        ngp = "?"
    msg = (f"План/Факт: {kpi.get('План_выручка','?')} / {kpi.get('Факт_выручка','?')}\n"
           f"Средний чек: {kpi.get('Средний_чек','?')} | Конверсия: {kpi.get('Конверсия_звонок→бронь','?')}\n"
           f"НГ-даты проданы: {ngp}")
    await update.message.reply_text(msg, reply_markup=MAIN_KB)

    result = gpt_analyze_status(kpi)
    if isinstance(result, tuple) and len(result) >= 2:
        comment, prompt = result[0], result[1]
    else:
        comment, prompt = str(result), ""
    context.user_data["last_status_prompt"] = prompt
    context.user_data["last_status_text"] = comment

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Продолжить ⏭", callback_data="MORE::status")]])
    await update.message.reply_text(f"🤖 Анализ:\n{comment}", reply_markup=kb)

# ====== TODAY / WEEK / MONTH ======
def _period_dates(which: str):
    today = dt.date.today()
    if which == "today":
        return today, today
    if which == "week":
        return today, today + dt.timedelta(days=7)
    if which == "month":
        # 30 календарных дней вперёд
        return today, today + dt.timedelta(days=30)
    return today, today

async def _send_period(update: Update, context: ContextTypes.DEFAULT_TYPE, which: str):
    start, end = _period_dates(which)
    # Берём операционные задачи (вкладка 02_Operations_Sobranie)
    tasks = fetch_ops_tasks(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, 300)

    # Фильтруем по дедлайну в интервале
    def to_date(s):
        try:
            return dt.datetime.strptime(str(s), "%Y-%m-%d").date()
        except:
            return None
    in_range = []
    for t in tasks:
        d = to_date(t.get("Дедлайн",""))
        if d is None:
            continue
        if start <= d <= end:
            in_range.append(t)

    # Отсортируем по дате
    in_range.sort(key=lambda t: t.get("Дедлайн",""))
    text = f"📋 {('Сегодня' if which=='today' else '7 дней' if which=='week' else '30 дней')}:\n" + format_tasks(in_range)
    await update.message.reply_text(text, reply_markup=MAIN_KB)

async def today_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_period(update, context, "today")

async def week_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_period(update, context, "week")

async def month_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_period(update, context, "month")

# ====== ФОКУС ======
async def focus_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = fetch_ops_tasks(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, 100)
    eff = fetch_eff_actions(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, 50)
    top = pick_next(tasks, eff, 3)
    if not top:
        await update.message.reply_text("Нет активных задач. Сначала «Внести».", reply_markup=MAIN_KB)
        return

    context.user_data["free_top"] = top
    # Кнопки спринта
    buttons, lines = [], []
    for i, t in enumerate(top, 1):
        ttl = f"{t.get('Категория','?')} — {t.get('Проект','?')}: {t.get('Задача','?')}"
        lines.append(f"{i}) {ttl}\n   Дедлайн: {t.get('Дедлайн','—')} | Прогресс: {t.get('Прогресс_%','0')}%")
        buttons.append([
            InlineKeyboardButton("25 мин 🕒", callback_data=f"POM::25::{i}"),
            InlineKeyboardButton("60 мин ⏱️", callback_data=f"POM::60::{i}"),
            InlineKeyboardButton("90 мин 💪", callback_data=f"POM::90::{i}")
        ])
    await update.message.reply_text("Рекомендовано сейчас:\n" + "\n".join(lines),
                                    reply_markup=InlineKeyboardMarkup(buttons))
    advice = gpt_analyze_free(top, eff)
    await update.message.reply_text(f"💡 Совет: {advice}", reply_markup=MAIN_KB)

# ====== КАЛЕНДАРЬ ======
async def calendar_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cal_id = os.getenv("CALENDAR_ID", "").strip()
    if not cal_id:
        await update.message.reply_text("CALENDAR_ID не задан в переменных окружения.", reply_markup=MAIN_KB)
        return
    link = telegram_calendar_link(cal_id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Сегодня 19:00 +60", callback_data="CAL::TODAY19::60"),
         InlineKeyboardButton("Завтра 06:00 +90", callback_data="CAL::TOMORROW06::90")],
        [InlineKeyboardButton("Ближайшее окно +25", callback_data="CAL::NEXT::25")]
    ])
    await update.message.reply_text(f"Твой календарь:\n{link}\nВыбери быстрый слот:", reply_markup=kb)

# ====== CALLBACKS ======
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split("::")

    # --- обработка кнопок спринтов (из «Фокус») ---
    if len(data) >= 3 and data[0] == "POM":
        try:
            duration = int(data[1])
            idx = int(data[2]) - 1
        except Exception:
            await q.edit_message_text("Ошибка в данных кнопки. Попробуй снова.")
            return

        top = context.user_data.get("free_top", [])
        if not (0 <= idx < len(top)):
            await q.edit_message_text("Список устарел. Нажми «🎯 Фокус» ещё раз.")
            return

        t = top[idx]
        ttl = f"{t.get('Категория','?')} — {t.get('Проект','?')}: {t.get('Задача','?')}"

        # 1) фиксируем выбор в Inbox
        append_inbox(
            GOOGLE_SHEET_ID,
            GOOGLE_CREDENTIALS_JSON,
            f"[СПРИНТ {duration} мин] {ttl}",
            category="Собрание",
            due_str="завтра",
            author=DEFAULT_AUTHOR
        )
        # 2) создаём событие завтра 06:00 по TZ
        try:
            created = add_event(
                summary=f"[СПРИНТ {duration} мин] {ttl}",
                minutes=duration,
                start_dt=None,  # завтра 06:00
                description="Автозапись из VP Assistant (🎯 Фокус)"
            )
            link = created.get("htmlLink", "—")
            await q.edit_message_text(
                f"🧭 Запланировал спринт: {duration} мин.\n"
                f"Старт: завтра 06:00 ({os.getenv('TZ', 'Europe/Berlin')}).\n"
                f"Календарь: {link}"
            )
        except Exception as e:
            await q.edit_message_text(
                "🧭 Спринт внесён в список дел, но событие в календарь не создалось.\n"
                f"Причина: {e}"
            )
        return

    # --- обработка кнопок календаря (быстрые пресеты) ---
    if len(data) >= 3 and data[0] == "CAL":
        preset = data[1]
        try:
            duration = int(data[2])
        except:
            duration = 60

        # высчитаем start_dt локально
        from dateutil import tz as _tz
        local = _tz.gettz(TZ or "Europe/Berlin")
        now = dt.datetime.now(local)

        if preset == "TODAY19":
            start_dt = now.replace(hour=19, minute=0, second=0, microsecond=0)
            if start_dt < now:
                start_dt = start_dt + dt.timedelta(days=1)
        elif preset == "TOMORROW06":
            start_dt = (now + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        else:
            # пока как завтра 06:00 (позже добавим поиск окна)
            start_dt = (now + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

        try:
            created = add_event(
                summary=f"[Слот {duration} мин] Фокус-набор",
                minutes=duration,
                start_dt=start_dt,
                description="Быстрый слот (Календарь)"
            )
            link = created.get("htmlLink", "—")
            when = start_dt.strftime("%Y-%m-%d %H:%M")
            await q.edit_message_text(f"✅ Слот создан: {duration} мин • {when} ({TZ})\n{link}")
        except Exception as e:
            await q.edit_message_text(f"Не удалось создать слот: {e}")
        return

    # --- обработка кнопки «Продолжить ⏭» после KPI ---
    if q.data == "MORE::status":
        prompt = context.user_data.get("last_status_prompt", "")
        so_far = context.user_data.get("last_status_text", "")
        if not prompt or not so_far:
            await q.message.reply_text("Нечего продолжать. Сначала нажми «📈 Статус KPI».")
            return
        cont = gpt_continue_status(prompt, so_far)
        context.user_data["last_status_text"] = so_far + "\n" + cont
        await q.message.reply_text(f"🤖 Продолжение:\n{cont}")
        return

# ====== РЕЗЕРВНЫЕ /КОМАНДЫ (оставляем, но пользователю не нужны) ======
async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").replace("/add","",1).strip()
    if not text:
        await update.message.reply_text("Пример: /add Обновить экранное меню завтра #собрание", reply_markup=MAIN_KB)
        return
    cat = detect_category(text)
    due = ""
    for kw in ["сегодня","завтра","послезавтра"]:
        if kw in text.lower(): due = kw; break
    if not due and "через" in text: due = text
    due = parse_due(due)
    ok = append_inbox(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, text, category=cat, due_str=due, author=DEFAULT_AUTHOR)
    await update.message.reply_text(f"Записал в Inbox → [{cat}] {text}\nСрок: {due or '—'}" if ok else "Не удалось записать (проверь доступы).",
                                    reply_markup=MAIN_KB)

async def free_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # переиспользуем «Фокус»
    await focus_button(update, context)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # переиспользуем кнопку KPI
    await kpi_button(update, context)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Кнопочная навигация и «резервные» команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("free", free_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))

    # Кнопки (текстовые сообщения)
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_CAPTURE}$"), handle_capture_button))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_TODAY}$"), today_button))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_WEEK}$"), week_button))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MONTH}$"), month_button))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_CALENDAR}$"), calendar_button))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_FOCUS}$"), focus_button))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_KPI}$"), kpi_button))

    # Режим «жду текст после 'Внести'»
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_any_text))
    # Неподдерживаемые команды — показываем меню
    app.add_handler(MessageHandler(filters.COMMAND, start))

    # Запуск (webhook/polling)
    base_url = os.getenv("BASE_URL", "").strip()  # https://...onrender.com
    port = int(os.getenv("PORT", "10000"))
    if base_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_TOKEN,
            webhook_url=f"{base_url}/{TELEGRAM_TOKEN}",
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
