import ast
import csv
import io
import json
import re
from datetime import date, datetime, time
from math import ceil

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    can_answer_messages,
    can_change_license_status,
    can_manage_licenses,
    can_manage_messages,
    can_manage_persons,
    can_manage_users,
    get_current_user,
)
from app.db import get_db
from app.models import AuditLog, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 20


AUDIT_ACTION_LABELS = {
    "create": "Crear",
    "update": "Actualizar",
    "delete": "Eliminar",
    "view": "Ver",
    "login": "Inicio de sesión",
    "logout": "Cierre de sesión",

    "assistant_paused": "Asistente pausado",
    "assistant_resumed": "Asistente reanudado",
    "pause_assistant": "Pausar asistente",
    "resume_assistant": "Reanudar asistente",

    "human_reply": "Respuesta humana",
    "human_reply_sent": "Respuesta humana enviada",

    "conversation_created": "Conversación creada",
    "message_received": "Mensaje recibido",
    "message_sent": "Mensaje enviado",

    "license_created": "Solicitud creada",
    "license_created_manual": "Solicitud creada manualmente",
    "license_updated": "Solicitud actualizada",
    "license_edited": "Solicitud editada",
    "license_deleted": "Solicitud eliminada",
    "license_status_changed": "Cambio de estado de solicitud",
    "license_status_changed_from_conversation": "Cambio de estado desde conversación",

    "person_created": "Persona creada",
    "person_updated": "Persona actualizada",
    "person_edited": "Persona editada",
    "person_deleted": "Persona eliminada",

    "user_created": "Usuario creado",
    "user_updated": "Usuario actualizado",
    "user_deleted": "Usuario eliminado",
    "user_password_changed": "Contraseña de usuario cambiada",
    "user_password_reset": "Contraseña de usuario reiniciada",
}


AUDIT_ENTITY_LABELS = {
    "person": "Persona",
    "persons": "Personas",
    "conversation": "Conversación",
    "message": "Mensaje",
    "license_request": "Solicitud de licencia",
    "license": "Licencia",
    "medical_folder": "Carpeta médica",
    "other_license": "Otra licencia",
    "user": "Usuario",
    "audit": "Auditoría",
}


STATUS_LABELS = {
    "pending": "Pendiente",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "observed": "Observada",
    "cancelled": "Cancelada",
    None: "-",
    "": "-",
}


REQUEST_TYPE_LABELS = {
    "license": "Licencia",
    "medical_folder": "Carpeta médica",
    "other_license": "Otra licencia",
}


def audit_action_label(value: str | None) -> str:
    if not value:
        return "-"

    return AUDIT_ACTION_LABELS.get(
        value,
        value.replace("_", " ").capitalize(),
    )


def audit_entity_label(value: str | None) -> str:
    if not value:
        return "-"

    return AUDIT_ENTITY_LABELS.get(
        value,
        value.replace("_", " ").capitalize(),
    )


def status_label(value: str | None) -> str:
    if value in STATUS_LABELS:
        return STATUS_LABELS[value]

    return value or "-"


def request_type_label(value: str | None) -> str:
    if not value:
        return "-"

    return REQUEST_TYPE_LABELS.get(value, value)


def _admin_context(current_user: User, extra: dict | None = None) -> dict:
    data = {
        "current_user": current_user,
        "can_manage_users": can_manage_users(current_user),
        "can_manage_licenses": can_manage_licenses(current_user),
        "can_manage_persons": can_manage_persons(current_user),
        "can_manage_messages": can_manage_messages(current_user),
        "can_change_license_status": can_change_license_status(current_user),
        "can_answer_messages": can_answer_messages(current_user),
    }

    if extra:
        data.update(extra)

    return data


def _require_admin(current_user: User | None):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    if not can_manage_users(current_user):
        return RedirectResponse(url="/admin", status_code=303)

    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    value = value.strip()

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _apply_filters(
    query,
    action: str | None,
    entity_type: str | None,
    user_email: str | None,
    date_from: date | None,
    date_to: date | None,
):
    if action:
        query = query.filter(AuditLog.action == action)

    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)

    if user_email:
        query = query.filter(AuditLog.user_email.ilike(f"%{user_email.strip()}%"))

    if date_from:
        start_dt = datetime.combine(date_from, time.min)
        query = query.filter(AuditLog.created_at >= start_dt)

    if date_to:
        end_dt = datetime.combine(date_to, time.max)
        query = query.filter(AuditLog.created_at <= end_dt)

    return query


def _extract_python_dict_after_marker(text: str, marker: str) -> dict | None:
    start = text.find(marker)

    if start < 0:
        return None

    brace_start = text.find("{", start)

    if brace_start < 0:
        return None

    depth = 0
    end = None

    for index in range(brace_start, len(text)):
        char = text[index]

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                end = index + 1
                break

    if end is None:
        return None

    raw_dict = text[brace_start:end]

    try:
        parsed = ast.literal_eval(raw_dict)

        if isinstance(parsed, dict):
            return parsed

    except Exception:
        return None

    return None


