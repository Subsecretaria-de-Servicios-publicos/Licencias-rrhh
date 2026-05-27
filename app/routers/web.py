import mimetypes
import os
import uuid
import csv
import io
from pathlib import Path
from datetime import date, datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, Form, Request, File, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    can_answer_messages,
    can_change_license_status,
    can_manage_licenses,
    can_manage_messages,
    can_manage_persons,
    can_manage_users,
    get_current_user,
    home_for_user,
)
from app.db import get_db
from app.models import Conversation, LicenseRequest, Message, Person, User
from app.services.audit_service import create_audit_log
from app.services.evolution_service import (
    get_public_base_url,
    send_whatsapp_media,
    send_whatsapp_text,
)
from app.services.notification_service import notify_license_status_by_whatsapp
from app.services.person_service import create_or_update_person, normalize_phone


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


REQUEST_TYPE_LABELS = {
    "license": "Licencias",
    "medical_folder": "Carpeta Médica",
    "other_license": "Otras Licencias",
}

STATUS_LABELS = {
    "pending": "Pendiente",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "observed": "Observada",
    "cancelled": "Cancelada",
}

PAGE_SIZE = 10


def _redirect_login():
    return RedirectResponse(url="/login", status_code=303)


def _redirect_home(current_user: User | None):
    return RedirectResponse(url=home_for_user(current_user), status_code=303)


def _ensure_login(current_user: User | None):
    if not current_user:
        return _redirect_login()
    return None


def _ensure_licenses(current_user: User | None):
    if not current_user:
        return _redirect_login()
    if not can_manage_licenses(current_user):
        return _redirect_home(current_user)
    return None


def _ensure_persons(current_user: User | None):
    if not current_user:
        return _redirect_login()
    if not can_manage_persons(current_user):
        return _redirect_home(current_user)
    return None


def _ensure_messages(current_user: User | None):
    if not current_user:
        return _redirect_login()
    if not can_manage_messages(current_user):
        return _redirect_home(current_user)
    return None


def _ensure_license_status(current_user: User | None):
    if not current_user:
        return _redirect_login()
    if not can_change_license_status(current_user):
        return _redirect_home(current_user)
    return None


def _ensure_answer_messages(current_user: User | None):
    if not current_user:
        return _redirect_login()
    if not can_answer_messages(current_user):
        return _redirect_home(current_user)
    return None


def _template_context(current_user: User | None, extra: dict | None = None) -> dict:
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


def _display_end_date(item: LicenseRequest) -> str:
    if item.end_date:
        return str(item.end_date)

    if item.request_type == "medical_folder":
        return "Pendiente de cierre"

    return ""


def _as_aware_utc(value):
    if not value:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _message_is_unread_for_admin(message: Message, conversation: Conversation) -> bool:
    if message.sender_type != "user":
        return False

    if not message.created_at:
        return False

    if not conversation.admin_last_read_at:
        return True

    message_at = _as_aware_utc(message.created_at)
    read_at = _as_aware_utc(conversation.admin_last_read_at)

    if not message_at or not read_at:
        return False

    return message_at > read_at


def _enrich_conversation_for_messages_list(conversation: Conversation) -> Conversation:
    sorted_messages = sorted(
        conversation.messages or [],
        key=lambda msg: (msg.created_at or datetime.min, msg.id or 0),
    )

    last_message = sorted_messages[-1] if sorted_messages else None

    conversation.last_message_preview = (
        (last_message.content or "").strip()
        if last_message
        else ""
    )

    conversation.last_message_at = (
        last_message.created_at
        if last_message
        else conversation.created_at
    )

    conversation.unread_count = sum(
        1
        for message in sorted_messages
        if _message_is_unread_for_admin(message, conversation)
    )

    return conversation


def _sort_conversations_for_messages(conversations: list[Conversation]) -> list[Conversation]:
    enriched = [
        _enrich_conversation_for_messages_list(conversation)
        for conversation in conversations
    ]

    return sorted(
        enriched,
        key=lambda conversation: (
            conversation.last_message_at or conversation.created_at or datetime.min,
            conversation.id or 0,
        ),
        reverse=True,
    )


