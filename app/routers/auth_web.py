from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    get_current_user,
    home_for_user,
)
from app.db import get_db
from app.models import User
from app.services.security_service import verify_password

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request=request, db=db)

    if user:
        return RedirectResponse(url=home_for_user(user), status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == email.strip().lower(), User.is_active.is_(True))
        .first()
    )

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Usuario o contraseña incorrectos.",
            },
            status_code=400,
        )

    token = create_session_token(user.id)

    response = RedirectResponse(url=home_for_user(user), status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
    )

    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response