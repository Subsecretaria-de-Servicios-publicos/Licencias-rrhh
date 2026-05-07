import os

import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")


def normalize_whatsapp_number(number: str) -> str:
    value = number.strip()
    value = value.replace("@s.whatsapp.net", "")
    value = value.replace("@c.us", "")
    value = value.replace("+", "")
    value = value.replace(" ", "")
    value = value.replace("-", "")
    value = value.replace("(", "")
    value = value.replace(")", "")
    return value


def _post_send_text(payload: dict) -> dict:
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=20) as client:
        response = client.post(url, json=payload, headers=headers)

        try:
            response_json = response.json()
        except Exception:
            response_json = {"raw": response.text}

        if response.status_code >= 400:
            return {
                "ok": False,
                "status_code": response.status_code,
                "payload_sent": payload,
                "response": response_json,
            }

        return {
            "ok": True,
            "status_code": response.status_code,
            "data": response_json,
        }


def send_whatsapp_text(number: str, text: str) -> dict:
    if not EVOLUTION_API_URL:
        return {"ok": False, "error": "Falta EVOLUTION_API_URL"}

    if not EVOLUTION_API_KEY:
        return {"ok": False, "error": "Falta EVOLUTION_API_KEY"}

    if not EVOLUTION_INSTANCE:
        return {"ok": False, "error": "Falta EVOLUTION_INSTANCE"}

    clean_number = normalize_whatsapp_number(number)

    payload_v1 = {
        "number": clean_number,
        "text": text,
    }

    result_v1 = _post_send_text(payload_v1)

    if result_v1.get("ok"):
        return result_v1

    payload_v2 = {
        "number": clean_number,
        "options": {
            "delay": 1200,
            "presence": "composing",
        },
        "textMessage": {
            "text": text,
        },
    }

    result_v2 = _post_send_text(payload_v2)

    if result_v2.get("ok"):
        return result_v2

    return {
        "ok": False,
        "error": "No se pudo enviar mensaje con ningún formato compatible",
        "attempts": {
            "v1": result_v1,
            "v2": result_v2,
        },
    }