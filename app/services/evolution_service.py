import mimetypes
import os
import requests
import httpx
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
PUBLIC_WEBHOOK_URL = os.getenv("PUBLIC_WEBHOOK_URL", "")

def get_public_base_url() -> str:
    """
    Usa PUBLIC_WEBHOOK_URL para calcular la URL pública base del sistema.

    Ejemplo:
    PUBLIC_WEBHOOK_URL=https://licrrhh.salta.gob.ar/api/evolution/webhook

    Devuelve:
    https://licrrhh.salta.gob.ar
    """
    value = (PUBLIC_WEBHOOK_URL or "").strip()

    if value.endswith("/api/evolution/webhook"):
        return value.replace("/api/evolution/webhook", "")

    return value.rstrip("/")


def detect_media_type(mime_type: str | None, filename: str | None = None) -> str:
    mime = mime_type or ""

    if not mime and filename:
        guessed, _ = mimetypes.guess_type(filename)
        mime = guessed or ""

    if mime.startswith("image/"):
        return "image"

    if mime.startswith("video/"):
        return "video"

    if mime.startswith("audio/"):
        return "audio"

    return "document"


def send_whatsapp_media(
    phone: str,
    media_url: str,
    filename: str,
    mime_type: str | None = None,
    caption: str | None = None,
) -> dict:
    """
    Envía archivo por Evolution API usando URL pública.

    Requiere que media_url sea accesible públicamente desde internet.
    """
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY or not EVOLUTION_INSTANCE:
        return {
            "ok": False,
            "error": "Faltan variables de entorno de Evolution API",
        }

    clean_phone = str(phone or "").replace("+", "").replace(" ", "").strip()

    if not clean_phone:
        return {
            "ok": False,
            "error": "Teléfono vacío",
        }

    mime = mime_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    media_type = detect_media_type(mime, filename)

    url = f"{EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE}"

    payload = {
        "number": clean_phone,
        "mediatype": media_type,
        "mimetype": mime,
        "caption": caption or "",
        "media": media_url,
        "fileName": filename or "archivo",
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": EVOLUTION_API_KEY,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=60,
        )

        try:
            data = response.json()
        except Exception:
            data = response.text

        return {
            "ok": response.status_code in {200, 201},
            "status_code": response.status_code,
            "data": data,
            "payload": payload,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "payload": payload,
        }

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