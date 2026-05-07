from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conversation, Person
from app.services.assistant_service import (
    build_context_text,
    build_conversational_reply,
    build_created_request_reply,
    save_message,
    should_assistant_reply,
    try_create_license_request_from_message,
    update_person_from_message,
)
from app.services.person_service import create_or_update_person, find_person_by_dni

router = APIRouter(prefix="/api/messages", tags=["messages"])


class InboundMessage(BaseModel):
    channel: str = "web"
    external_contact: str
    content: str
    dni: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@router.post("/inbound")
def inbound_message(payload: InboundMessage, db: Session = Depends(get_db)):
    person = None

    if payload.dni:
        person = create_or_update_person(
            db=db,
            first_name=payload.first_name or "Sin nombre",
            last_name=payload.last_name or "Sin apellido",
            dni=payload.dni,
            phone=payload.external_contact,
            assistant_enabled=True,
        )

    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.channel == payload.channel,
            Conversation.external_contact == payload.external_contact,
        )
        .order_by(Conversation.created_at.desc())
        .first()
    )

    if not conversation:
        conversation = Conversation(
            person_id=person.id if person else None,
            channel=payload.channel,
            external_contact=payload.external_contact,
            assistant_paused=False,
        )
        db.add(conversation)
        db.flush()

    if person and not conversation.person_id:
        conversation.person_id = person.id

    save_message(
        db=db,
        conversation_id=conversation.id,
        sender_type="user",
        content=payload.content,
    )

    created_request = None
    assistant_response = None
    assistant_will_reply = should_assistant_reply(conversation, person)

    if assistant_will_reply:
        context_text = " ".join(
        msg.content for msg in conversation.messages[-10:]
        if msg.content
    )

    update_person_from_message(person, payload.content)

    if should_request_identity_before_creating(
        person=person,
        content=payload.content,
        context_text=context_text,
    ):
        assistant_response = build_missing_identity_reply()
    else:
        context_text = build_context_text(conversation, payload.content)

    update_person_from_message(person, payload.content)

    created_request = try_create_license_request_from_message(
        db=db,
        person=person,
        content=payload.content,
        context_text=context_text,
    )

    if created_request:
        assistant_response = build_created_request_reply(created_request)
    else:
        assistant_response = build_conversational_reply(
            person=person,
            conversation=conversation,
            content=payload.content,
        )

    save_message(
            db=db,
            conversation_id=conversation.id,
            sender_type="assistant",
            content=assistant_response,
        )

    db.commit()

    return {
        "ok": True,
        "conversation_id": conversation.id,
        "assistant_paused": conversation.assistant_paused,
        "assistant_will_reply": assistant_will_reply,
        "assistant_response": assistant_response,
        "created_license_request_id": created_request.id if created_request else None,
    }