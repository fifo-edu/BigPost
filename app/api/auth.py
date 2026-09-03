from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_access_token, get_current_user, verify_password
from app.models.models import User
from app.schemas.schemas import LoginRequest, UserOut
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(User.username.ilike(payload.username), User.active.is_(True))
        .first()
    )
    if not user or not verify_password(payload.password, user.password_hash):
        log_action(
            db,
            username=payload.username,
            role=None,
            action="LOGIN_FALHOU",
            result="ERRO",
            origin="Manual",
            ip_address=client_ip(request),
        )
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    token = create_access_token(user)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 8,
    )
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="LOGIN",
        origin="Manual",
        ip_address=client_ip(request),
    )
    return {"ok": True, "user": UserOut.model_validate(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
