"""Credenciais dos Correios para o módulo BigPost Cliente (emissão de
etiquetas/postagem via contrato, diferente do login do site Correios Atende
usado pelos módulos BigPost Agência/Operação). Aqui o Correios pede usuário,
token de API, cartão de postagem e número do contrato. Cadastrado pelo
Painel Master junto com a licença BigPost (tela Licenças → BigPost). Token
nunca volta em texto puro pela API — só fica disponível internamente
(app/services/crypto.py) para o backend usar quando a integração autenticar
contra o Correios."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_role
from app.models.models import ClientCorreiosCredential, Licensee, User
from app.schemas.schemas import ClientCorreiosCredentialOut, ClientCorreiosCredentialUpsert
from app.services.audit import log_action
from app.services.crypto import encrypt

router = APIRouter(prefix="/api/v1/licensees/{licensee_id}/client-correios-credential", tags=["client-correios"])


def _to_out(cred: ClientCorreiosCredential) -> ClientCorreiosCredentialOut:
    return ClientCorreiosCredentialOut(
        licensee_id=cred.licensee_id,
        correios_username=cred.correios_username,
        postal_card=cred.postal_card,
        contract_number=cred.contract_number,
        has_token=bool(cred.token_encrypted),
        active=cred.active,
        last_validated_at=cred.last_validated_at,
        updated_at=cred.updated_at,
    )


@router.get("", response_model=ClientCorreiosCredentialOut)
def get_credential(
    licensee_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))
):
    cred = db.query(ClientCorreiosCredential).filter(ClientCorreiosCredential.licensee_id == licensee_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Nenhuma credencial de Correios (BigPost Cliente) cadastrada para este licenciado")
    return _to_out(cred)


@router.put("", response_model=ClientCorreiosCredentialOut)
def upsert_credential(
    licensee_id: int,
    payload: ClientCorreiosCredentialUpsert,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    if not db.get(Licensee, licensee_id):
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")

    cred = db.query(ClientCorreiosCredential).filter(ClientCorreiosCredential.licensee_id == licensee_id).first()
    is_new = cred is None
    if not cred:
        cred = ClientCorreiosCredential(licensee_id=licensee_id)
        db.add(cred)

    cred.correios_username = payload.correios_username
    cred.postal_card = payload.postal_card
    cred.contract_number = payload.contract_number
    cred.token_encrypted = encrypt(payload.token) if payload.token else None
    cred.active = True
    cred.updated_at = datetime.utcnow()
    cred.created_by = cred.created_by or user.username
    db.commit()
    db.refresh(cred)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_CREDENCIAL_CLIENTE_CORREIOS" if is_new else "ATUALIZAR_CREDENCIAL_CLIENTE_CORREIOS",
        entity=f"licensee:{licensee_id}",
        after={"correios_username": cred.correios_username, "postal_card": cred.postal_card, "contract_number": cred.contract_number},
        ip_address=client_ip(request),
    )
    return _to_out(cred)