def _mark_conversation_as_read(db: Session, conversation: Conversation) -> None:
    conversation.admin_last_read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)


@router.get("/admin")
def admin_dashboard(
    request: Request,
    latest_page: int = 1,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_login(current_user)

    if redirect:
        return redirect

    if current_user and current_user.role == "OPERADOR":
        return RedirectResponse(url="/admin/messages", status_code=303)

    latest_page = max(latest_page, 1)
    latest_page_size = 8

    total_persons = db.query(Person).count()
    total_requests = db.query(LicenseRequest).count()

    total_licenses = (
        db.query(LicenseRequest)
        .filter(LicenseRequest.request_type == "license")
        .count()
    )

    total_medical = (
        db.query(LicenseRequest)
        .filter(LicenseRequest.request_type == "medical_folder")
        .count()
    )

    total_other = (
        db.query(LicenseRequest)
        .filter(LicenseRequest.request_type == "other_license")
        .count()
    )

    pending_requests = (
        db.query(LicenseRequest)
        .filter(LicenseRequest.status == "pending")
        .count()
    )

    latest_total_items = db.query(LicenseRequest).count()
    latest_total_pages = max(ceil(latest_total_items / latest_page_size), 1)

    if latest_page > latest_total_pages:
        latest_page = latest_total_pages

    latest_requests = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .order_by(LicenseRequest.created_at.desc(), LicenseRequest.id.desc())
        .offset((latest_page - 1) * latest_page_size)
        .limit(latest_page_size)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _template_context(
            current_user,
            {
                "total_persons": total_persons,
                "total_requests": total_requests,
                "total_licenses": total_licenses,
                "total_medical": total_medical,
                "total_other": total_other,
                "pending_requests": pending_requests,
                "latest_requests": latest_requests,
                "latest_page": latest_page,
                "latest_total_pages": latest_total_pages,
                "latest_total_items": latest_total_items,
                "latest_page_size": latest_page_size,
                "request_type_labels": REQUEST_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
            },
        ),
    )


@router.get("/admin/licenses")
def license_list(
    request: Request,
    type: str | None = None,
    status: str | None = None,
    person_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    page = max(page, 1)

    selected_person = None

    if person_id:
        selected_person = db.query(Person).filter(Person.id == person_id).first()

    query = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .join(Person)
    )

    if type:
        query = query.filter(LicenseRequest.request_type == type)

    if status:
        query = query.filter(LicenseRequest.status == status)

    if person_id:
        query = query.filter(LicenseRequest.person_id == person_id)

    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Person.dni.ilike(search),
                Person.first_name.ilike(search),
                Person.last_name.ilike(search),
                Person.phone.ilike(search),
                Person.department.ilike(search),
            )
        )

    total_items = query.count()
    total_pages = max(ceil(total_items / PAGE_SIZE), 1)

    if page > total_pages:
        page = total_pages

    requests = (
        query.order_by(LicenseRequest.created_at.desc(), LicenseRequest.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    title = "Todas las solicitudes"

    if type in REQUEST_TYPE_LABELS:
        title = REQUEST_TYPE_LABELS[type]

    if selected_person:
        title = f"Solicitudes de {selected_person.first_name} {selected_person.last_name}"

    return templates.TemplateResponse(
        request,
        "license_list.html",
        _template_context(
            current_user,
            {
                "requests": requests,
                "title": title,
                "selected_type": type or "",
                "selected_status": status or "",
                "selected_person_id": person_id,
                "selected_person": selected_person,
                "q": q or "",
                "page": page,
                "total_pages": total_pages,
                "total_items": total_items,
                "request_type_labels": REQUEST_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "display_end_date": _display_end_date,
            },
        ),
    )


@router.get("/admin/licenses/export.csv")
def license_export_csv(
    type: str | None = None,
    status: str | None = None,
    person_id: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    query = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .join(Person)
    )

    if type:
        query = query.filter(LicenseRequest.request_type == type)

    if status:
        query = query.filter(LicenseRequest.status == status)

    if person_id:
        query = query.filter(LicenseRequest.person_id == person_id)

    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Person.dni.ilike(search),
                Person.first_name.ilike(search),
                Person.last_name.ilike(search),
                Person.phone.ilike(search),
                Person.department.ilike(search),
            )
        )

    rows = query.order_by(LicenseRequest.created_at.desc(), LicenseRequest.id.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "ID",
            "Nombre",
            "Apellido",
            "DNI",
            "Telefono",
            "Email",
            "Area",
            "Legajo",
            "Tipo",
            "Estado",
            "Desde",
            "Hasta",
            "Motivo",
            "Carpeta médica por",
            "DNI familiar",
            "Nombre familiar",
            "Parentesco",
            "Observaciones",
            "Creado",
        ]
    )

    for item in rows:
        writer.writerow(
            [
                item.id,
                item.person.first_name if item.person else "",
                item.person.last_name if item.person else "",
                item.person.dni if item.person else "",
                item.person.phone if item.person and item.person.phone else "",
                item.person.email if item.person and item.person.email else "",
                item.person.department if item.person and item.person.department else "",
                item.person.employee_number if item.person and item.person.employee_number else "",
                REQUEST_TYPE_LABELS.get(item.request_type, item.request_type),
                STATUS_LABELS.get(item.status, item.status),
                item.start_date,
                item.end_date or "",
                item.reason or "",
                item.medical_folder_for or "",
                item.family_member_dni or "",
                item.family_member_full_name or "",
                item.family_relationship or "",
                item.admin_notes or "",
                item.created_at,
            ]
        )

    output.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="solicitudes_licencias.csv"'
    }

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )


