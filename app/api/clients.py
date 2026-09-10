"""Cadastro de clientes de uma agência (módulo Agência gerencia quem são os
clientes que podem emitir etiqueta com essa agência). Gerenciado pela própria
equipe da agência (Administrador/Master) — não pelo time interno do BigPost."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import UNUSABLE_PASSWORD_HASH, require_licensee_role
from app.models.models import Client, LicenseeUser
from app.schemas.schemas import ClientCreate, ClientCreateOut, ClientOut, PasswordLinkOut
from app.services.audit import log_action
from app.services.password_tokens import issue_and_notify
from app.services.support_access import SUPPORT_USERNAME

router = APIRouter(prefix="/api/v1/agencia/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(
    db: Session = Depends(get_db), user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa"))
):
    return (
        db.query(Client)
        .filter(Client.licensee_id == user.licensee_id, Client.username != SUPPORT_USERNAME)
        .order_by(Client.legal_name)
        .all()
    )


@router.post("", response_model=ClientCreateOut)
def create_client(
    payload: ClientCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    """Cadastro sempre por e-mail (desde 2026-09-10): quem cadastra não
    define senha — o cliente recebe um convite pra definir a própria.
    `username` fica igual ao `contact_email` (que passa a ser também o
    login)."""
    email = payload.contact_email.strip().lower()
    client = Client(
        licensee_id=user.licensee_id,
        **payload.model_dump(exclude={"contact_email"}),
        contact_email=email,
        username=email,
        password_hash=UNUSABLE_PASSWORD_HASH,
        created_by=user.username,
    )
    db.add(client)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um cliente com esse e-mail nesta agência")
    db.refresh(client)

    link, emailed = issue_and_notify(db, "client", client.id, "invite", email, client.legal_name)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_CLIENTE",
        entity=f"client:{client.id}",
        after={"legal_name": client.legal_name, "tax_id": client.tax_id, "convite_emailed": emailed},
        origin="Agência",
        ip_address=client_ip(request),
    )
    return ClientCreateOut(**ClientOut.model_validate(client).model_dump(), invite_emailed=emailed, invite_link=None if emailed else link)


@router.post("/{client_id}/reset-password", response_model=PasswordLinkOut)
def reset_client_password(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    """Suporte ao botão "Esqueci minha senha" da tela de login do Cliente,
    acionado por um Administrador/Master da própria agência (o cliente
    pertence a ela), pela tela de Clientes: desde 2026-09-10 manda (ou
    devolve, se sem e-mail ou SMTP desligado) um link de redefinição — mesmo
    mecanismo do "Esqueci minha senha" público."""
    client = db.query(Client).filter(Client.id == client_id, Client.licensee_id == user.licensee_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    link, emailed = issue_and_notify(db, "client", client.id, "reset", client.contact_email, client.legal_name)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ZERAR_SENHA_CLIENTE",
        entity=f"client:{client.id}",
        details={"emailed": emailed},
        origin="Agência",
        ip_address=client_ip(request),
    )
    return PasswordLinkOut(emailed=emailed, link=link)


@router.post("/{client_id}/deactivate", response_model=ClientOut)
def deactivate_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    client = db.query(Client).filter(Client.id == client_id, Client.licensee_id == user.licensee_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    client.active = False
    db.commit()
    db.refresh(client)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="DESATIVAR_CLIENTE",
        entity=f"client:{client.id}",
        origin="Agência",
        ip_address=client_ip(request),
    )
    return client
