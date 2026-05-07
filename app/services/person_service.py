import re

from sqlalchemy.orm import Session

from app.models import Person


def normalize_dni(dni: str) -> str:
    """
    Convierte:
    30.111.222
    30-111-222
    30 111 222

    en:
    30111222
    """
    return re.sub(r"\D", "", dni or "")


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None

    value = phone.strip()
    value = value.replace(" ", "")
    value = value.replace("-", "")
    value = value.replace("(", "")
    value = value.replace(")", "")
    return value or None


def find_person_by_dni(db: Session, dni: str) -> Person | None:
    clean_dni = normalize_dni(dni)

    if not clean_dni:
        return None

    return db.query(Person).filter(Person.dni == clean_dni).first()


def create_or_update_person(
    db: Session,
    first_name: str,
    last_name: str,
    dni: str,
    phone: str | None = None,
    email: str | None = None,
    department: str | None = None,
    employee_number: str | None = None,
    assistant_enabled: bool = True,
) -> Person:
    clean_dni = normalize_dni(dni)

    person = find_person_by_dni(db, clean_dni)

    if person:
        person.first_name = first_name.strip()
        person.last_name = last_name.strip()
        person.phone = normalize_phone(phone)
        person.email = email.strip() if email else None
        person.department = department.strip() if department else None
        person.employee_number = employee_number.strip() if employee_number else None
        return person

    person = Person(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        dni=clean_dni,
        phone=normalize_phone(phone),
        email=email.strip() if email else None,
        department=department.strip() if department else None,
        employee_number=employee_number.strip() if employee_number else None,
        assistant_enabled=assistant_enabled,
    )

    db.add(person)
    db.flush()

    return person