import datetime, re

def parse_due(text):
    text = (text or "").lower()
    today = datetime.date.today()
    if "сегодня" in text: return today.isoformat()
    if "завтра" in text: return (today + datetime.timedelta(days=1)).isoformat()
    if "послезавтра" in text: return (today + datetime.timedelta(days=2)).isoformat()
    m = re.search(r"через\s+(\d+)\s+д", text)
    if m: return (today + datetime.timedelta(days=int(m.group(1)))).isoformat()
    for fmt in ("%d.%m.%Y","%d.%m"):
        try:
            dt = datetime.datetime.strptime(text, fmt)
            if fmt=="%d.%m": dt = dt.replace(year=today.year)
            return dt.date().isoformat()
        except: pass
    return ""

def score_task(task, eff_list):
    prio = float(task.get("Приоритет", task.get("Приоритет(1-3)","2")) or 2)
    progress = float(task.get("Прогресс_%", 0) or 0)
    # дедлайн
    days_left = 30.0
    try:
        d = datetime.datetime.strptime(str(task.get("Дедлайн","")), "%Y-%m-%d").date()
        days_left = (d - datetime.date.today()).days
        if days_left < 0: days_left = 0
    except: pass
    # эффект
    effect = 0.0
    for e in eff_list:
        if task.get("Категория","").lower() in str(e.get("Направление","")).lower():
            try: effect = max(effect, float(str(e.get("Потенциал_прироста_%","0")).replace("+","").replace(",",".") or 0))
            except: pass
    return prio*2 + effect/5 + (100-progress)/50 + (30 - min(days_left,30))/10

def pick_next(tasks, eff_list, top=3):
    ranked = sorted(((score_task(t, eff_list), t) for t in tasks), key=lambda x: x[0], reverse=True)
    return [t for _, t in ranked[:top]]