def _append_whatsapp_result(lines: list[str], data: dict | None) -> None:
    if not data:
        return

    lines.append("")
    lines.append("Notificación por WhatsApp:")
    lines.append(f"- Resultado: {'Enviada correctamente' if data.get('ok') else 'No enviada'}")

    phone = data.get("phone")

    if phone:
        lines.append(f"- Teléfono: {phone}")

    message = data.get("message")

    if message:
        lines.append("- Mensaje enviado:")
        lines.append(f"  {message}")

    send_result = data.get("send_result")

    if isinstance(send_result, dict):
        lines.append("")
        lines.append("Respuesta de Evolution API:")
        lines.append(f"- OK: {'Sí' if send_result.get('ok') else 'No'}")

        status_code = send_result.get("status_code")

        if status_code:
            lines.append(f"- Código HTTP: {status_code}")

        api_data = send_result.get("data")

        if isinstance(api_data, dict):
            key_data = api_data.get("key")

            if isinstance(key_data, dict):
                message_id = key_data.get("id")
                remote_jid = key_data.get("remoteJid")

                if message_id:
                    lines.append(f"- ID mensaje WhatsApp: {message_id}")

                if remote_jid:
                    lines.append(f"- Destino: {remote_jid}")

            status = api_data.get("status")

            if status:
                lines.append(f"- Estado Evolution: {status}")


def format_audit_detail(detail: str | None) -> str:
    if not detail:
        return "-"

    text = str(detail).strip()

    # Cambio de estado desde conversación o desde detalle.
    if "Estado cambiado" in text:
        lines = []

        conversation_match = re.search(r"conversación #(\d+)", text, flags=re.IGNORECASE)
        previous_match = re.search(r"Estado anterior=([^,\.]+)", text)
        new_match = re.search(r"estado nuevo=([^,\.]+)", text, flags=re.IGNORECASE)
        observation_match = re.search(r"Observaciones=([^\.]+)", text)

        if "desde conversación" in text:
            lines.append("Cambio de estado realizado desde el panel de mensajes.")
        elif "desde detalle" in text:
            lines.append("Cambio de estado realizado desde el detalle de la solicitud.")
        else:
            lines.append("Cambio de estado de solicitud.")

        if conversation_match:
            lines.append(f"Conversación: #{conversation_match.group(1)}")

        if previous_match:
            lines.append(f"Estado anterior: {status_label(previous_match.group(1).strip())}")

        if new_match:
            lines.append(f"Estado nuevo: {status_label(new_match.group(1).strip())}")

        if observation_match:
            observation = observation_match.group(1).strip()

            if observation and observation not in {"None", "null"}:
                lines.append(f"Observación de RRHH: {observation}")

        whatsapp_data = _extract_python_dict_after_marker(
            text,
            "Notificación WhatsApp=",
        )
        _append_whatsapp_result(lines, whatsapp_data)

        return "\n".join(lines)

    # Solicitud editada.
    if text.startswith("Solicitud editada"):
        clean = text
        clean = clean.replace("Solicitud editada.", "Solicitud editada.")
        clean = clean.replace("Tipo:", "\nTipo:")
        clean = clean.replace("Estado:", "\nEstado:")
        clean = clean.replace("Desde:", "\nDesde:")
        clean = clean.replace("Hasta:", "\nHasta:")
        clean = clean.replace("Motivo anterior:", "\nMotivo anterior:")
        clean = clean.replace("Motivo nuevo:", "\nMotivo nuevo:")
        clean = clean.replace("Observaciones anteriores:", "\nObservaciones anteriores:")
        clean = clean.replace("Observaciones nuevas:", "\nObservaciones nuevas:")
        clean = clean.replace("Persona anterior:", "\nPersona anterior:")
        clean = clean.replace("Carpeta médica por=", "\nCarpeta médica por: ")
        clean = clean.replace("DNI familiar=", "\nDNI familiar: ")
        clean = clean.replace("Familiar=", "\nFamiliar: ")
        clean = clean.replace("Parentesco=", "\nParentesco: ")
        clean = clean.replace("Notificación WhatsApp=", "\nNotificación WhatsApp: ")

        return clean.strip()

    # Solicitud creada manualmente.
    if text.startswith("Solicitud creada manualmente"):
        clean = text
        clean = clean.replace("Solicitud creada manualmente.", "Solicitud creada manualmente.")
        clean = clean.replace("Tipo=", "\nTipo: ")
        clean = clean.replace("persona_id=", "\nPersona ID: ")
        clean = clean.replace("desde=", "\nDesde: ")
        clean = clean.replace("hasta=", "\nHasta: ")
        clean = clean.replace(", ", "\n")

        return clean.strip()

    # Respuesta humana.
    if text.startswith("Respuesta humana"):
        clean = text
        clean = clean.replace("Respuesta humana enviada/registrada.", "Respuesta humana enviada o registrada.")
        clean = clean.replace("Canal=", "\nCanal: ")
        clean = clean.replace("contacto=", "\nContacto: ")
        clean = clean.replace("contenido=", "\nContenido: ")
        clean = clean.replace(", ", "\n")

        return clean.strip()

    # Persona editada.
    if text.startswith("Persona editada"):
        clean = text
        clean = clean.replace("Persona editada.", "Persona editada.")
        clean = clean.replace("Antes=", "\nDatos anteriores:\n")
        clean = clean.replace("Después=", "\nDatos nuevos:\n")

        return clean.strip()

    # Si es JSON válido.
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except Exception:
        pass

    # Si parece dict estilo Python.
    try:
        parsed = ast.literal_eval(text)

        if isinstance(parsed, dict):
            pretty_lines = []

            for key, value in parsed.items():
                label = str(key).replace("_", " ").capitalize()
                pretty_lines.append(f"{label}: {value}")

            return "\n".join(pretty_lines)

    except Exception:
        pass

    # Fallback general.
    clean = text
    clean = clean.replace(". ", ".\n")
    clean = clean.replace(", ", "\n")
    clean = clean.replace("=", ": ")

    return clean.strip()


