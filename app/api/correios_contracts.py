"""Contratos dos Correios (credenciais CWS) de uma loja, usados pelos
clientes dela para gerar pré-postagens. Normalmente cada cliente tem o seu
contrato, mas vários clientes podem usar o mesmo (marketplace): o contrato é
cadastrado uma vez e cada cliente aponta para ele. Gerenciado no portal da
loja (Administrador/Master). O código de acesso nunca volta pela API."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_licensee_role
from app.models.models import Client, CorreiosContract, LicenseeUser
from app.schemas.schemas import CorreiosContractCreate, CorreiosContractOut, CorreiosContractUpdate
from app.services.audit import log_action
from app.services.correios_cws import invalidar_token_contrato
from app.services.crypto import encrypt

router = APIRouter(prefix="/api/v1/agencia/correios-contracts", tags=["correios-contracts"])


def contratos_da_loja(db: Session, licensee_id: int) -> list[CorreiosContractOut]:
    counts = dict(
        db.query(Client.correios_contract_id, func.count(Client.id))
        .filter(Client.licensee_id == licensee_id, Client.correios_contract_id.isnot(None))
        .group_by(Client.correios_contract_id)
        .all()
    )
    rows = (
        db.query(CorreiosContract)
        .filter(CorreiosContract.licensee_id == licensee_id)
        .order_by(CorreiosContract.label)
        .all()
    )
    return [
        CorreiosContractOut.model_validate(k).model_copy(update={"clients_count": counts.get(k.id, 0)}) for k in rows
    ]


def _cartao_em_uso(db: Session, licensee_id: int, postal_card: str, exceto_id: int | None = None) -> CorreiosContract | None:
    q = db.query(CorreiosContract).filter(
        CorreiosContract.licensee_id == licensee_id, CorreiosContract.postal_card == postal_card
    )
    if exceto_id is not None:
        q = q.filter(CorreiosContract.id != exceto_id)
    return q.first()


def criar_contrato(db: Session, licensee_id: int, data: CorreiosContractCreate, created_by: str) -> CorreiosContract:
    """Cadastra um contrato novo na loja (sem commit). Recusa cartão de
    postagem já cadastrado na loja: nesse caso o certo é escolher o contrato
    existente (é o caso do marketplace), não duplicar a credencial."""
    existente = _cartao_em_uso(db, licensee_id, data.postal_card.strip())
    if existente:
        raise HTTPException(
            status_code=400,
            detail=f"O cartão de postagem {data.postal_card} já está cadastrado no contrato \"{existente.label}\". "
            "Escolha esse contrato na lista em vez de cadastrar de novo.",
        )
    contrato = CorreiosContract(
        licensee_id=licensee_id,
        label=(data.label or "").strip() or f"Contrato {data.contract_number.strip()}",
        correios_username=data.correios_username.strip(),
        access_code_encrypted=encrypt(data.access_code),
        postal_card=data.postal_card.strip(),
        contract_number=data.contract_number.strip(),
        dr=data.dr,
        created_by=created_by,
    )
    db.add(contrato)
    db.flush()
    return contrato


def contrato_da_loja_ou_400(db: Session, licensee_id: int, contract_id: int) -> CorreiosContract:
    contrato = (
        db.query(CorreiosContract)
        .filter(CorreiosContract.id == contract_id, CorreiosContract.licensee_id == licensee_id)
        .first()
    )
    if not contrato:
        raise HTTPException(status_code=400, detail="Contrato dos Correios não encontrado nesta loja")
    if not contrato.active:
        raise HTTPException(status_code=400, detail=f"O contrato \"{contrato.label}\" está inativo")
    return contrato


def _audit(contrato: CorreiosContract) -> dict:
    return {
        "label": contrato.label,
        "postal_card": contrato.postal_card,
        "contract_number": contrato.contract_number,
        "dr": contrato.dr,
        "active": contrato.active,
    }


@router.get("", response_model=list[CorreiosContractOut])
def list_contracts(db: Session = Depends(get_db), user: LicenseeUser = Depends(require_licensee_role("Administrador"))):
    return contratos_da_loja(db, user.licensee_id)


@router.post("", response_model=CorreiosContractOut)
def create_contract(
    payload: CorreiosContractCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    contrato = criar_contrato(db, user.licensee_id, payload, user.username)
    db.commit()
    db.refresh(contrato)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_CONTRATO_CORREIOS",
        entity=f"correios_contract:{contrato.id}",
        after=_audit(contrato),
        origin="Agência",
        ip_address=client_ip(request),
    )
    return CorreiosContractOut.model_validate(contrato)


@router.put("/{contract_id}", response_model=CorreiosContractOut)
def update_contract(
    contract_id: int,
    payload: CorreiosContractUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    """Editar o contrato vale para todos os clientes que usam ele."""
    contrato = (
        db.query(CorreiosContract)
        .filter(CorreiosContract.id == contract_id, CorreiosContract.licensee_id == user.licensee_id)
        .first()
    )
    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato dos Correios não encontrado")
    outro = _cartao_em_uso(db, user.licensee_id, payload.postal_card.strip(), exceto_id=contrato.id)
    if outro:
        raise HTTPException(
            status_code=400, detail=f"O cartão de postagem {payload.postal_card} já está no contrato \"{outro.label}\""
        )
    before = _audit(contrato)
    contrato.label = (payload.label or "").strip() or f"Contrato {payload.contract_number.strip()}"
    contrato.correios_username = payload.correios_username.strip()
    contrato.postal_card = payload.postal_card.strip()
    contrato.contract_number = payload.contract_number.strip()
    contrato.dr = payload.dr
    contrato.active = payload.active
    if payload.access_code:
        contrato.access_code_encrypted = encrypt(payload.access_code)
    contrato.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(contrato)
    invalidar_token_contrato(contrato.id)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ATUALIZAR_CONTRATO_CORREIOS",
        entity=f"correios_contract:{contrato.id}",
        before=before,
        after={**_audit(contrato), "codigo_acesso_alterado": bool(payload.access_code)},
        origin="Agência",
        ip_address=client_ip(request),
    )
    return next(k for k in contratos_da_loja(db, user.licensee_id) if k.id == contrato.id)
