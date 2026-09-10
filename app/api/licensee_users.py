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
from app.core.security import UNUSABLE_PASSWORD_HASH, require_role
from app.models.models import Licensee, LicenseeUser, User
from app.schemas.schemas import LICENSEE_ROLES, LicenseeUserCreate, LicenseeUserCreateOut, LicenseeUserOut, PasswordLinkOut
from app.services.audit import log_action
from app.services.password_tokens import issue_and_notify
from app.services.support_access import SUPPORT_USERNAME

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
    return (
        db.query(LicenseeUser)
        .filter(LicenseeUser.licensee_id == licensee_id, LicenseeUser.username != SUPPORT_USERNAME)
        .order_by(LicenseeUser.username)
        .all()
    )


@router.post("", response_model=LicenseeUserCreateOut)
def create_licensee_user(
    licensee_id: int,
    payload: LicenseeUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    """Cadastro sempre por e-mail (desde 2026-09-10): quem cadastra não
    define senha — o novo usuário da agência recebe um convite pra definir a
    própria. `username` fica igual ao e-mail."""
    _get_licensee_or_404(db, licensee_id)
    if payload.role not in LICENSEE_ROLES:
        raise HTTPException(status_code=400, detail="Perfil inválido")
    email = payload.email.strip().lower()
    new_user = LicenseeUser(
        licensee_id=licensee_id,
        username=email,
        email=email,
        full_name=payload.full_name,
        role=payload.role,
        password_hash=UNUSABLE_PASSWORD_HASH,
        active=True,
        created_by=user.username,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um usuário com esse e-mail nesta agência")
    db.refresh(new_user)

    link, emailed = issue_and_notify(
        db, "licensee_user", new_user.id, "invite", email, new_user.full_name or email
    )

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_USUARIO_AGENCIA",
        entity=f"licensee:{licensee_id}:{new_user.username}",
        after={"role": new_user.role, "convite_emailed": emailed},
        ip_address=client_ip(request),
    )
    return LicenseeUserCreateOut(
        **LicenseeUserOut.model_validate(new_user).model_dump(), invite_emailed=emailed, invite_link=None if emailed else link
    )


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


@router.post("/{licensee_user_id}/reset-password", response_model=PasswordLinkOut)
def reset_licensee_user_password(
    licensee_id: int,
    licensee_user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    """"Zerar Senha": desde 2026-09-10 manda (ou devolve, se sem e-mail ou
    SMTP desligado) um link de redefinição — mesmo mecanismo do "Esqueci
    minha senha" público."""
    target = _get_licensee_user_or_404(db, licensee_id, licensee_user_id)

    link, emailed = issue_and_notify(
        db, "licensee_user", target.id, "reset", target.email, target.full_name or target.username
    )

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ZERAR_SENHA_USUARIO_AGENCIA",
        entity=f"licensee:{licensee_id}:{target.username}",
        details={"emailed": emailed},
        ip_address=client_ip(request),
    )
    return PasswordLinkOut(emailed=emailed, link=link)


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
