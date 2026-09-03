from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import get_current_user, require_role
from app.models.models import SystemParameter, User
from app.schemas.schemas import ParamUpdate
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/params", tags=["params"])


@router.get("")
def list_params(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [
        {"key": p.key, "value": p.value.get("v"), "description": p.description, "updated_at": p.updated_at}
        for p in db.query(SystemParameter).order_by(SystemParameter.key).all()
    ]


@router.put("/{key}")
def update_param(
    key: str,
    payload: ParamUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    row = db.query(SystemParameter).filter(SystemParameter.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Parâmetro não encontrado")
    before = row.value
    row.value = {"v": payload.value}
    row.updated_by = user.username
    if payload.description:
        row.description = payload.description
    db.commit()
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ALTERAR_PARAMETRO",
        entity=key,
        before=before,
        after=row.value,
        ip_address=client_ip(request),
    )
    return {"key": row.key, "value": row.value.get("v"), "description": row.description}
