from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import UNUSABLE_PASSWORD_HASH, require_role
from app.models.models import User
from app.schemas.schemas import PasswordLinkOut, UserCreate, UserCreateOut, UserOut
from app.services.audit import log_action
from app.services.password_tokens import issue_and_notify

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))):
    return db.query(User).order_by(User.username).all()


@router.post("", response_model=UserCreateOut)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    """Cadastro sempre por e-mail (desde 2026-09-10): quem cadastra não
    define senha — o novo usuário recebe um convite pra definir a própria.
    `username` fica igual ao e-mail (a coluna continua existindo por
    compatibilidade — ver app/models/models.py)."""
    if payload.role not in ("Master", "Supervisor", "Operador"):
        raise HTTPException(status_code=400, detail="Perfil inválido")
    email = payload.email.strip().lower()
    new_user = User(
        username=email,
        email=email,
        full_name=payload.full_name,
        role=payload.role,
        password_hash=UNUSABLE_PASSWORD_HASH,
        active=True,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um usuário com esse e-mail")
    db.refresh(new_user)

    link, emailed = issue_and_notify(db, "user", new_user.id, "invite", email, new_user.full_name or email)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_USUARIO",
        entity=new_user.username,
        after={"role": new_user.role, "convite_emailed": emailed},
        ip_address=client_ip(request),
    )
    return UserCreateOut(**UserOut.model_validate(new_user).model_dump(), invite_emailed=emailed, invite_link=None if emailed else link)


@router.post("/{user_id}/reset-password", response_model=PasswordLinkOut)
def reset_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    """"Zerar Senha": desde 2026-09-10 não define mais a senha diretamente —
    manda (ou devolve, se o alvo não tiver e-mail ou o SMTP não estiver
    configurado) um link de redefinição, mesmo mecanismo do "Esqueci minha
    senha" público."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    link, emailed = issue_and_notify(db, "user", target.id, "reset", target.email, target.full_name or target.username)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ZERAR_SENHA_USUARIO",
        entity=target.username,
        details={"emailed": emailed},
        ip_address=client_ip(request),
    )
    return PasswordLinkOut(emailed=emailed, link=link)


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
