from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import get_current_user, require_role
from app.models.models import Charge, Licensee, User
from app.schemas.schemas import ChargeCreate, ChargeOut, MassChargeRequest
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/charges", tags=["charges"])


@router.get("", response_model=list[ChargeOut])
def list_charges(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Charge).order_by(Charge.id.desc()).all()


@router.post("", response_model=ChargeOut)
def create_charge(
    payload: ChargeCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    charge = Charge(**payload.model_dump(), status="Aberta")
    db.add(charge)
    db.commit()
    db.refresh(charge)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="EMITIR_COBRANCA",
        entity=f"licensee:{payload.licensee_id}",
        after=payload.model_dump(),
        ip_address=client_ip(request),
    )
    return charge


@router.post("/{charge_id}/pay", response_model=ChargeOut)
def pay_charge(
    charge_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Operador")),
):
    charge = db.get(Charge, charge_id)
    if not charge:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada")
    charge.status = "Paga"
    charge.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(charge)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="BAIXAR_COBRANCA",
        entity=f"charge:{charge_id}",
        after={"status": "Paga"},
        ip_address=client_ip(request),
    )
    return charge


@router.post("/mass")
def mass_charges(
    payload: MassChargeRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    if payload.licensee_ids:
        rows = (
            db.query(Licensee)
            .filter(Licensee.id.in_(payload.licensee_ids), Licensee.status == "Ativo")
            .all()
        )
    else:
        rows = db.query(Licensee).filter(Licensee.status == "Ativo").all()

    created = 0
    for licensee in rows:
        exists = (
            db.query(Charge)
            .filter(Charge.licensee_id == licensee.id, Charge.reference_month == payload.reference_month)
            .first()
        )
        if exists:
            continue
        db.add(
            Charge(
                licensee_id=licensee.id,
                reference_month=payload.reference_month,
                due_date=payload.due_date,
                amount=float(licensee.monthly_fee or 0),
                status="Aberta",
            )
        )
        created += 1
    db.commit()
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="GERAR_COBRANCAS_EM_MASSA",
        entity=payload.reference_month,
        after={"criadas": created, "vencimento": payload.due_date},
        origin="Banco do Brasil",
        ip_address=client_ip(request),
    )
    return {"ok": True, "created": created}
