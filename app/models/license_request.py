from datetime import date

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base



class LicenseRequest(Base):
    __tablename__ = "license_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), nullable=False, index=True)

    request_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)

    start_date: Mapped[Date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    person = relationship("Person", back_populates="license_requests")

    medical_folder_for: Mapped[str | None] = mapped_column(String(30), nullable=True)
    family_member_dni: Mapped[str | None] = mapped_column(String(30), nullable=True)
    family_member_full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    family_relationship: Mapped[str | None] = mapped_column(String(100), nullable=True)