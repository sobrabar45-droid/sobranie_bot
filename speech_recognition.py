import os
import json
import requests
from typing import Optional
from openai import OpenAI

# ── Переменные окружения ───────────────────────────────────────────
YANDEX_API_KEY   = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")

# ── Вспомогательные ────────────────────────────────────────────────
def _clean_text(t: str) -> str:
    """Аккуратная нормализация текста результата."""
    if not isinstance(t, str):
        return ""
    t = t.replace("  ", " ").strip()
    if not t:
        return ""
    # Первая буква с заглавной, точка в конце при необходимости
    if t[0].isalpha():
        t = t[0].upper() + t[1:]
    if t and t[-1] not in ".!?…":
        t += "."
    return t

# ── Распознавание через Yandex SpeechKit ───────────────────────────
def _recognize_yandex(audio_path: str) -> Optional[str]:
    """
    Отправляет файл в Yandex STT.
    Telegram voice = OGG/Opus — поддерживается STT напрямую.
    Документация: https://cloud.yandex.ru/docs/speechkit/stt/request
    """
    if not (YANDEX_API_KEY and YANDEX_FOLDER_ID):
        return None

    url = (
        "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
        f"?folderId={YANDEX_FOLDER_ID}&lang=ru-RU"
    )
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}

    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(url, headers=headers, data=f.read(), timeout=60)
        # Пример ответа: {"result":"текст", "endOfUtterance":true}
        data = resp.json()
    except Exception as e:
        print("Yandex STT network/parse error:", repr(e))
        return None

    if isinstance(data, dict) and "result" in data:
        return _clean_text(data.get("result", ""))

    # Логируем ошибку для диагностики
    print("Yandex STT error payload:", json.dumps(data, ensure_ascii=False))
    return None

# ── Распознавание через OpenAI (fallback) ──────────────────────────
def _recognize_openai(audio_path: str) -> Optional[str]:
    """
    Fallback на OpenAI (Whisper via Chat Completions API).
    Требуется OPENAI_API_KEY.
    """
    if not OPENAI_API_KEY:
        return None

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(audio_path, "rb") as audio_file:
            # gpt-4o-mini-transcribe — актуальная лёгкая модель для транскрибации
            out = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                # Можно подсказать язык, чтобы ускорить/улучшить качество
                # language="ru"
            )
        text = getattr(out, "text", "") or ""
        return _clean_text(text)
    except Exception as e:
        print("OpenAI transcription error:", repr(e))
        return None

# ── Публичная функция ──────────────────────────────────────────────
def recognize_speech(audio_path: str) -> str:
    """
    Универсальная точка входа:
    1) Пытается Yandex SpeechKit;
    2) Если не удалось — OpenAI;
    3) Если и это не удалось — возвращает предупреждение.
    """
    # 1) Yandex
    text = _recognize_yandex(audio_path)
    if text:
        return text

    # 2) OpenAI
    text = _recognize_openai(audio_path)
    if text:
        return text

    return (
        "⚠️ Не удалось распознать голос. "
        "Проверьте YANDEX_API_KEY / YANDEX_FOLDER_ID или квоту OpenAI."
    )
