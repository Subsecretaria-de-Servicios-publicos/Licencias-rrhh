from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conversation, Person
from app.services.assistant_service import (
    build_context_text,
    build_conversational_reply,
    build_created_request_reply,
    get_assistant_block_reason,
    save_message,
    should_assistant_reply,
    try_create_license_request_from_message,
    update_person_from_message,
)
from app.services.evolution_service import normalize_whatsapp_number, send_whatsapp_text
from app.services.person_service import normalize_phone

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


def extract_message_text(data: dict) -> str | None:
    message = data.get("message") or {}

    if isinstance(message.get("conversation"), str):
        return message.get("conversation")

    extended = message.get("extendedTextMessage") or {}

    if isinstance(extended.get("text"), str):
        return extended.get("text")

    return None


def extract_remote_jid(data: dict) -> str | None:
    key = data.get("key") or {}
    return key.get("remoteJid")


def extract_push_name(data: dict) -> str | None:
    return data.get("pushName")


def split_name(full_name: str | None) -> tuple[str, str]:
    if not full_name:
        return "Sin nombre", "Sin apellido"

    parts = full_name.strip().split(" ", 1)

    if len(parts) == 1:
        return parts[0], "Sin apellido"

    return parts[0], parts[1]


@router.post("/webhook")
async def evolution_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    print("EVOLUTION WEBHOOK PAYLOAD:", payload)

    event = payload.get("event")
    event_normalized = str(event or "").lower().replace("_", ".")

    data = payload.get("data") or {}

    if event_normalized not in ["messages.upsert", "messages_upsert"]:
        return {
            "ok": True,
            "ignored": True,
            "reason": "Evento no procesado",
            "event": event,
        }

    key = data.get("key") or {}

    if key.get("fromMe"):
        return {
            "ok": True,
            "ignored": True,
            "reason": "Mensaje propio",
        }

    text = extract_message_text(data)
    remote_jid = extract_remote_jid(data)

    if not text or not remote_jid:
        return {
            "ok": True,
            "ignored": True,
            "reason": "Sin texto o contacto",
        }

    phone = normalize_whatsapp_number(remote_jid)
    phone = normalize_phone(phone)

    push_name = extract_push_name(data)
    first_name, last_name = split_name(push_name)

    person = (
        db.query(Person)
        .filter(
            (Person.phone == phone)
            | (Person.dni == phone)
        )
        .first()
    )

    if not person:
        person = Person(
            first_name=first_name,
            last_name=last_name,
            dni=phone,
            phone=phone,
            assistant_enabled=True,
        )
        db.add(person)
        db.flush()

    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.channel == "whatsapp",
            Conversation.external_contact == phone,
        )
        .order_by(Conversation.created_at.desc())
        .first()
    )

    if not conversation:
        conversation = Conversation(
            person_id=person.id,
            channel="whatsapp",
            external_contact=phone,
            assistant_paused=False,
        )
        db.add(conversation)
        db.flush()

    # Si por algún motivo la conversación quedó sin persona vinculada,
    # la reparamos.
    if not conversation.person_id:
        conversation.person_id = person.id
        db.flush()

    # 1) Guardar mensaje entrante.
    save_message(
        db=db,
        conversation_id=conversation.id,
        sender_type="user",
        content=text,
    )

    assistant_response = None
    created_request = None
    send_result = None

    assistant_block_reason = get_assistant_block_reason(conversation, person)
    assistant_will_reply = should_assistant_reply(conversation, person)

    print(
        "EVOLUTION ASSISTANT DECISION:",
        {
            "conversation_id": conversation.id,
            "person_id": person.id if person else None,
            "assistant_will_reply": assistant_will_reply,
            "assistant_block_reason": assistant_block_reason,
            "conversation_assistant_paused": conversation.assistant_paused,
            "person_assistant_enabled": person.assistant_enabled if person else None,
        },
    )

    if assistant_will_reply:
        # 2) Actualizar persona con DNI/nombre si el usuario lo mandó.
        update_person_from_message(person, text)

        # 3) Construir contexto del historial, pero la lógica del service
        # evita reutilizar datos viejos cuando el usuario inicia un trámite nuevo.
        context_text = build_context_text(conversation, text)
        print(
            "EVOLUTION ASSISTANT CONTEXT:",
            {
                "conversation_id": conversation.id,
                "context_length": len(context_text or ""),
                "incoming_text": text,
            },
        )

        # 4) Intentar crear solicitud. Si faltan datos, devuelve None.
        created_request = try_create_license_request_from_message(
            db=db,
            person=person,
            content=text,
            context_text=context_text,
            conversation=conversation,
        )

        if created_request:
            assistant_response = build_created_request_reply(created_request)
        else:
            assistant_response = build_conversational_reply(
                person=person,
                conversation=conversation,
                content=text,
            )

        print(
            "EVOLUTION ASSISTANT RESPONSE BUILT:",
            {
                "conversation_id": conversation.id,
                "has_response": bool(assistant_response),
                "response": assistant_response,
                "created_request_id": created_request.id if created_request else None,
            },
        )

        if assistant_response:
            save_message(
                db=db,
                conversation_id=conversation.id,
                sender_type="assistant",
                content=assistant_response,
            )

    db.commit()

    # 6) Enviar por WhatsApp después del commit.
    if assistant_response:
        send_result = send_whatsapp_text(phone, assistant_response)

        print(
            "EVOLUTION ASSISTANT SEND RESULT:",
            {
                "conversation_id": conversation.id,
                "phone": phone,
                "send_result": send_result,
            },
        )
    else:
        print(
            "EVOLUTION ASSISTANT SEND SKIPPED:",
            {
                "conversation_id": conversation.id,
                "assistant_will_reply": assistant_will_reply,
                "assistant_block_reason": assistant_block_reason,
                "has_response": bool(assistant_response),
            },
        )

    return {
        "ok": True,
        "conversation_id": conversation.id,
        "assistant_will_reply": assistant_will_reply,
        "assistant_block_reason": assistant_block_reason,
        "assistant_response": assistant_response,
        "created_license_request_id": created_request.id if created_request else None,
        "send_result": send_result,
    }