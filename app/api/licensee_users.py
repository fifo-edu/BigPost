"""Gestão dos usuários de cada agência licenciada (Master, Administrador,
Financeiro, Operador de Caixa, Expedição).

Estas rotas são o cadastro administrativo (equipe interna do BigPost criando/
gerenciando as identidades da equipe de uma agência), por isso são protegidas
pelo RBAC interno (Supervisor+), não pelo RBAC de agência. O login efetivo
desses usuários, uma vez cadastrados, acontece no módulo Agência
(/api/v1/auth/agencia/login, ver app/api/auth_agencia.py).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import hash_password, require_role
from app.models.models import Licensee, LicenseeUser, User
from app.schemas.schemas import LICENSEE_ROLES, LicenseeUserCreate, LicenseeUserOut, PasswordResetRequest
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/licensees/{licensee_id}/users", tags=["licensee-users"])


def _get_licensee_or_404(db: Session, licensee_id: int) -> Licensee:
    licensee = db.get(Licensee, licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")
    return licensee


@router.get("", response_model=list[LicenseeUserOut])
def list_licensee_users(
    licensee_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))
):
    _get_licensee_or_404(db, licensee_id)
    return db.query(LicenseeUser).filter(LicenseeUser.licensee_id == licensee_id).order_by(LicenseeUser.username).all()


@router.post("", response_model=LicenseeUserOut)
def create_licensee_user(
    licensee_id: int,
    payload: LicenseeUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    _get_licensee_or_404(db, licensee_id)
    if payload.role not in LICENSEE_ROLES:
        raise HTTPException(status_code=400, detail="Perfil inválido")
    new_user = LicenseeUser(
        licensee_id=licensee_id,
        username=payload.username.strip(),
        full_name=payload.full_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        active=True,
        created_by=user.username,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um usuário com esse nome nesta agência")
    db.refresh(new_user)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_USUARIO_AGENCIA",
        entity=f"licensee:{licensee_id}:{new_user.username}",
        after={"role": new_user.role},
        ip_address=client_ip(request),
    )
    return new_user


@router.post("/{licensee_user_id}/deactivate", response_model=LicenseeUserOut)
def deactivate_licensee_user(
    licensee_id: int,
    licensee_user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    licensee_user = (
        db.query(LicenseeUser)
        .filter(LicenseeUser.id == licensee_user_id, LicenseeUser.licensee_id == licensee_id)
        .first()
    )
    if not licensee_user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    licensee_user.active = False
    db.commit()
    db.refresh(licensee_user)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="DESATIVAR_USUARIO_AGENCIA",
        entity=f"licensee:{licensee_id}:{licensee_user.username}",
        ip_address=client_ip(request),
    )
    return licensee_user


def _get_licensee_user_or_404(db: Session, licensee_id: int, licensee_user_id: int) -> LicenseeUser:
    licensee_user = (
        db.query(LicenseeUser)
        .filter(LicenseeUser.id == licensee_user_id, LicenseeUser.licensee_id == licensee_id)
        .first()
    )
    if not licensee_user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return licensee_user


@router.post("/{licensee_user_id}/reset-password", response_model=LicenseeUserOut)
def reset_licensee_user_password(
    licensee_id: int,
    licensee_user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    target = _get_licensee_user_or_404(db, licensee_id, licensee_user_id)
    target.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(target)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ZERAR_SENHA_USUARIO_AGENCIA",
        entity=f"licensee:{licensee_id}:{target.username}",
        ip_address=client_ip(request),
    )
    return target


@router.post("/{licensee_user_id}/unlock", response_model=LicenseeUserOut)
def unlock_licensee_user(
    licensee_id: int,
    licensee_user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    target = _get_licensee_user_or_404(db, licensee_id, licensee_user_id)
    target.locked = False
    target.failed_attempts = 0
    db.commit()
    db.refresh(target)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="DESBLOQUEAR_USUARIO_AGENCIA",
        entity=f"licensee:{licensee_id}:{target.username}",
        ip_address=client_ip(request),
    )
    return target