@router.get("/admin/licenses/new")
def license_new_form(
    request: Request,
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "license_form.html",
        _template_context(
            current_user,
            {
                "request_type_labels": REQUEST_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
            },
        ),
    )


@router.post("/admin/licenses/new")
def license_create(
    first_name: str = Form(...),
    last_name: str = Form(...),
    dni: str = Form(...),
    phone: str | None = Form(None),
    email: str | None = Form(None),
    department: str | None = Form(None),
    employee_number: str | None = Form(None),
    request_type: str = Form(...),
    start_date: date = Form(...),
    end_date: date | None = Form(None),
    reason: str | None = Form(None),
    admin_notes: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    person = create_or_update_person(
        db=db,
        first_name=first_name,
        last_name=last_name,
        dni=dni,
        phone=phone,
        email=email,
        department=department,
        employee_number=employee_number,
        assistant_enabled=True,
    )

    if request_type == "medical_folder":
        end_date = None

    if request_type != "medical_folder" and not end_date:
        end_date = start_date

    item = LicenseRequest(
        person_id=person.id,
        request_type=request_type,
        status="pending",
        start_date=start_date,
        end_date=end_date,
        reason=reason.strip() if reason else None,
        admin_notes=admin_notes.strip() if admin_notes else None,
        medical_folder_for="agent" if request_type == "medical_folder" else None,
    )

    db.add(item)
    db.flush()

    create_audit_log(
        db=db,
        current_user=current_user,
        action="license_created_manual",
        entity_type="license_request",
        entity_id=item.id,
        description=(
            f"Solicitud creada manualmente. "
            f"Tipo={request_type}, persona_id={person.id}, "
            f"desde={start_date}, hasta={end_date}."
        ),
    )

    db.commit()

    return RedirectResponse(
        url=f"/admin/licenses?type={request_type}",
        status_code=303,
    )


@router.get("/admin/licenses/{license_id}")
def license_detail(
    license_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    item = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .filter(LicenseRequest.id == license_id)
        .first()
    )

    if not item:
        return RedirectResponse(url="/admin/licenses", status_code=303)

    return templates.TemplateResponse(
        request,
        "license_detail.html",
        _template_context(
            current_user,
            {
                "item": item,
                "request_type_labels": REQUEST_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "display_end_date": _display_end_date,
            },
        ),
    )


@router.get("/admin/licenses/{license_id}/edit")
def license_edit_form(
    license_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    item = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .filter(LicenseRequest.id == license_id)
        .first()
    )

    if not item:
        return RedirectResponse(url="/admin/licenses", status_code=303)

    return templates.TemplateResponse(
        request,
        "license_edit.html",
        _template_context(
            current_user,
            {
                "item": item,
                "return_to": return_to or "",
                "request_type_labels": REQUEST_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "display_end_date": _display_end_date,
            },
        ),
    )


@router.post("/admin/licenses/{license_id}/edit")
def license_edit_save(
    license_id: int,
    request_type: str = Form(...),
    status: str = Form(...),
    start_date: date = Form(...),
    end_date: date | None = Form(None),
    reason: str | None = Form(None),
    admin_notes: str | None = Form(None),
    medical_folder_for: str | None = Form(None),
    family_member_dni: str | None = Form(None),
    family_member_full_name: str | None = Form(None),
    family_relationship: str | None = Form(None),
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str | None = Form(None),
    email: str | None = Form(None),
    department: str | None = Form(None),
    employee_number: str | None = Form(None),
    return_to: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_licenses(current_user)

    if redirect:
        return redirect

    item = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .filter(LicenseRequest.id == license_id)
        .first()
    )

    if not item:
        return RedirectResponse(url="/admin/licenses", status_code=303)

    old_request_type = item.request_type
    old_status = item.status
    old_start_date = item.start_date
    old_end_date = item.end_date
    old_reason = item.reason
    old_admin_notes = item.admin_notes

    old_person_data = None

    if item.person:
        old_person_data = {
            "first_name": item.person.first_name,
            "last_name": item.person.last_name,
            "phone": item.person.phone,
            "email": item.person.email,
            "department": item.person.department,
            "employee_number": item.person.employee_number,
        }

    if request_type in REQUEST_TYPE_LABELS:
        item.request_type = request_type

    if status in STATUS_LABELS:
        item.status = status

    if item.request_type == "medical_folder":
        end_date = end_date or None

    if item.request_type != "medical_folder" and not end_date:
        end_date = start_date

    item.start_date = start_date
    item.end_date = end_date
    item.reason = reason.strip() if reason else None
    item.admin_notes = admin_notes.strip() if admin_notes else None

    if item.request_type == "medical_folder":
        item.medical_folder_for = medical_folder_for or None

        if item.medical_folder_for == "family":
            item.family_member_dni = family_member_dni.strip() if family_member_dni else None
            item.family_member_full_name = (
                family_member_full_name.strip()
                if family_member_full_name
                else None
            )
            item.family_relationship = family_relationship.strip() if family_relationship else None
        else:
            item.family_member_dni = None
            item.family_member_full_name = None
            item.family_relationship = None
    else:
        item.medical_folder_for = None
        item.family_member_dni = None
        item.family_member_full_name = None
        item.family_relationship = None

    if item.person:
        item.person.first_name = first_name.strip()
        item.person.last_name = last_name.strip()
        item.person.phone = normalize_phone(phone)
        item.person.email = email.strip() if email else None
        item.person.department = department.strip() if department else None
        item.person.employee_number = employee_number.strip() if employee_number else None

    notify_result = None

    if old_status != item.status:
        notify_result = notify_license_status_by_whatsapp(item)

    create_audit_log(
        db=db,
        current_user=current_user,
        action="license_edited",
        entity_type="license_request",
        entity_id=item.id,
        description=(
            "Solicitud editada. "
            f"Tipo: {old_request_type} -> {item.request_type}. "
            f"Estado: {old_status} -> {item.status}. "
            f"Desde: {old_start_date} -> {item.start_date}. "
            f"Hasta: {old_end_date} -> {item.end_date}. "
            f"Motivo anterior: {old_reason}. Motivo nuevo: {item.reason}. "
            f"Observaciones anteriores: {old_admin_notes}. "
            f"Observaciones nuevas: {item.admin_notes}. "
            f"Persona anterior: {old_person_data}. "
            f"Carpeta médica por={item.medical_folder_for}. "
            f"DNI familiar={item.family_member_dni}. "
            f"Familiar={item.family_member_full_name}. "
            f"Parentesco={item.family_relationship}. "
            f"Notificación WhatsApp={notify_result}."
        ),
    )

    db.commit()

    if return_to:
        return RedirectResponse(url=return_to, status_code=303)

    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)


