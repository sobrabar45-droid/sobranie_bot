import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from gpt_brain import gpt_analyze_status, gpt_continue_status
from google_sheets import fetch_kpi, append_inbox
from calendar_api import list_events_between, pretty_events, add_event
from speech_recognition import recognize_speech

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "В.П.")
BASE_URL = os.getenv("BASE_URL", "https://sobranie-bot.onrender.com")
CALENDAR_ID = os.getenv("CALENDAR_ID", "").strip()

logging.basicConfig(level=logging.INFO)

# === КОМАНДЫ ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [
            InlineKeyboardButton("🗓 День", callback_data="day"),
            InlineKeyboardButton("📅 Неделя", callback_data="week"),
            InlineKeyboardButton("🗓️ Месяц", callback_data="month"),
        ],
        [InlineKeyboardButton("➕ Внести задачу", callback_data="capture")],
        [InlineKeyboardButton("📎 Календарь", url="https://calendar.google.com")],
    ]
    await update.message.reply_text(
        "👋 Добро пожаловать! Выберите действие:", 
        reply_markup=InlineKeyboardMarkup(kb)
    )

# === СТАТУС / KPI ===

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Анализирую показатели...")
    kpi = fetch_kpi(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON)
    result = gpt_analyze_status(kpi)

    if isinstance(result, tuple) and len(result) >= 2:
        comment, prompt = result
    else:
        comment, prompt = str(result), ""

    context.user_data["last_status_prompt"] = prompt
    context.user_data["last_status_text"] = comment

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Продолжить", callback_data="MORE::status")]])
    await update.message.reply_text(f"🤖 Анализ:\n{comment}", reply_markup=kb)

# === ОБРАБОТКА НАЖАТИЙ ===

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split("::")

    # --- Кнопки периодов: День / Неделя / Месяц ---
    if q.data in ["day", "week", "month"]:
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        if q.data == "day":
            end = now + timedelta(days=1)
            title = "🗓 На сегодня"
        elif q.data == "week":
            end = now + timedelta(days=7)
            title = "📅 На 7 дней"
        else:
            end = now + timedelta(days=30)
            title = "🗓️ На 30 дней"

        if not CALENDAR_ID:
            await q.edit_message_text("CALENDAR_ID не задан в переменных окружения.", reply_markup=None)
            return

        try:
            events = list_events_between(CALENDAR_ID, GOOGLE_CREDENTIALS_JSON, now, end)
            text = pretty_events(events)
            out = f"{title}:\n{text}" if text.strip() else f"{title}:\n—"
            await q.edit_message_text(out, reply_markup=None)
        except Exception as e:
            await q.edit_message_text(f"Не удалось получить события календаря: {e}", reply_markup=None)
        return

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

    # --- Кнопка «Внести задачу» ---
    if data == "capture":
        await q.edit_message_text("📝 Напишите задачу (например: «купить картошку #семья завтра»):")
        context.user_data["capture_mode"] = True
        return

    # --- Продолжение анализа ---
    if data == "MORE::status":
        prompt = context.user_data.get("last_status_prompt", "")
        so_far = context.user_data.get("last_status_text", "")
        if not prompt or not so_far:
            await q.message.reply_text("Нет данных для продолжения. Сначала запустите /status.")
            return
        cont = gpt_continue_status(prompt, so_far)
        context.user_data["last_status_text"] = so_far + "\n" + cont
        await q.message.reply_text(f"🤖 Продолжение:\n{cont}")
        return

# === ДОБАВЛЕНИЕ ТЕКСТА ===

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("capture_mode"):
        context.user_data["capture_mode"] = False
        text = update.message.text
        append_inbox(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, text, author=AUTHOR_NAME)
        await update.message.reply_text(f"✅ Задача добавлена:\n{text}")
        return
    await update.message.reply_text("💬 Используйте кнопки меню для выбора действия.")

# === ОБРАБОТКА ГОЛОСА ===

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    file_path = "voice.ogg"
    await file.download_to_drive(file_path)

    text = recognize_speech(file_path)
    if text.startswith("⚠️"):
        await update.message.reply_text(text)
        return

    append_inbox(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, text, author=AUTHOR_NAME)
    await update.message.reply_text(f"🗣 Распознал и добавил:\n{text}")

# === ГЛАВНАЯ ФУНКЦИЯ ===

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # --- Webhook для Render ---
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{BASE_URL}/{TELEGRAM_TOKEN}",
    )

if __name__ == "__main__":
    main()