def make_audit_preview(detail: str | None, max_length: int = 160) -> str:
    pretty = format_audit_detail(detail)

    if not pretty or pretty == "-":
        return "-"

    one_line = " ".join(pretty.split())

    if len(one_line) <= max_length:
        return one_line

    return one_line[:max_length].rstrip() + "..."


def enrich_audit_item(item: AuditLog) -> AuditLog:
    item.action_label = audit_action_label(item.action)
    item.entity_type_label = audit_entity_label(item.entity_type)
    item.description_pretty = format_audit_detail(item.description)
    item.description_preview = make_audit_preview(item.description)
    return item


@router.get("/admin/audit")
def audit_list(
    request: Request,
    action: str | None = None,
    entity_type: str | None = None,
    user_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    page = max(page, 1)

    parsed_date_from = _parse_date(date_from)
    parsed_date_to = _parse_date(date_to)

    query = db.query(AuditLog)
    query = _apply_filters(
        query=query,
        action=action,
        entity_type=entity_type,
        user_email=user_email,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )

    total_items = query.count()
    total_pages = max(ceil(total_items / PAGE_SIZE), 1)

    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    logs = [enrich_audit_item(item) for item in logs]

    raw_actions = [
        row[0]
        for row in db.query(AuditLog.action)
        .distinct()
        .order_by(AuditLog.action.asc())
        .all()
        if row[0]
    ]

    raw_entity_types = [
        row[0]
        for row in db.query(AuditLog.entity_type)
        .distinct()
        .order_by(AuditLog.entity_type.asc())
        .all()
        if row[0]
    ]

    actions = [
        {
            "value": value,
            "label": audit_action_label(value),
        }
        for value in raw_actions
    ]

    entity_types = [
        {
            "value": value,
            "label": audit_entity_label(value),
        }
        for value in raw_entity_types
    ]

    return templates.TemplateResponse(
        request,
        "audit_list.html",
        _admin_context(
            current_user,
            {
                "logs": logs,
                "actions": actions,
                "entity_types": entity_types,
                "selected_action": action or "",
                "selected_entity_type": entity_type or "",
                "user_email": user_email or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "page": page,
                "total_pages": total_pages,
                "total_items": total_items,
            },
        ),
    )


# IMPORTANTE:
# Esta ruta debe ir ANTES de /admin/audit/{audit_id}
@router.get("/admin/audit/export.csv")
def audit_export_csv(
    action: str | None = None,
    entity_type: str | None = None,
    user_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    parsed_date_from = _parse_date(date_from)
    parsed_date_to = _parse_date(date_to)

    query = db.query(AuditLog)
    query = _apply_filters(
        query=query,
        action=action,
        entity_type=entity_type,
        user_email=user_email,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )

    rows = query.order_by(AuditLog.created_at.desc()).limit(5000).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "ID",
            "Fecha",
            "Usuario ID",
            "Usuario Email",
            "Rol",
            "Acción",
            "Acción interna",
            "Entidad",
            "Entidad interna",
            "Entidad ID",
            "Detalle",
        ]
    )

    for item in rows:
        writer.writerow(
            [
                item.id,
                item.created_at,
                item.user_id or "",
                item.user_email or "",
                item.user_role or "",
                audit_action_label(item.action),
                item.action,
                audit_entity_label(item.entity_type),
                item.entity_type,
                item.entity_id or "",
                format_audit_detail(item.description),
            ]
        )

    output.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="auditoria_rrhh.csv"'
    }

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )


@router.get("/admin/audit/{audit_id}")
def audit_detail(
    audit_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    item = db.query(AuditLog).filter(AuditLog.id == audit_id).first()

    if not item:
        return RedirectResponse(url="/admin/audit", status_code=303)

    item = enrich_audit_item(item)

    return templates.TemplateResponse(
        request,
        "audit_detail.html",
        _admin_context(
            current_user,
            {
                "item": item,
            },
        ),
    )