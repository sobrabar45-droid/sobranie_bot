import os
import requests
import json
from openai import OpenAI

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def recognize_speech(audio_path: str) -> str:
    """
    Распознаёт речь: сначала пробует Yandex SpeechKit, потом OpenAI.
    """
    # --- 1. Если есть Яндекс SpeechKit ---
    if YANDEX_API_KEY and YANDEX_FOLDER_ID:
        try:
            with open(audio_path, "rb") as f:
                audio_data = f.read()
            url = f"https://stt.api.cloud.yandex.net/speech/v1/stt:recognize?folderId={YANDEX_FOLDER_ID}"
            headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
            resp = requests.post(url, headers=headers, data=audio_data)
            result = resp.json()
            if "result" in result:
                return result["result"]
            else:
                print("Yandex SpeechKit error:", result)
        except Exception as e:
            print("Ошибка Yandex SpeechKit:", e)

    # --- 2. Если нет SpeechKit, пробуем OpenAI ---
    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=audio_file
                )
            return transcript.text
        except Exception as e:
            print("Ошибка OpenAI:", e)

    return "⚠️ Не удалось распознать голос."
