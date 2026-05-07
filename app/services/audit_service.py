from sqlalchemy.orm import Session

from app.models import AuditLog, User


def create_audit_log(
    db: Session,
    current_user: User | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    description: str | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=current_user.id if current_user else None,
        user_email=current_user.email if current_user else None,
        user_role=current_user.role if current_user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
    )

    db.add(log)
    db.flush()

    return log