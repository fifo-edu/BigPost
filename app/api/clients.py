"""Cadastro de clientes de uma agência (módulo Agência gerencia quem são os
clientes que podem emitir etiqueta com essa agência). Gerenciado pela própria
equipe da agência (Administrador/Master) — não pelo time interno do BigPost."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import hash_password, require_licensee_role
from app.models.models import Client, LicenseeUser
from app.schemas.schemas import ClientCreate, ClientOut
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/agencia/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(
    db: Session = Depends(get_db), user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa"))
):
    return db.query(Client).filter(Client.licensee_id == user.licensee_id).order_by(Client.legal_name).all()


@router.post("", response_model=ClientOut)
def create_client(
    payload: ClientCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    client = Client(
        licensee_id=user.licensee_id,
        **payload.model_dump(exclude={"password"}),
        password_hash=hash_password(payload.password),
        created_by=user.username,
    )
    db.add(client)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um cliente com esse usuário nesta agência")
    db.refresh(client)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_CLIENTE",
        entity=f"client:{client.id}",
        after={"legal_name": client.legal_name, "tax_id": client.tax_id},
        origin="Agência",
        ip_address=client_ip(request),
    )
    return client


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
