"""Login da equipe da agência licenciada — LicenseeUser, mesma tabela/cookie
(`session_agencia`) para os 2 portais que hoje rodam sobre ela:
- Portal Agência (Master, Administrador, Financeiro) — relação com Cliente/
  Operador + SAC.
- Portal Operador (Operador de Caixa, Expedição) — fila de aferição/postagem.

Cada portal manda `portal: "agencia"|"operador"` no login; abaixo só valida
que o papel do usuário bate com o portal que ele está tentando usar, pra
evitar confusão (ex.: um usuário Expedição logando sem querer no portal
Agência, que não tem nada pra ele fazer)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import LICENSEE_ROLE_RANK, create_token, get_current_licensee_user, verify_password
from app.models.models import LicenseeUser
from app.schemas.schemas import LicenseeUserLoginRequest, LicenseeUserOut
from app.services.audit import log_action
from app.services.params import get_param

router = APIRouter(prefix="/api/v1/auth/agencia", tags=["auth-agencia"])

# Papéis operacionais (fila de aferição/postagem) — usam o portal Operador.
# Os demais (Master, Administrador, Financeiro) usam o portal Agência.
OPERATIONAL_ROLES = tuple(role for role in LICENSEE_ROLE_RANK if LICENSEE_ROLE_RANK[role] == 1)


@router.post("/login")
def login(payload: LicenseeUserLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = (
        db.query(LicenseeUser)
        .filter(
            LicenseeUser.licensee_id == payload.licensee_id,
            LicenseeUser.username.ilike(payload.username),
            LicenseeUser.active.is_(True),
        )
        .first()
    )
    if user and user.locked:
        raise HTTPException(status_code=423, detail="Conta bloqueada por excesso de tentativas — peça ao administrador da agência para desbloquear")

    if not user or not verify_password(payload.password, user.password_hash):
        if user:
            max_attempts = get_param(db, "security.login_max_attempts", 5)
            user.failed_attempts += 1
            if user.failed_attempts >= max_attempts:
                user.locked = True
            db.commit()
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    if user.failed_attempts:
        user.failed_attempts = 0
        db.commit()

    is_operational = user.role in OPERATIONAL_ROLES
    if payload.portal == "operador" and not is_operational:
        raise HTTPException(status_code=403, detail="Este usuário não é da equipe operacional — acesse pelo portal da Agência")
    if payload.portal == "agencia" and is_operational:
        raise HTTPException(status_code=403, detail="Este usuário é da equipe operacional — acesse pelo portal Operador")

    token = create_token(
        user.username, "licensee_user", {"uid": user.id, "licensee_id": user.licensee_id, "role": user.role}
    )
    response.set_cookie(
        "session_agencia", token, httponly=True, samesite="strict", secure=settings.cookie_secure, max_age=60 * 60 * 8
    )
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="LOGIN_AGENCIA",
        entity=f"licensee:{user.licensee_id}",
        origin="Agência",
        ip_address=client_ip(request),
    )
    return {"ok": True, "user": LicenseeUserOut.model_validate(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session_agencia")
    return {"ok": True}


@router.get("/me", response_model=LicenseeUserOut)
def me(user: LicenseeUser = Depends(get_current_licensee_user)):
    return user
