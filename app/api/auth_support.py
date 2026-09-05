"""'Modo suporte' — ver app/services/support_access.py para a explicação
completa do fluxo e por que criamos uma conta técnica por licenciado em vez
de reaproveitar a sessão do usuário Master interno diretamente.

Resumo do fluxo, chamado a partir da tela de login da Agência, do Operador
ou do Cliente:
1. POST /login — usuário+senha de uma conta Master interna (tabela `users`,
   a mesma da Administração). Devolve uma sessão transitória de poucos
   minutos (cookie `session_support`) — ainda não dá acesso a nada.
2. GET /licensees — com a sessão transitória, lista os licenciados já
   sincronizados (vindos do Painel Master) pra escolher um.
3. POST /enter/{licensee_id} — entra automaticamente nesse licenciado,
   emitindo o cookie normal do portal pedido (session_agencia ou
   session_cliente), com acesso total (perfil Master). Consome a sessão
   transitória (só dá pra usar uma vez por login)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, get_current_support_user, verify_password
from app.models.models import Licensee, User
from app.schemas.schemas import SupportEnterRequest, SupportLicenseeOut, SupportLoginRequest
from app.services.audit import log_action
from app.services.params import get_param
from app.services.support_access import get_or_create_support_client, get_or_create_support_licensee_user

router = APIRouter(prefix="/api/v1/auth/support", tags=["auth-support"])

# Sessão transitória curta — só o tempo de escolher o licenciado na tela
# seguinte, não uma sessão de trabalho de verdade.
SUPPORT_SESSION_SECONDS = 10 * 60


@router.post("/login")
def login(payload: SupportLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(User.username.ilike(payload.username), User.active.is_(True))
        .first()
    )
    if user and user.locked:
        raise HTTPException(status_code=423, detail="Conta bloqueada por excesso de tentativas — peça a um Master para desbloquear")

    if not user or user.role != "Master" or not verify_password(payload.password, user.password_hash):
        if user and user.role == "Master":
            max_attempts = get_param(db, "security.login_max_attempts", 5)
            user.failed_attempts += 1
            if user.failed_attempts >= max_attempts:
                user.locked = True
            db.commit()
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    if user.failed_attempts:
        user.failed_attempts = 0
        db.commit()

    token = create_token(user.username, "support", {"role": user.role}, expire_seconds=SUPPORT_SESSION_SECONDS)
    response.set_cookie(
        "session_support", token, httponly=True, samesite="strict", secure=settings.cookie_secure,
        max_age=SUPPORT_SESSION_SECONDS,
    )
    log_action(
        db, username=user.username, role=user.role, action="LOGIN_SUPORTE",
        origin="Suporte", ip_address=client_ip(request),
    )
    return {"ok": True}


@router.get("/licensees", response_model=list[SupportLicenseeOut])
def list_licensees(db: Session = Depends(get_db), support_user: User = Depends(get_current_support_user)):
    return db.query(Licensee).order_by(Licensee.trade_name, Licensee.legal_name).all()


@router.post("/enter/{licensee_id}")
def enter(
    licensee_id: int,
    payload: SupportEnterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    support_user: User = Depends(get_current_support_user),
):
    licensee = db.get(Licensee, licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")

    if payload.portal in ("agencia", "operador"):
        lu = get_or_create_support_licensee_user(db, licensee_id)
        token = create_token(lu.username, "licensee_user", {"uid": lu.id, "licensee_id": lu.licensee_id, "role": lu.role})
        response.set_cookie(
            "session_agencia", token, httponly=True, samesite="strict", secure=settings.cookie_secure, max_age=60 * 60 * 8
        )
    elif payload.portal == "cliente":
        client = get_or_create_support_client(db, licensee_id)
        token = create_token(client.username, "client", {"uid": client.id})
        response.set_cookie(
            "session_cliente", token, httponly=True, samesite="strict", secure=settings.cookie_secure, max_age=60 * 60 * 8
        )
    else:
        raise HTTPException(status_code=400, detail="Portal inválido")

    response.delete_cookie("session_support")
    log_action(
        db, username=support_user.username, role=support_user.role, action="ENTRAR_SUPORTE",
        entity=f"licensee:{licensee_id}", origin="Suporte",
        details={"portal": payload.portal, "licenciado": licensee.trade_name or licensee.legal_name},
        ip_address=client_ip(request),
    )
    return {"ok": True, "licensee": {"id": licensee.id, "name": licensee.trade_name or licensee.legal_name}}


@router.post("/cancel")
def cancel(response: Response):
    """Desiste da escolha de licenciado (botão 'voltar' na tela de suporte)."""
    response.delete_cookie("session_support")
    return {"ok": True}