@router.post("/admin/licenses/{license_id}/status")
def license_update_status(
    license_id: int,
    status: str = Form(...),
    admin_notes: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_license_status(current_user)

    if redirect:
        return redirect

    item = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .filter(LicenseRequest.id == license_id)
        .first()
    )

    if not item:
        return RedirectResponse(url="/admin/licenses", status_code=303)

    old_status = item.status

    if status in STATUS_LABELS:
        item.status = status

    item.admin_notes = admin_notes.strip() if admin_notes else None

    notify_result = None

    if old_status != item.status:
        notify_result = notify_license_status_by_whatsapp(item)

    create_audit_log(
        db=db,
        current_user=current_user,
        action="license_status_changed",
        entity_type="license_request",
        entity_id=item.id,
        description=(
            f"Estado cambiado desde detalle. "
            f"Estado anterior={old_status}, estado nuevo={item.status}. "
            f"Observaciones={item.admin_notes}. "
            f"Notificación WhatsApp={notify_result}."
        ),
    )

    db.commit()

    return RedirectResponse(url=f"/admin/licenses/{license_id}", status_code=303)


@router.get("/admin/messages")
def conversations_list(
    request: Request,
    conversation_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_messages(current_user)

    if redirect:
        return redirect

    conversations = (
        db.query(Conversation)
        .options(joinedload(Conversation.person), joinedload(Conversation.messages))
        .all()
    )

    conversations = _sort_conversations_for_messages(conversations)

    selected_conversation = None

    if conversations:
        if conversation_id:
            selected_conversation = next(
                (conversation for conversation in conversations if conversation.id == conversation_id),
                None,
            )

        if not selected_conversation:
            selected_conversation = conversations[0]

    messages = []
    person_requests = []

    if selected_conversation:
        _mark_conversation_as_read(db, selected_conversation)

        selected_conversation = (
            db.query(Conversation)
            .options(joinedload(Conversation.person), joinedload(Conversation.messages))
            .filter(Conversation.id == selected_conversation.id)
            .first()
        )

        conversations = (
            db.query(Conversation)
            .options(joinedload(Conversation.person), joinedload(Conversation.messages))
            .all()
        )
        conversations = _sort_conversations_for_messages(conversations)

        for conversation in conversations:
            if conversation.id == selected_conversation.id:
                conversation.unread_count = 0
                selected_conversation = conversation
                break

        messages = sorted(
            selected_conversation.messages or [],
            key=lambda msg: (msg.created_at or datetime.min, msg.id or 0),
        )

        if selected_conversation.person_id:
            person_requests = (
                db.query(LicenseRequest)
                .filter(LicenseRequest.person_id == selected_conversation.person_id)
                .order_by(LicenseRequest.created_at.desc())
                .limit(10)
                .all()
            )

    return templates.TemplateResponse(
        request,
        "messages_list.html",
        _template_context(
            current_user,
            {
                "conversations": conversations,
                "selected_conversation": selected_conversation,
                "messages": messages,
                "person_requests": person_requests,
                "request_type_labels": REQUEST_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "display_end_date": _display_end_date,
            },
        ),
    )


@router.get("/admin/messages/{conversation_id}")
def conversation_detail(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_messages(current_user)

    if redirect:
        return redirect

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )

    if not conversation:
        return RedirectResponse(url="/admin/messages", status_code=303)

    return RedirectResponse(
        url=f"/admin/messages?conversation_id={conversation_id}",
        status_code=303,
    )


@router.post("/admin/messages/{conversation_id}/pause")
def pause_assistant(
    conversation_id: int,
    pause_reason: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_messages(current_user)

    if redirect:
        return redirect

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )

    if not conversation:
        return RedirectResponse(url="/admin/messages", status_code=303)

    conversation.assistant_paused = True
    conversation.pause_reason = pause_reason or "Pausado por operador"

    create_audit_log(
        db=db,
        current_user=current_user,
        action="assistant_paused",
        entity_type="conversation",
        entity_id=conversation.id,
        description=(
            f"Asistente pausado. "
            f"Motivo={conversation.pause_reason}. "
            f"Persona_id={conversation.person_id}."
        ),
    )

    db.commit()

    return RedirectResponse(
        url=f"/admin/messages?conversation_id={conversation_id}",
        status_code=303,
    )


@router.post("/admin/messages/{conversation_id}/resume")
def resume_assistant(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_messages(current_user)

    if redirect:
        return redirect

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )

    if not conversation:
        return RedirectResponse(url="/admin/messages", status_code=303)

    conversation.assistant_paused = False
    conversation.pause_reason = None

    if conversation.person:
        conversation.person.assistant_enabled = True

    create_audit_log(
        db=db,
        current_user=current_user,
        action="assistant_resumed",
        entity_type="conversation",
        entity_id=conversation.id,
        description=(
            f"Asistente reanudado. "
            f"Persona_id={conversation.person_id}."
        ),
    )

    db.commit()

    return RedirectResponse(
        url=f"/admin/messages?conversation_id={conversation_id}",
        status_code=303,
    )


UPLOAD_MESSAGES_DIR = Path("app/static/uploads/messages")

MAX_MESSAGE_ATTACHMENT_SIZE = 12 * 1024 * 1024

ALLOWED_MESSAGE_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
}


