from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import can_manage_users, get_current_user
from app.db import get_db
from app.models import User
from app.services.security_service import hash_password

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


ROLES = {
    "ADMIN": "Administrador",
    "RRHH": "RRHH",
    "OPERADOR": "Operador",
}


def _require_admin(current_user: User | None):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    if not can_manage_users(current_user):
        return RedirectResponse(url="/admin", status_code=303)

    return None


@router.get("/admin/users")
def users_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    users = db.query(User).order_by(User.created_at.desc()).all()

    return templates.TemplateResponse(
        request,
        "users_list.html",
        {
            "current_user": current_user,
            "users": users,
            "roles": ROLES,
        },
    )


@router.get("/admin/users/new")
def user_new_form(
    request: Request,
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "user_form.html",
        {
            "current_user": current_user,
            "item": None,
            "roles": ROLES,
            "error": None,
        },
    )


@router.post("/admin/users/new")
def user_create(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    clean_email = email.strip().lower()

    existing = db.query(User).filter(User.email == clean_email).first()

    if existing:
        return templates.TemplateResponse(
            request,
            "user_form.html",
            {
                "current_user": current_user,
                "item": None,
                "roles": ROLES,
                "error": "Ya existe un usuario con ese email.",
            },
            status_code=400,
        )

    if role not in ROLES:
        role = "OPERADOR"

    user = User(
        full_name=full_name.strip(),
        email=clean_email,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active == "true",
    )

    db.add(user)
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/admin/users/{user_id}/edit")
def user_edit_form(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    item = db.query(User).filter(User.id == user_id).first()

    if not item:
        return RedirectResponse(url="/admin/users", status_code=303)

    return templates.TemplateResponse(
        request,
        "user_form.html",
        {
            "current_user": current_user,
            "item": item,
            "roles": ROLES,
            "error": None,
        },
    )


@router.post("/admin/users/{user_id}/edit")
def user_edit_save(
    user_id: int,
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    item = db.query(User).filter(User.id == user_id).first()

    if not item:
        return RedirectResponse(url="/admin/users", status_code=303)

    clean_email = email.strip().lower()

    existing = (
        db.query(User)
        .filter(User.email == clean_email, User.id != user_id)
        .first()
    )

    if existing:
        return templates.TemplateResponse(
            request,
            "user_form.html",
            {
                "current_user": current_user,
                "item": item,
                "roles": ROLES,
                "error": "Ya existe otro usuario con ese email.",
            },
            status_code=400,
        )

    if role not in ROLES:
        role = "OPERADOR"

    item.full_name = full_name.strip()
    item.email = clean_email
    item.role = role

    # Evita que el admin se desactive a sí mismo por error.
    if current_user and item.id == current_user.id:
        item.is_active = True
    else:
        item.is_active = is_active == "true"

    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/admin/users/{user_id}/password")
def user_password_form(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    item = db.query(User).filter(User.id == user_id).first()

    if not item:
        return RedirectResponse(url="/admin/users", status_code=303)

    return templates.TemplateResponse(
        request,
        "user_password.html",
        {
            "current_user": current_user,
            "item": item,
            "error": None,
        },
    )


@router.post("/admin/users/{user_id}/password")
def user_password_save(
    user_id: int,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    item = db.query(User).filter(User.id == user_id).first()

    if not item:
        return RedirectResponse(url="/admin/users", status_code=303)

    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "user_password.html",
            {
                "current_user": current_user,
                "item": item,
                "error": "Las contraseñas no coinciden.",
            },
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "user_password.html",
            {
                "current_user": current_user,
                "item": item,
                "error": "La contraseña debe tener al menos 8 caracteres.",
            },
            status_code=400,
        )

    item.password_hash = hash_password(password)
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/toggle")
def user_toggle_active(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    redirect = _require_admin(current_user)

    if redirect:
        return redirect

    item = db.query(User).filter(User.id == user_id).first()

    if not item:
        return RedirectResponse(url="/admin/users", status_code=303)

    # Evita desactivar el usuario actual.
    if current_user and item.id == current_user.id:
        return RedirectResponse(url="/admin/users", status_code=303)

    item.is_active = not item.is_active
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)