import os
import logging
import datetime as dt
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
TZ = os.getenv("TZ", "Europe/Berlin")

logging.basicConfig(level=logging.INFO)


# --- Глобальный перехватчик ошибок: стек в логи, пользователю — короткое сообщение
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import traceback
    err = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logging.error("❌ Unhandled error:\n%s", err)
    try:
        chat_id = None
        if isinstance(update, Update):
            if update.effective_chat:
                chat_id = update.effective_chat.id
            elif update.callback_query and update.callback_query.message:
                chat_id = update.callback_query.message.chat_id
        if chat_id:
            await context.bot.sendMessage(chat_id, "⚠️ Внутренняя ошибка. Подробности в логах Render.")
    except Exception:
        pass


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
        [InlineKeyboardButton("🔗 Календарь (веб)", url="https://calendar.google.com")],
        [InlineKeyboardButton("🧪 Диагностика", callback_data="diag")],
    ]
    await update.message.reply_text(
        "👋 Добро пожаловать! Выберите действие:",
        reply_markup=InlineKeyboardMarkup(kb),
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


# === САМО-ДИАГНОСТИКА ===
async def diag_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timedelta
    calendar_id = CALENDAR_ID
    creds_raw = GOOGLE_CREDENTIALS_JSON
    tz = TZ
    y_key = os.getenv("YANDEX_API_KEY", "")
    y_folder = os.getenv("YANDEX_FOLDER_ID", "")
    base_url = BASE_URL
    oai = os.getenv("OPENAI_API_KEY", "")

    # тип creds: путь/встроенный JSON
    if not creds_raw:
        creds_kind = "❌ пусто"
    elif os.path.exists(creds_raw):
        creds_kind = f"📁 путь к файлу (найден): {creds_raw}"
    else:
        import json
        try:
            _ = json.loads(creds_raw)
            creds_kind = "📄 встроенный JSON (OK)"
        except Exception as e:
            creds_kind = f"⚠️ встроенный JSON, но парсинг не удался: {e}"

    # пробуем прочитать 3 события
    cal_probe = ""
    try:
        if not calendar_id:
            cal_probe = "❌ CALENDAR_ID не задан"
        else:
            now = datetime.utcnow()
            events = list_events_between(calendar_id, creds_raw, now, now + timedelta(days=3), max_results=3)
            if not events:
                cal_probe = "✅ Календарь читается, событий нет."
            else:
                cal_probe = "✅ Календарь читается. Ближайшие события:\n" + pretty_events(events)
    except Exception as e:
        cal_probe = f"❌ Ошибка чтения календаря: {e}"

    stt_probe = []
    stt_probe.append("Yandex SpeechKit: " + ("✅ ключ задан" if y_key and y_folder else "❌ нет ключа/FolderID"))
    stt_probe.append("OpenAI: " + ("✅ ключ задан" if oai else "— (не используется)"))

    msg = (
        "🧪 DIAG:\n"
        f"• CALENDAR_ID: {calendar_id or '—'}\n"
        f"• GOOGLE_CREDENTIALS_JSON: {creds_kind}\n"
        f"• TZ: {tz}\n"
        f"• BASE_URL: {base_url or '—'}\n"
        f"• STТ: {', '.join(stt_probe)}\n\n"
        f"{cal_probe}"
    )
    await update.message.reply_text(msg)


# === ОБРАБОТКА НАЖАТИЙ ===
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    raw = q.data
    data = raw.split("::")

    # --- Диагностика кнопкой
    if raw == "diag":
        # «проксируем» на /diag, чтобы логика была одна
        fake_update = Update(update.update_id, message=q.message)
        await diag_cmd(fake_update, context)
        return
    # --- Статус KPI по кнопке ---
    if raw == "status":
        # Проксируем в тот же хендлер, что и команда /status
        fake_update = Update(update.update_id, message=q.message)
        await status_cmd(fake_update, context)
        return

    # --- Список событий (день / неделя / месяц)
    if raw in ["day", "week", "month"]:
        now = dt.datetime.utcnow()
        if raw == "day":
            end = now + dt.timedelta(days=1)
            title = "🗓 На сегодня"
        elif raw == "week":
            end = now + dt.timedelta(days=7)
            title = "📅 На 7 дней"
        else:
            end = now + dt.timedelta(days=30)
            title = "🗓️ На 30 дней"

        if not CALENDAR_ID:
            await q.edit_message_text("❌ CALENDAR_ID не задан в переменных окружения.", reply_markup=None)
            return

        try:
            events = list_events_between(CALENDAR_ID, GOOGLE_CREDENTIALS_JSON, now, end)
            text = pretty_events(events)
            out = f"{title}:\n{text}" if text.strip() else f"{title}:\n—"
            await q.edit_message_text(out, reply_markup=None)
        except Exception as e:
            await q.edit_message_text(f"Не удалось получить события календаря: {e}", reply_markup=None)
        return

    # --- обработка кнопки «Внести задачу»
    if raw == "capture":
        await q.edit_message_text("📝 Напишите задачу (например: «купить картошку #семья завтра»):")
        context.user_data["capture_mode"] = True
        return

    # --- обработка кнопки «Продолжить ⏭» после KPI
    if raw == "MORE::status":
        prompt = context.user_data.get("last_status_prompt", "")
        so_far = context.user_data.get("last_status_text", "")
        if not prompt or not so_far:
            await q.message.reply_text("Нечего продолжать. Сначала нажми «📊 Статус».")
            return
        cont = gpt_continue_status(prompt, so_far)
        context.user_data["last_status_text"] = so_far + "\n" + cont
        await q.message.reply_text(f"🤖 Продолжение:\n{cont}")
        return

    # --- обработка спринтов (если будут кнопки POM::dur::idx)
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
            author=AUTHOR_NAME,
        )
        # 2) создаём событие завтра 06:00 по TZ
        try:
            created = add_event(
                summary=f"[СПРИНТ {duration} мин] {ttl}",
                minutes=duration,
                start_dt=None,  # завтра 06:00 (см. calendar_api.add_event)
                description="Автозапись из VP Assistant (🎯 Фокус)",
            )
            link = created.get("htmlLink", "—")
            await q.edit_message_text(
                f"🧭 Запланировал спринт: {duration} мин.\n"
                f"Старт: завтра 06:00 ({TZ}).\n"
                f"Календарь: {link}"
            )
        except Exception as e:
            await q.edit_message_text(
                "🧭 Спринт внесён в список дел, но событие в календарь не создалось.\n"
                f"Причина: {e}"
            )
        return

    # --- обработка быстрых пресетов календаря (если будут CAL::PRESET::DUR)
    if len(data) >= 3 and data[0] == "CAL":
        preset = data[1]
        try:
            duration = int(data[2])
        except Exception:
            duration = 60

        now_local = dt.datetime.now()
        # делаем start_dt «наивным» — calendar_api сам подставит TZ
        if preset == "TODAY19":
            start_dt = now_local.replace(hour=19, minute=0, second=0, microsecond=0)
            if start_dt < now_local:
                start_dt = start_dt + dt.timedelta(days=1)
        elif preset == "TOMORROW06":
            start_dt = (now_local + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        else:
            start_dt = (now_local + dt.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

        try:
            created = add_event(
                summary=f"[Слот {duration} мин] Фокус-набор",
                minutes=duration,
                start_dt=start_dt,
                description="Быстрый слот (Календарь)",
            )
            link = created.get("htmlLink", "—")
            when = start_dt.strftime("%Y-%m-%d %H:%M")
            await q.edit_message_text(f"✅ Слот создан: {duration} мин • {when} ({TZ})\n{link}")
        except Exception as e:
            await q.edit_message_text(f"Не удалось создать слот: {e}")
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

    # команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("diag", diag_cmd))

    # кнопки/колбэки
    app.add_handler(CallbackQueryHandler(on_cb))

    # сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # глобальный обработчик ошибок
    app.add_error_handler(error_handler)

    # Webhook для Render
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{BASE_URL}/{TELEGRAM_TOKEN}",
    )


if __name__ == "__main__":
    main()