def _safe_filename(filename: str | None) -> str:
    raw = filename or "archivo"
    raw = raw.replace("\\", "_").replace("/", "_").strip()

    if not raw:
        raw = "archivo"

    return raw


def _detect_attachment_kind(mime_type: str | None, filename: str | None = None) -> str:
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


async def _save_message_attachment(
    conversation_id: int,
    attachment: UploadFile | None,
) -> dict | None:
    if not attachment or not attachment.filename:
        return None

    original_name = _safe_filename(attachment.filename)
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_MESSAGE_ATTACHMENT_EXTENSIONS:
        raise ValueError(
            "Tipo de archivo no permitido. Permitidos: PDF, imágenes, Word, Excel y TXT."
        )

    content = await attachment.read()

    if len(content) > MAX_MESSAGE_ATTACHMENT_SIZE:
        raise ValueError("El archivo supera el tamaño máximo permitido de 12 MB.")

    mime_type = attachment.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    target_dir = UPLOAD_MESSAGES_DIR / str(conversation_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{extension}"
    stored_path = target_dir / stored_name

    stored_path.write_bytes(content)

    relative_path = f"/static/uploads/messages/{conversation_id}/{stored_name}"

    return {
        "original_name": original_name,
        "relative_path": relative_path,
        "mime_type": mime_type,
        "kind": _detect_attachment_kind(mime_type, original_name),
    }


def _build_public_file_url(relative_path: str) -> str:
    base_url = get_public_base_url()

    if not base_url:
        return relative_path

    return f"{base_url.rstrip('/')}{relative_path}"


@router.post("/admin/messages/{conversation_id}/reply")
async def human_reply(
    conversation_id: int,
    content: str | None = Form(None),
    attachment: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_answer_messages(current_user)

    if redirect:
        return redirect

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )

    if not conversation:
        return RedirectResponse(url="/admin/messages", status_code=303)

    clean_content = (content or "").strip()

    attachment_data = None

    try:
        attachment_data = await _save_message_attachment(
            conversation_id=conversation.id,
            attachment=attachment,
        )
    except ValueError as exc:
        system_message = Message(
            conversation_id=conversation.id,
            sender_type="system",
            content=f"No se pudo adjuntar el archivo. {exc}",
        )
        db.add(system_message)
        db.commit()

        return RedirectResponse(
            url=f"/admin/messages?conversation_id={conversation_id}",
            status_code=303,
        )

    if not clean_content and not attachment_data:
        return RedirectResponse(
            url=f"/admin/messages?conversation_id={conversation_id}",
            status_code=303,
        )

    human_content = clean_content

    if attachment_data and not human_content:
        human_content = f"Archivo adjunto: {attachment_data['original_name']}"

    human_message = Message(
        conversation_id=conversation.id,
        sender_type="human",
        content=human_content,
        attachment_name=attachment_data["original_name"] if attachment_data else None,
        attachment_path=attachment_data["relative_path"] if attachment_data else None,
        attachment_mime_type=attachment_data["mime_type"] if attachment_data else None,
        attachment_kind=attachment_data["kind"] if attachment_data else None,
    )
    db.add(human_message)

    conversation.assistant_paused = True
    conversation.pause_reason = "Respondido por operador humano"
    conversation.admin_last_read_at = datetime.now(timezone.utc)

    send_result = None

    if conversation.channel == "whatsapp" and conversation.external_contact:
        if attachment_data:
            public_file_url = _build_public_file_url(attachment_data["relative_path"])

            send_result = send_whatsapp_media(
                phone=conversation.external_contact,
                media_url=public_file_url,
                filename=attachment_data["original_name"],
                mime_type=attachment_data["mime_type"],
                caption=clean_content or "",
            )
        else:
            send_result = send_whatsapp_text(
                conversation.external_contact,
                clean_content,
            )

        print("HUMAN_REPLY_SEND_RESULT:", send_result)

        if send_result.get("ok"):
            system_message = Message(
                conversation_id=conversation.id,
                sender_type="system",
                content="Respuesta humana enviada por WhatsApp correctamente.",
            )
            db.add(system_message)
        else:
            system_message = Message(
                conversation_id=conversation.id,
                sender_type="system",
                content=f"No se pudo enviar la respuesta por WhatsApp. Error: {send_result}",
            )
            db.add(system_message)
    else:
        system_message = Message(
            conversation_id=conversation.id,
            sender_type="system",
            content=(
                "La respuesta quedó guardada, pero no se envió por WhatsApp "
                "porque la conversación no tiene canal whatsapp o contacto externo."
            ),
        )
        db.add(system_message)

    create_audit_log(
        db=db,
        current_user=current_user,
        action="human_reply_sent",
        entity_type="conversation",
        entity_id=conversation.id,
        description=(
            f"Respuesta humana enviada/registrada. "
            f"Canal={conversation.channel}, contacto={conversation.external_contact}, "
            f"contenido={clean_content[:250]}, "
            f"adjunto={attachment_data['original_name'] if attachment_data else None}, "
            f"resultado={send_result}."
        ),
    )

    db.commit()

    return RedirectResponse(
        url=f"/admin/messages?conversation_id={conversation_id}",
        status_code=303,
    )


@router.post("/admin/messages/{conversation_id}/requests/{license_id}/status")
def message_license_update_status(
    conversation_id: int,
    license_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_license_status(current_user)

    if redirect:
        return redirect

    item = (
        db.query(LicenseRequest)
        .options(joinedload(LicenseRequest.person))
        .filter(LicenseRequest.id == license_id)
        .first()
    )

    if not item:
        return RedirectResponse(
            url=f"/admin/messages?conversation_id={conversation_id}",
            status_code=303,
        )

    old_status = item.status

    if status in STATUS_LABELS:
        item.status = status

        notify_result = None

        if old_status != item.status:
            notify_result = notify_license_status_by_whatsapp(item)

        create_audit_log(
            db=db,
            current_user=current_user,
            action="license_status_changed_from_conversation",
            entity_type="license_request",
            entity_id=item.id,
            description=(
                f"Estado cambiado desde conversación #{conversation_id}. "
                f"Estado anterior={old_status}, estado nuevo={item.status}. "
                f"Notificación WhatsApp={notify_result}."
            ),
        )

        if notify_result and notify_result.get("ok"):
            system_message = Message(
                conversation_id=conversation_id,
                sender_type="system",
                content=(
                    "Se notificó al empleado por WhatsApp sobre el cambio de estado "
                    f"de la solicitud #{item.id}."
                ),
            )
            db.add(system_message)

        elif notify_result:
            system_message = Message(
                conversation_id=conversation_id,
                sender_type="system",
                content=(
                    "No se pudo notificar por WhatsApp el cambio de estado "
                    f"de la solicitud #{item.id}. Error: {notify_result}"
                ),
            )
            db.add(system_message)

        db.commit()

    return RedirectResponse(
        url=f"/admin/messages?conversation_id={conversation_id}",
        status_code=303,
    )


@router.get("/admin/persons")
def persons_list(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_persons(current_user)

    if redirect:
        return redirect

    query = db.query(Person)

    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Person.dni.ilike(search),
                Person.first_name.ilike(search),
                Person.last_name.ilike(search),
                Person.phone.ilike(search),
            )
        )

    persons = query.order_by(Person.created_at.desc()).all()

    return templates.TemplateResponse(
        request,
        "persons_list.html",
        _template_context(
            current_user,
            {
                "persons": persons,
                "q": q or "",
            },
        ),
    )


@router.get("/admin/persons/new")
def person_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_persons(current_user)

    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "person_detail.html",
        _template_context(
            current_user,
            {
                "person": None,
                "is_new": True,
            },
        ),
    )


