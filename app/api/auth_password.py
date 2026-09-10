"""Fluxo de senha por e-mail — "esqueci minha senha" de verdade e a
finalização de um convite (1º acesso, conta cadastrada só com e-mail) —
mesmo mecanismo pros 3 tipos de conta (User, LicenseeUser, Client). Ver
app/services/password_tokens.py.

Dois endpoints públicos (sem login, chamados a partir de qualquer uma das 5
telas de login):
- POST /forgot — pede a redefinição; SEMPRE responde de forma genérica (não
  revela se o e-mail existe) pra não virar uma forma de descobrir contas —
  por isso, ao contrário das ações administrativas (cadastro, "Zerar Senha"
  em app/api/users.py, licensee_users.py e clients.py), nunca devolve o link
  na resposta, só tenta mandar por e-mail (silenciosamente inerte se o SMTP
  não estiver configurado — quem precisar nesse meio tempo usa o "Zerar
  Senha" administrativo).
- POST /set — aplica o token (convite OU redefinição, mesmo mecanismo) e a
  nova senha, já validada pela política (app/services/password_policy.py).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import hash_password
from app.models.models import Client, LicenseeUser, User
from app.schemas.schemas import PasswordForgotRequest, PasswordSetRequest
from app.services.audit import log_action
from app.services.password_policy import validate_password_strength
from app.services.password_tokens import consume_token, notify_reset_without_link
from app.services.support_access import SUPPORT_USERNAME

router = APIRouter(prefix="/api/v1/auth/password", tags=["auth-password"])

GENERIC_OK = {"ok": True, "detail": "Se o e-mail informado tiver uma conta, enviamos as instruções."}

_MODEL_BY_ACTOR_TYPE = {"user": User, "licensee_user": LicenseeUser, "client": Client}


def _find_actor(db: Session, actor_type: str, email: str, licensee_id: int | None):
    email = email.strip().lower()
    if actor_type == "user":
        return db.query(User).filter(User.email.ilike(email), User.active.is_(True)).first()
    if licensee_id is None:
        return None
    if actor_type == "licensee_user":
        return (
            db.query(LicenseeUser)
            .filter(
                LicenseeUser.licensee_id == licensee_id,
                LicenseeUser.email.ilike(email),
                LicenseeUser.username != SUPPORT_USERNAME,
                LicenseeUser.active.is_(True),
            )
            .first()
        )
    if actor_type == "client":
        return (
            db.query(Client)
            .filter(
                Client.licensee_id == licensee_id,
                Client.contact_email.ilike(email),
                Client.username != SUPPORT_USERNAME,
                Client.active.is_(True),
            )
            .first()
        )
    return None


@router.post("/forgot")
def forgot_password(payload: PasswordForgotRequest, db: Session = Depends(get_db)):
    actor = _find_actor(db, payload.actor_type, payload.email, payload.licensee_id)
    if actor:
        name = getattr(actor, "full_name", None) or getattr(actor, "legal_name", None) or getattr(actor, "username", "")
        notify_reset_without_link(db, payload.actor_type, actor.id, payload.email.strip(), name)
    return GENERIC_OK


@router.post("/set")
def set_password(payload: PasswordSetRequest, request: Request, db: Session = Depends(get_db)):
    record = consume_token(db, payload.token)
    if not record:
        raise HTTPException(status_code=400, detail="Link inválido ou expirado — peça um novo")

    try:
        validate_password_strength(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    model = _MODEL_BY_ACTOR_TYPE[record.actor_type]
    actor = db.get(model, record.actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    actor.password_hash = hash_password(payload.new_password)
    if hasattr(actor, "failed_attempts"):
        actor.failed_attempts = 0
    if hasattr(actor, "locked"):
        actor.locked = False
    db.commit()

    log_action(
        db,
        username=getattr(actor, "username", None),
        role=getattr(actor, "role", None) or ("Client" if record.actor_type == "client" else None),
        action="DEFINIR_SENHA" if record.purpose == "invite" else "REDEFINIR_SENHA",
        entity=f"{record.actor_type}:{actor.id}",
        origin="E-mail",
        ip_address=client_ip(request),
    )
    return {"ok": True}
