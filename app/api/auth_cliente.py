"""Login do cliente da agência (módulo Cliente) — Client. Duas formas de
acesso: usuário/senha pro portal manual (cookie), ou api_key pra integração
programática (Authorization: Bearer) — "emite as etiquetas por integrações
ou manuais"."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, generate_api_key, get_current_client, verify_password
from app.models.models import Client, Licensee
from app.schemas.schemas import (
    ClientApiKeyOut,
    ClientLicenseeLookupRequest,
    ClientLoginRequest,
    ClientOut,
    ClientWebhookConfig,
    ClientWebhookOut,
    LicenseeMatchOut,
)
from app.services.audit import log_action
from app.services.support_access import SUPPORT_USERNAME

router = APIRouter(prefix="/api/v1/auth/cliente", tags=["auth-cliente"])


@router.post("/login")
def login(payload: ClientLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    # `payload.username` aceita username OU e-mail — desde 2026-09-10 o
    # cadastro é sempre por e-mail (contact_email dobra de contato + login),
    # mas contas antigas continuam entrando pelo username de sempre.
    identifier = payload.username.strip()
    client = (
        db.query(Client)
        .filter(
            Client.licensee_id == payload.licensee_id,
            or_(Client.username.ilike(identifier), Client.contact_email.ilike(identifier)),
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


@router.post("/lookup-licensee", response_model=list[LicenseeMatchOut])
def lookup_licensee(payload: ClientLicenseeLookupRequest, db: Session = Depends(get_db)):
    """Mesma ideia de app/api/auth_agencia.py::lookup_licensee, pro lado do
    Cliente: resolve automaticamente em qual(is) agência(s) um e-mail tem
    conta de cliente, dispensando o "Código do licenciado/agência (ID)"
    digitado à mão."""
    email = payload.email.strip().lower()
    rows = (
        db.query(Client, Licensee)
        .join(Licensee, Licensee.id == Client.licensee_id)
        .filter(
            Client.contact_email.ilike(email),
            Client.active.is_(True),
            Client.username != SUPPORT_USERNAME,
        )
        .all()
    )
    return [LicenseeMatchOut(id=licensee.id, name=licensee.trade_name or licensee.legal_name) for _, licensee in rows]


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
