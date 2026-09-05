from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import hash_password, require_role
from app.models.models import User
from app.schemas.schemas import PasswordResetRequest, UserCreate, UserOut
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))):
    return db.query(User).order_by(User.username).all()


@router.post("", response_model=UserOut)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    if payload.role not in ("Master", "Supervisor", "Operador"):
        raise HTTPException(status_code=400, detail="Perfil inválido")
    new_user = User(
        username=payload.username.strip(),
        full_name=payload.full_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        active=True,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Usuário já existe")
    db.refresh(new_user)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_USUARIO",
        entity=new_user.username,
        after={"role": new_user.role},
        ip_address=client_ip(request),
    )
    return new_user


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    target.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(target)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ZERAR_SENHA_USUARIO",
        entity=target.username,
        ip_address=client_ip(request),
    )
    return target


@router.post("/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    target.locked = False
    target.failed_attempts = 0
    db.commit()
    db.refresh(target)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="DESBLOQUEAR_USUARIO",
        entity=target.username,
        ip_address=client_ip(request),
    )
    return target
