import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import Base, engine
from app.models import AuditLog, Conversation, LicenseRequest, Message, Person, User
from app.routers import admin_audit, admin_users, auth_web, evolution, messages, web


load_dotenv()

app = FastAPI(title="RRHH Licencias")


# =========================================================
# CORS
# =========================================================

raw_cors_origins = os.getenv("CORS_ORIGINS", "")

cors_origins = [
    origin.strip()
    for origin in raw_cors_origins.split(",")
    if origin.strip()
]

if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Accept-Language",
            "Content-Language",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-Evolution-Webhook-Secret",
        ],
        expose_headers=[],
        max_age=600,
    )


# =========================================================
# SECURITY HEADERS
# =========================================================

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)

    app_env = os.getenv("APP_ENV", "dev").lower().strip()

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )

    # Compatible con Jinja2, CSS propio, JS inline actual y archivos estáticos/adjuntos.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "media-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    if app_env == "prod":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
def on_startup():
    # En producción se debe usar Alembic:
    # alembic upgrade head
    #
    # Esto queda desactivado por defecto para no crear tablas fuera de migraciones.
    auto_create_tables = os.getenv("AUTO_CREATE_TABLES", "false").lower().strip()

    if auto_create_tables == "true":
        Base.metadata.create_all(bind=engine)


# =========================================================
# STATIC FILES
# =========================================================

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# =========================================================
# ROUTERS
# =========================================================

app.include_router(auth_web.router)
app.include_router(admin_users.router)
app.include_router(admin_audit.router)
app.include_router(web.router)
app.include_router(messages.router)
app.include_router(evolution.router)


@app.get("/")
def home():
    return {"ok": True, "app": "RRHH Licencias"}