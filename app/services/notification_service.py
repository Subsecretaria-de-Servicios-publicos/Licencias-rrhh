from app.models import LicenseRequest
from app.services.evolution_service import send_whatsapp_text


REQUEST_TYPE_LABELS = {
    "license": "licencia",
    "medical_folder": "carpeta médica",
    "other_license": "otra licencia",
}


STATUS_LABELS = {
    "pending": "pendiente",
    "approved": "aprobada",
    "rejected": "rechazada",
    "observed": "observada",
    "cancelled": "cancelada",
}


def _format_date(value) -> str:
    if not value:
        return "-"

    try:
        return value.strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def build_license_status_message(item: LicenseRequest) -> str:
    request_type = REQUEST_TYPE_LABELS.get(item.request_type, item.request_type)
    status = STATUS_LABELS.get(item.status, item.status)

    person_name = "Hola"
    if item.person:
        person_name = f"Hola {item.person.first_name}".strip()

    if item.request_type == "medical_folder":
        base = (
            f"{person_name}, te informamos que tu solicitud de {request_type} "
            f"fue marcada como {status}.\n\n"
            f"Desde: {_format_date(item.start_date)}"
        )

        if item.end_date:
            base += f"\nHasta: {_format_date(item.end_date)}"

    else:
        base = (
            f"{person_name}, te informamos que tu solicitud de {request_type} "
            f"fue marcada como {status}.\n\n"
            f"Desde: {_format_date(item.start_date)}\n"
            f"Hasta: {_format_date(item.end_date)}"
        )

    if item.admin_notes:
        base += f"\n\nObservación de RRHH: {item.admin_notes}"

    if item.status == "approved":
        base += "\n\nTu solicitud quedó aprobada por RRHH."

    elif item.status == "rejected":
        base += "\n\nTu solicitud fue rechazada. Podés comunicarte con RRHH para más información."

    elif item.status == "observed":
        base += "\n\nTu solicitud quedó observada. Revisá la observación indicada por RRHH."

    elif item.status == "cancelled":
        base += "\n\nTu solicitud fue cancelada."

    else:
        base += "\n\nTu solicitud quedó pendiente de revisión."

    return base


def notify_license_status_by_whatsapp(item: LicenseRequest) -> dict:
    if not item.person:
        return {
            "ok": False,
            "error": "La solicitud no tiene persona vinculada.",
        }

    if not item.person.phone:
        return {
            "ok": False,
            "error": "La persona no tiene teléfono cargado.",
        }

    message = build_license_status_message(item)

    result = send_whatsapp_text(
        item.person.phone,
        message,
    )

    return {
        "ok": result.get("ok", False),
        "phone": item.person.phone,
        "message": message,
        "send_result": result,
    }