from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import Base, engine
from app.models import AuditLog, Conversation, LicenseRequest, Message, Person, User
from app.routers import admin_audit, admin_users, auth_web, evolution, messages, web

app = FastAPI(title="RRHH Licencias")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_web.router)
app.include_router(admin_users.router)
app.include_router(admin_audit.router)
app.include_router(web.router)
app.include_router(messages.router)
app.include_router(evolution.router)


@app.get("/")
def home():
    return {"ok": True, "app": "RRHH Licencias"}