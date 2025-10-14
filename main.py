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

    data = q.data

    # --- Список событий (день / неделя / месяц) ---
    if data in ["day", "week", "month"]:
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        if data == "day":
            end = now + timedelta(days=1)
        elif data == "week":
            end = now + timedelta(days=7)
        else:
            end = now + timedelta(days=30)

        events = list_events_between(GOOGLE_CREDENTIALS_JSON, now, end)
        text = pretty_events(events, title=f"🗓 Список ({data})")
        await q.edit_message_text(text or "Пока нет событий.", reply_markup=None)
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
