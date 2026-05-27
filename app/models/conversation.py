from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    person_id: Mapped[int | None] = mapped_column(
        ForeignKey("persons.id"),
        nullable=True,
        index=True,
    )

    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="web")
    external_contact: Mapped[str | None] = mapped_column(String(150), nullable=True)

    assistant_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    admin_last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    person = relationship("Person", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )

    sender_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    attachment_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    conversation = relationship("Conversation", back_populates="messages")