import os

from dotenv import load_dotenv
from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
SESSION_COOKIE_NAME = "rrhh_session"

serializer = URLSafeSerializer(SECRET_KEY, salt="rrhh-licencias-session")


ROLE_ADMIN = "ADMIN"
ROLE_RRHH = "RRHH"
ROLE_OPERADOR = "OPERADOR"


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def read_session_token(token: str) -> int | None:
    try:
        data = serializer.loads(token)
        return int(data.get("user_id"))
    except (BadSignature, ValueError, TypeError):
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)

    if not token:
        return None

    user_id = read_session_token(token)

    if not user_id:
        return None

    return (
        db.query(User)
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )


def has_role(user: User | None, allowed_roles: list[str]) -> bool:
    if not user:
        return False

    return user.role in allowed_roles


def redirect_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def redirect_forbidden() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=303)


def require_authenticated_user(current_user: User | None):
    if not current_user:
        return redirect_login()

    return None


def require_roles(current_user: User | None, allowed_roles: list[str]):
    if not current_user:
        return redirect_login()

    if current_user.role not in allowed_roles:
        return redirect_forbidden()

    return None


def can_manage_users(user: User | None) -> bool:
    return has_role(user, [ROLE_ADMIN])


def can_manage_licenses(user: User | None) -> bool:
    return has_role(user, [ROLE_ADMIN, ROLE_RRHH])


def can_manage_persons(user: User | None) -> bool:
    return has_role(user, [ROLE_ADMIN, ROLE_RRHH])


def can_manage_messages(user: User | None) -> bool:
    return has_role(user, [ROLE_ADMIN, ROLE_RRHH, ROLE_OPERADOR])


def can_change_license_status(user: User | None) -> bool:
    return has_role(user, [ROLE_ADMIN, ROLE_RRHH])


def can_answer_messages(user: User | None) -> bool:
    return has_role(user, [ROLE_ADMIN, ROLE_RRHH, ROLE_OPERADOR])


def home_for_user(user: User | None) -> str:
    if not user:
        return "/login"

    if user.role == ROLE_OPERADOR:
        return "/admin/messages"

    return "/admin"