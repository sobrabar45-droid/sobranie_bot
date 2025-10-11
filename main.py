import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from config import TELEGRAM_TOKEN, GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, DEFAULT_AUTHOR
from google_sheets import append_inbox, fetch_ops_tasks, fetch_kpi, fetch_eff_actions
from logic import parse_due, pick_next
from gpt_brain import gpt_analyze_free, gpt_analyze_status, gpt_continue_status
logging.basicConfig(level=logging.INFO)
HELP = ("Команды:\n"
        "/start — запуск\n"
        "/add <текст> — добавить задачу/идею\n"
        "/free — что сделать прямо сейчас\n"
        "/status — краткий статус KPI")

def detect_category(t: str):
    t = t.lower()
    if "#семья" in t or "семья" in t: return "Семья"
    if "#ремонт" in t: return "Ремонт"
    if "#личное" in t: return "Личное"
    if "#rnd" in t or "нейросет" in t or "gpt" in t: return "R&D"
    return "Собрание"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Готов. Управляю приоритетами и временем.\n"+HELP)

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").replace("/add","",1).strip()
    if not text:
        await update.message.reply_text("Пример: /add Обновить экранное меню завтра #собрание")
        return
    cat = detect_category(text)
    # выделим простой срок
    due = ""
    for kw in ["сегодня","завтра","послезавтра"]:
        if kw in text.lower(): due = kw; break
    if not due and "через" in text: due = text  # парсер поймает
    due = parse_due(due)
    ok = append_inbox(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, text, category=cat, due_str=due, author=DEFAULT_AUTHOR)
    await update.message.reply_text(f"Записал в Inbox → [{cat}] {text}\nСрок: {due or '—'}" if ok else "Не удалось записать (проверь доступы).")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) Получаем KPI и отправляем краткий факт-отчёт
    kpi = fetch_kpi(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON)
    if not kpi:
        await update.message.reply_text("KPI пока пусты.")
        return
    try:
        ng = kpi.get("%_НГ_дат_продано","")
        ngp = f"{int(float(ng)*100)}%" if ng not in ("", None) else "?"
    except:
        ngp = "?"
    msg = (f"План/Факт: {kpi.get('План_выручка','?')} / {kpi.get('Факт_выручка','?')}\n"
           f"Средний чек: {kpi.get('Средний_чек','?')} | Конверсия: {kpi.get('Конверсия_звонок→бронь','?')}\n"
           f"НГ-даты проданы: {ngp}")
    await update.message.reply_text(msg)

    # 2) GPT-анализ с защищённой распаковкой результата
    result = gpt_analyze_status(kpi)
    if isinstance(result, tuple) and len(result) >= 2:
        comment, prompt = result[0], result[1]
    else:
        comment, prompt = str(result), ""

    # 3) Сохраним контекст для продолжений / кнопки
    context.user_data["last_status_prompt"] = prompt
    context.user_data["last_status_text"] = comment

    # 4) Кнопка «Продолжить ⏭»
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Продолжить ⏭", callback_data="MORE::status")]
    ])
    await update.message.reply_text(f"🤖 Анализ:\n{comment}", reply_markup=kb)
async def free_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = fetch_ops_tasks(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, 100)
    eff = fetch_eff_actions(GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, 50)
    top = pick_next(tasks, eff, 3)
    if not top:
        await update.message.reply_text("Нет активных задач. Добавь через /add.")
        return

    context.user_data["free_top"] = top

    buttons, lines = [], []
    for i, t in enumerate(top, 1):
        ttl = f"{t.get('Категория','?')} — {t.get('Проект','?')}: {t.get('Задача','?')}"
        lines.append(f"{i}) {ttl}\n   Дедлайн: {t.get('Дедлайн','—')} | Прогресс: {t.get('Прогресс_%','0')}%")
        buttons.append([
            InlineKeyboardButton("25 мин 🕒", callback_data=f"POM::25::{i}"),
            InlineKeyboardButton("60 мин ⏱️", callback_data=f"POM::60::{i}"),
            InlineKeyboardButton("90 мин 💪", callback_data=f"POM::90::{i}")
        ])

    # ВАЖНО: закрываем скобку здесь — это один вызов
    await update.message.reply_text(
        "Рекомендовано сейчас:\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    # А уже затем — отдельным сообщением совет GPT
    advice = gpt_analyze_free(top, eff)
    await update.message.reply_text(f"💡 Совет: {advice}")

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data.split("::")

    # --- обработка кнопок спринтов ---
    if len(data) >= 3 and data[0] == "POM":
        try:
            duration = int(data[1])
            idx = int(data[2]) - 1
        except Exception:
            await q.edit_message_text("Ошибка в данных кнопки. Попробуй снова.")
            return

        top = context.user_data.get("free_top", [])
        if not (0 <= idx < len(top)):
            await q.edit_message_text("Список устарел. Нажми /free ещё раз.")
            return

        t = top[idx]
        ttl = f"{t.get('Категория','?')} — {t.get('Проект','?')}: {t.get('Задача','?')}"

        append_inbox(
            GOOGLE_SHEET_ID,
            GOOGLE_CREDENTIALS_JSON,
            f"[СПРИНТ {duration} мин] {ttl}",
            category="Собрание",
            due_str="завтра",
            author=DEFAULT_AUTHOR
        )

        await q.edit_message_text(
            f"🧭 Добавил запрос: {duration} мин фокус на задачу.\nСлот появится завтра в 06:00 в календаре."
        )
        return

    # --- обработка кнопки «Продолжить ⏭» ---
    elif q.data == "MORE::status":
        from gpt_brain import gpt_continue_status
        prompt = context.user_data.get("last_status_prompt", "")
        so_far = context.user_data.get("last_status_text", "")
        if not prompt or not so_far:
            await q.message.reply_text("Нечего продолжать. Сначала запусти /status.")
            return

        cont = gpt_continue_status(prompt, so_far)
        context.user_data["last_status_text"] = so_far + "\n" + cont

        await q.message.reply_text(f"🤖 Продолжение:\n{cont}")
        return

async def more_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = context.user_data.get("last_status_prompt", "")
    so_far = context.user_data.get("last_status_text", "")
    if not prompt or not so_far:
        await update.message.reply_text("Нечего продолжать. Сначала запроси /status.")
        return

    from gpt_brain import gpt_continue_status
    cont = gpt_continue_status(prompt, so_far)

    # обновляем контекст, чтобы можно было продолжать несколько раз
    context.user_data["last_status_text"] = so_far + "\n" + cont

    await update.message.reply_text(f"🤖 Продолжение:\n{cont}\n\n(/more — ещё продолжить)")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("free", free_cmd))
    app.add_handler(CommandHandler("more", more_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.COMMAND, start))

    # --- режим запуска ---
    base_url = os.getenv("BASE_URL", "").strip()      # https://...onrender.com
    port = int(os.getenv("PORT", "10000"))            # Render задаёт PORT

    if base_url:
        # Webhook-режим для Render (Web Service обязан слушать порт)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_TOKEN,                   # скрытый путь
            webhook_url=f"{base_url}/{TELEGRAM_TOKEN}",
        )
    else:
        # Локально можно оставлять polling
        app.run_polling()

if __name__ == "__main__":
    main()
