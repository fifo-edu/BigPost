"""Credenciais de acesso ao www.correiosatende.correios.com.br por
licenciado (MCU de 8 dígitos + usuário/senha do site, e um token de API caso
o Correios venha a fornecer um). Senha/token nunca voltam em texto puro pela
API — só ficam disponíveis internamente (app/services/crypto.py) para o
backend usar quando a integração de fato autenticar contra o Correios."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_role
from app.models.models import CorreiosCredential, Licensee, User
from app.schemas.schemas import CorreiosCredentialOut, CorreiosCredentialUpsert
from app.services.audit import log_action
from app.services.crypto import encrypt

router = APIRouter(prefix="/api/v1/licensees/{licensee_id}/correios-credential", tags=["correios"])


def _to_out(cred: CorreiosCredential) -> CorreiosCredentialOut:
    return CorreiosCredentialOut(
        licensee_id=cred.licensee_id,
        mcu=cred.mcu,
        correios_username=cred.correios_username,
        has_password=bool(cred.password_encrypted),
        active=cred.active,
        last_validated_at=cred.last_validated_at,
        updated_at=cred.updated_at,
    )


@router.get("", response_model=CorreiosCredentialOut)
def get_credential(
    licensee_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))
):
    cred = db.query(CorreiosCredential).filter(CorreiosCredential.licensee_id == licensee_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Nenhuma credencial Correios cadastrada para este licenciado")
    return _to_out(cred)


@router.put("", response_model=CorreiosCredentialOut)
def upsert_credential(
    licensee_id: int,
    payload: CorreiosCredentialUpsert,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    if not db.get(Licensee, licensee_id):
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")

    cred = db.query(CorreiosCredential).filter(CorreiosCredential.licensee_id == licensee_id).first()
    is_new = cred is None
    if not cred:
        cred = CorreiosCredential(licensee_id=licensee_id)
        db.add(cred)

    cred.mcu = payload.mcu
    cred.correios_username = payload.correios_username
    cred.password_encrypted = encrypt(payload.password)
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
        action="CADASTRAR_CREDENCIAL_CORREIOS" if is_new else "ATUALIZAR_CREDENCIAL_CORREIOS",
        entity=f"licensee:{licensee_id}",
        after={"mcu": cred.mcu, "correios_username": cred.correios_username},
        ip_address=client_ip(request),
    )
    return _to_out(cred)
