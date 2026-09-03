"""Login da equipe da agência licenciada (módulo Agência) — LicenseeUser.
Papéis: Master, Administrador, Financeiro, Operador de Caixa, Expedição."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, get_current_licensee_user, verify_password
from app.models.models import LicenseeUser
from app.schemas.schemas import LicenseeUserLoginRequest, LicenseeUserOut
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/auth/agencia", tags=["auth-agencia"])


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
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

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
