"""Login do cliente da agência (módulo Cliente) — Client. Duas formas de
acesso: usuário/senha pro portal manual (cookie), ou api_key pra integração
programática (Authorization: Bearer) — "emite as etiquetas por integrações
ou manuais"."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, generate_api_key, get_current_client, verify_password
from app.models.models import Client
from app.schemas.schemas import (
    ClientApiKeyOut,
    ClientLoginRequest,
    ClientOut,
    ClientWebhookConfig,
    ClientWebhookOut,
)
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/auth/cliente", tags=["auth-cliente"])


@router.post("/login")
def login(payload: ClientLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    client = (
        db.query(Client)
        .filter(
            Client.licensee_id == payload.licensee_id,
            Client.username.ilike(payload.username),
            Client.active.is_(True),
        )
        .first()
    )
    if not client or not verify_password(payload.password, client.password_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    token = create_token(client.username, "client", {"uid": client.id})
    response.set_cookie(
        "session_cliente", token, httponly=True, samesite="strict", secure=settings.cookie_secure, max_age=60 * 60 * 8
    )
    log_action(
        db,
        username=client.username,
        role="Client",
        action="LOGIN_CLIENTE",
        entity=f"client:{client.id}",
        origin="Cliente",
        ip_address=client_ip(request),
    )
    return {"ok": True, "client": ClientOut.model_validate(client)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session_cliente")
    return {"ok": True}


@router.get("/me", response_model=ClientOut)
def me(client: Client = Depends(get_current_client)):
    return client


@router.post("/api-key/rotate", response_model=ClientApiKeyOut)
def rotate_api_key(
    request: Request, db: Session = Depends(get_db), client: Client = Depends(get_current_client)
):
    """Gera uma nova chave de API (invalida a anterior, se houver). A chave em
    texto puro só aparece nesta resposta — guarde num lugar seguro."""
    raw_key, key_hash, prefix = generate_api_key()
    client.api_key_hash = key_hash
    client.api_key_prefix = prefix
    db.commit()
    log_action(
        db,
        username=client.username,
        role="Client",
        action="ROTACIONAR_API_KEY",
        entity=f"client:{client.id}",
        origin="Cliente",
        ip_address=client_ip(request),
    )
    return ClientApiKeyOut(api_key=raw_key, api_key_prefix=prefix)


@router.put("/webhook", response_model=ClientWebhookOut)
def configure_webhook(
    payload: ClientWebhookConfig,
    request: Request,
    db: Session = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    client.webhook_url = payload.webhook_url
    client.webhook_secret = payload.webhook_secret or client.webhook_secret or secrets.token_urlsafe(24)
    db.commit()
    log_action(
        db,
        username=client.username,
        role="Client",
        action="CONFIGURAR_WEBHOOK",
        entity=f"client:{client.id}",
        after={"webhook_url": client.webhook_url},
        origin="Cliente",
        ip_address=client_ip(request),
    )
    return ClientWebhookOut(webhook_url=client.webhook_url, webhook_secret=client.webhook_secret)


@router.get("/webhook", response_model=ClientWebhookOut)
def get_webhook(client: Client = Depends(get_current_client)):
    return ClientWebhookOut(webhook_url=client.webhook_url, webhook_secret=client.webhook_secret)
