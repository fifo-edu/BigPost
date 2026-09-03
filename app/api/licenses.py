import secrets
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import get_current_user, require_role
from app.models.models import Activation, License, Licensee, User
from app.schemas.schemas import (
    LicenseGenerateRequest,
    LicenseHeartbeatRequest,
    LicenseOut,
    LicenseValidateRequest,
)
from app.services.audit import log_action
from app.services.licensing import public_key_pem, sign_payload, verify_license_code

router = APIRouter(prefix="/api/v1/licenses", tags=["licenses"])


@router.get("/public-key")
def get_public_key():
    """Endpoint público: os apps Cliente/Agência baixam a chave pública uma
    vez e podem validar licenças offline a partir daí."""
    return {"public_key_pem": public_key_pem()}


@router.get("", response_model=list[LicenseOut])
def list_licenses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(License).order_by(License.id.desc()).all()


@router.post("/generate", response_model=LicenseOut)
def generate_license(
    payload: LicenseGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    licensee = db.get(Licensee, payload.licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")

    # BigPost é produto único — por padrão a licença libera os dois módulos
    # (Cliente e Agência); o admin pode restringir passando `features`.
    features = payload.features or {"cliente": True, "agencia": True}

    license_uid = secrets.token_hex(8).upper()
    token_payload = {
        "license_id": license_uid,
        "product_code": "BIGPOST",
        "customer_name": licensee.legal_name,
        "tax_id": licensee.tax_id,
        "issued_at": date.today().isoformat(),
        "expires_at": payload.expires_at or "PERPETUA",
        "max_users": payload.max_users or licensee.contracted_users,
        "features": features,
    }
    license_code = sign_payload(token_payload)

    license_row = License(
        licensee_id=licensee.id,
        license_code=license_code,
        license_uid=license_uid,
        expires_at=token_payload["expires_at"],
        max_users=token_payload["max_users"],
        features=features,
        status="Ativa",
        created_by=user.username,
    )
    db.add(license_row)
    db.commit()
    db.refresh(license_row)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="GERAR_LICENCA",
        entity=f"licensee:{licensee.id}",
        after=token_payload,
        ip_address=client_ip(request),
    )
    return license_row


@router.post("/{license_id}/revoke", response_model=LicenseOut)
def revoke_license(
    license_id: int,
    request: Request,
    reason: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    license_row = db.get(License, license_id)
    if not license_row:
        raise HTTPException(status_code=404, detail="Licença não encontrada")
    license_row.status = "Revogada"
    license_row.revoked_at = datetime.utcnow()
    license_row.revoked_reason = reason
    db.commit()
    db.refresh(license_row)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="REVOGAR_LICENCA",
        entity=f"license:{license_id}",
        after={"reason": reason},
        ip_address=client_ip(request),
    )
    return license_row


@router.post("/validate")
def validate_license(payload: LicenseValidateRequest, db: Session = Depends(get_db)):
    """Endpoint público (sem login) usado pelos módulos Cliente/Agência.

    Faz a verificação criptográfica da assinatura E confere o status atual no
    banco (permite revogar/bloquear uma licença mesmo que o token assinado
    continue "matematicamente" válido)."""
    data = verify_license_code(payload.license_code)
    if not data:
        return {"valid": False, "reason": "Assinatura inválida"}

    license_row = db.query(License).filter(License.license_uid == data.get("license_id")).first()
    if not license_row:
        return {"valid": False, "reason": "Licença não encontrada no cadastro"}
    if license_row.status != "Ativa":
        return {"valid": False, "reason": f"Licença {license_row.status.lower()}"}

    licensee = db.get(Licensee, license_row.licensee_id)
    if licensee and licensee.status in ("Bloqueado", "Expirado"):
        return {"valid": False, "reason": f"Licenciado {licensee.status.lower()}"}

    if data.get("expires_at") not in (None, "", "PERPETUA"):
        try:
            if date.fromisoformat(data["expires_at"]) < date.today():
                return {"valid": False, "reason": "Licença expirada"}
        except ValueError:
            pass

    return {"valid": True, "payload": data, "licensee_status": licensee.status if licensee else None}


@router.post("/heartbeat")
def heartbeat(payload: LicenseHeartbeatRequest, db: Session = Depends(get_db)):
    """Chamado periodicamente pelos apps Cliente/Agência: confirma que a
    instalação está de pé e reporta quantidade de usuários ativos. É o que
    alimenta a tabela `activations` (contagem de instalações por
    licenciado) sem que o Master precise saber nada do dado operacional."""
    data = verify_license_code(payload.license_code)
    if not data:
        raise HTTPException(status_code=400, detail="Licença inválida")
    license_row = db.query(License).filter(License.license_uid == data.get("license_id")).first()
    if not license_row or license_row.status != "Ativa":
        raise HTTPException(status_code=403, detail="Licença inativa")

    activation = (
        db.query(Activation)
        .filter(
            Activation.licensee_id == license_row.licensee_id,
            Activation.installation_id == payload.installation_id,
        )
        .first()
    )
    if not activation:
        activation = Activation(
            licensee_id=license_row.licensee_id,
            license_id=license_row.id,
            installation_id=payload.installation_id,
        )
        db.add(activation)
    activation.app_name = payload.app_name
    activation.app_version = payload.app_version
    activation.active_users = payload.active_users
    activation.last_seen = datetime.utcnow()
    activation.status = "Ativa"

    licensee = db.get(Licensee, license_row.licensee_id)
    if licensee:
        licensee.reported_active_users = payload.active_users

    db.commit()
    return {"ok": True}