@router.post("/admin/persons/new")
def person_create(
    first_name: str = Form(...),
    last_name: str = Form(...),
    dni: str = Form(...),
    phone: str | None = Form(None),
    email: str | None = Form(None),
    department: str | None = Form(None),
    employee_number: str | None = Form(None),
    assistant_enabled: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_persons(current_user)

    if redirect:
        return redirect

    clean_dni = (dni or "").strip()
    clean_phone = normalize_phone(phone)

    existing = db.query(Person).filter(Person.dni == clean_dni).first()

    if existing:
        return RedirectResponse(f"/admin/persons/{existing.id}", status_code=303)

    person = Person(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        dni=clean_dni,
        phone=clean_phone,
        email=email.strip() if email else None,
        department=department.strip() if department else None,
        employee_number=employee_number.strip() if employee_number else None,
        assistant_enabled=assistant_enabled == "true",
    )

    db.add(person)
    db.flush()

    create_audit_log(
        db=db,
        current_user=current_user,
        action="person_created",
        entity_type="person",
        entity_id=person.id,
        description=(
            f"Persona creada manualmente. "
            f"Nombre={person.first_name} {person.last_name}, "
            f"DNI={person.dni}, "
            f"Teléfono={person.phone or '-'}."
        ),
    )

    db.commit()

    return RedirectResponse(f"/admin/persons/{person.id}", status_code=303)


@router.get("/admin/persons/{person_id}")
def person_detail(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_persons(current_user)

    if redirect:
        return redirect

    person = db.query(Person).filter(Person.id == person_id).first()

    if not person:
        return RedirectResponse("/admin/persons", status_code=303)

    return templates.TemplateResponse(
        request,
        "person_detail.html",
        _template_context(
            current_user,
            {
                "person": person,
                "is_new": False,
            },
        ),
    )


@router.post("/admin/persons/{person_id}")
def person_update(
    person_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str | None = Form(None),
    email: str | None = Form(None),
    department: str | None = Form(None),
    employee_number: str | None = Form(None),
    assistant_enabled: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _ensure_persons(current_user)

    if redirect:
        return redirect

    person = db.query(Person).filter(Person.id == person_id).first()

    if not person:
        return RedirectResponse("/admin/persons", status_code=303)

    old_data = {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "phone": person.phone,
        "email": person.email,
        "department": person.department,
        "employee_number": person.employee_number,
        "assistant_enabled": person.assistant_enabled,
    }

    person.first_name = first_name.strip()
    person.last_name = last_name.strip()
    person.phone = normalize_phone(phone)
    person.email = email.strip() if email else None
    person.department = department.strip() if department else None
    person.employee_number = employee_number.strip() if employee_number else None
    person.assistant_enabled = assistant_enabled == "true"

    new_data = {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "phone": person.phone,
        "email": person.email,
        "department": person.department,
        "employee_number": person.employee_number,
        "assistant_enabled": person.assistant_enabled,
    }

    create_audit_log(
        db=db,
        current_user=current_user,
        action="person_edited",
        entity_type="person",
        entity_id=person.id,
        description=(
            f"Persona editada. "
            f"Antes={old_data}. Después={new_data}."
        ),
    )

    db.commit()

    return RedirectResponse(f"/admin/persons/{person_id}", status_code=303)