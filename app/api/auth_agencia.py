"""Login da equipe da agência licenciada — LicenseeUser, mesma tabela/cookie
(`session_agencia`) para os 3 portais que hoje rodam sobre ela:
- Portal Agência (Master, Administrador, Financeiro) — relação com Cliente/
  Operador + SAC, cobrança.
- Portal Operador (Operador de Caixa, Expedição) — fila de aferição/postagem.
- Portal SAC (SAC) — fila de encomendas com erro (ver app/api/shipments_sac.py).

Cada portal manda `portal: "agencia"|"operador"|"sac"` no login; abaixo só
valida que o papel do usuário bate com o portal que ele está tentando usar,
pra evitar confusão (ex.: um usuário Expedição logando sem querer no portal
Agência, que não tem nada pra ele fazer). Master/Administrador/Financeiro só
entram pelo portal Agência mesmo — pra mexer na fila Operador ou SAC como
esses papéis, usam o "modo suporte" (app/api/auth_support.py), igual já
funcionava entre Agência e Operador."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, get_current_licensee_user, verify_password
from app.models.models import Licensee, LicenseeUser
from app.schemas.schemas import LicenseeLookupRequest, LicenseeMatchOut, LicenseeUserLoginRequest, LicenseeUserOut
from app.services.audit import log_action
from app.services.params import get_param
from app.services.support_access import SUPPORT_USERNAME

router = APIRouter(prefix="/api/v1/auth/agencia", tags=["auth-agencia"])

# Qual(is) papel(éis) cada portal aceita. Um portal não listado aqui (não
# deveria acontecer, os 3 frontends mandam valor fixo) não é validado —
# mantém compatibilidade com qualquer chamada antiga que não mande `portal`.
PORTAL_ROLES: dict[str, tuple[str, ...]] = {
    "agencia": ("Master", "Administrador", "Financeiro"),
    "operador": ("Operador de Caixa", "Expedição"),
    "sac": ("SAC",),
}


@router.post("/login")
def login(payload: LicenseeUserLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    # `payload.username` aceita username OU e-mail — desde 2026-09-10 o
    # cadastro é sempre por e-mail, mas contas antigas continuam entrando
    # pelo username de sempre.
    identifier = payload.username.strip()
    user = (
        db.query(LicenseeUser)
        .filter(
            LicenseeUser.licensee_id == payload.licensee_id,
            or_(LicenseeUser.username.ilike(identifier), LicenseeUser.email.ilike(identifier)),
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

    allowed_roles = PORTAL_ROLES.get(payload.portal)
    if allowed_roles is not None and user.role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=f"Este usuário (perfil {user.role}) não acessa o portal '{payload.portal}' — confira se está no portal certo",
        )

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


@router.post("/lookup-licensee", response_model=list[LicenseeMatchOut])
def lookup_licensee(payload: LicenseeLookupRequest, db: Session = Depends(get_db)):
    """Resolve automaticamente em qual(is) agência(s) um e-mail está
    cadastrado — desde 2026-09-10 (tarde) dispensa a digitação manual do
    "Código do licenciado" na tela de login: o frontend chama isto assim que
    o e-mail é digitado e usa o resultado direto (1 resultado) ou mostra um
    seletor (mais de 1 — a mesma pessoa pode ter conta em mais de uma
    agência, já que o e-mail só é único *dentro* de cada licenciado, ver
    `uq_licensee_user_email`). Endpoint público (roda antes do login), só
    devolve id+nome da agência — nunca dado sensível da conta. Isso revela,
    de propósito, em quais agências um e-mail tem conta (é o próprio ponto do
    recurso), diferente do "Esqueci minha senha" (`/auth/password/forgot`),
    que continua com resposta genérica pra não vazar isso."""
    email = payload.email.strip().lower()
    allowed_roles = PORTAL_ROLES.get(payload.portal) if payload.portal else None
    query = (
        db.query(LicenseeUser, Licensee)
        .join(Licensee, Licensee.id == LicenseeUser.licensee_id)
        .filter(
            LicenseeUser.email.ilike(email),
            LicenseeUser.active.is_(True),
            LicenseeUser.username != SUPPORT_USERNAME,
        )
    )
    if allowed_roles is not None:
        query = query.filter(LicenseeUser.role.in_(allowed_roles))
    return [LicenseeMatchOut(id=licensee.id, name=licensee.trade_name or licensee.legal_name) for _, licensee in query.all()]


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session_agencia")
    return {"ok": True}


@router.get("/me", response_model=LicenseeUserOut)
def me(user: LicenseeUser = Depends(get_current_licensee_user)):
    return user
