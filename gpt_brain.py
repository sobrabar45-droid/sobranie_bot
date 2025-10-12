# gpt_brain.py
import os
from openai import OpenAI

def _client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    return OpenAI(api_key=key)

def gpt_analyze_free(tasks, eff_list):
    client = _client()
    if client is None:
        return "Добавь OPENAI_API_KEY в .env, чтобы получить умный совет."
    if not tasks:
        return "Сейчас нет активных задач — сделай короткое планирование или восстановление энергии."

    lines = []
    for t in tasks:
        lines.append(
            f"- {t.get('Категория','?')}: {t.get('Задача','?')} "
            f"(дедлайн {t.get('Дедлайн','—')}, прогресс {t.get('Прогресс_%','0')}%)"
        )

    prompt = (
        "Контекст: я владелец бара 'Собрание'. Проанализируй задачи ниже и предложи лучший первый шаг на ближайший час. "
        "Учитывай дедлайны, эффект на выручку/НГ-продажи, прогресс, простоту старта. Дай 1–2 конкретных действия.\n\n"
        + "\n".join(lines)
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=220,
        )
        return (resp.choices[0].message.content.strip() if resp.choices else "Нет ответа ИИ.")
    except Exception as e:
        return f"Не удалось получить совет ИИ: {e}"

def gpt_analyze_status(kpi: dict):
    """Возвращает строго ДВА значения: (text, prompt)."""
    client = _client()
    if client is None:
        return ("Добавь OPENAI_API_KEY в .env, чтобы получить аналитический комментарий.", "")
    if not kpi:
        return ("Пока нет KPI для анализа.", "")

    prompt = (
        "Ты — ассистент управляющего баром. Дай краткий отчёт: что хорошо, что риск, на что сфокусироваться сегодня.\n"
        f"KPI: план выручки {kpi.get('План_выручка','?')}, факт {kpi.get('Факт_выручка','?')}, "
        f"средний чек {kpi.get('Средний_чек','?')}, НГ-даты продано {kpi.get('%_НГ_дат_продано','?')}.\n"
        "Структура ответа: 1) Что хорошо 2) Риски 3) Конкретные шаги на сегодня. Пиши лаконично."
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=250,
        )
        text = resp.choices[0].message.content.strip() if resp.choices else "Нет ответа ИИ."
        return (text, prompt)
    except Exception as e:
        return (f"Ошибка анализа KPI: {e}", prompt)

def gpt_continue_status(original_prompt: str, so_far: str):
    client = _client()
    if client is None:
        return "Добавь OPENAI_API_KEY в .env, чтобы продолжать ответы."
    if not original_prompt or not so_far:
        return "Нет контекста для продолжения. Запроси /status заново."
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": original_prompt},
                {"role": "assistant", "content": so_far},
                {"role": "user", "content": "Продолжи строго с места, где остановился. Не повторяй уже сказанное."}
            ],
            temperature=0.5,
            max_tokens=220,
        )
        return resp.choices[0].message.content.strip() if resp.choices else "Нет продолжения."
    except Exception as e:
        return f"Не удалось продолжить: {e}"
from openai import OpenAI
__gpt_client = None
def _gpt():
    global __gpt_client
    if __gpt_client is None:
        __gpt_client = OpenAI()
    return __gpt_client

def gpt_prioritize(inbox_rows):
    tasks_text = "\n".join([f"- [{r.get('Категория','?')}] {r.get('Текст','?')} (срок: {r.get('Срок','—')})"
                            for r in inbox_rows[:30]])
    prompt = f"""Ты — личный ассистент. Расставь приоритеты очень кратко:
1) Топ-5 срочно/важно — по пунктам.
2) Что делегировать?
3) Что убрать/перенести?
Список задач:
{tasks_text}"""
    r = _gpt().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3, max_tokens=500
    )
    return r.choices[0].message.content.strip()

def gpt_daily_review(day_text, risks_text):
    prompt = f"Сформулируй понятный план дня по событиям:\n{day_text}\nРиски: {risks_text}\nВывод и 3 шага фокуса."
    r = _gpt().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3, max_tokens=400
    )
    return r.choices[0].message.content.strip()

def gpt_weekly_review(week_text, goals_hint=""):
    prompt = f"Краткий недельный обзор:\n{week_text}\n{goals_hint}\nПики нагрузки, свободные окна, 5 главных задач."
    r = _gpt().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3, max_tokens=600
    )
    return r.choices[0].message.content.strip()

