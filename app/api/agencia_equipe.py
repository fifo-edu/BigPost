"""Portal da loja (módulo Agência): a própria loja gerencia sua equipe e
consulta a agência postadora vinculada. Antes a equipe era cadastrada pelo
Admin do BigPost na tela de licenciados, que saiu do Admin (licença e lojas
vêm do Painel Master). Para uma loja nova sem nenhum usuário ainda, a equipe
BigPost entra em modo suporte (conta técnica com perfil Master) e cadastra o
primeiro Master por aqui.

Administrador gerencia a equipe abaixo dele; só Master cria, desativa ou
mexe em outro Master/Administrador."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import LICENSEE_ROLE_RANK, UNUSABLE_PASSWORD_HASH, require_licensee_role
from app.models.models import Licensee, LicenseeUser, PostingAgency
from app.schemas.schemas import (
    LICENSEE_ROLES,
    LicenseeUserCreate,
    LicenseeUserCreateOut,
    LicenseeUserOut,
    PasswordLinkOut,
    StorePostingAgencyOut,
)
from app.services.audit import log_action
from app.services.password_tokens import issue_and_notify
from app.services.support_access import SUPPORT_USERNAME

router = APIRouter(prefix="/api/v1/agencia", tags=["agencia-equipe"])


def _check_can_manage(actor: LicenseeUser, target_role: str) -> None:
    """Administrador só gerencia perfis abaixo do dele; Master gerencia todos."""
    if actor.role == "Master":
        return
    if LICENSEE_ROLE_RANK.get(target_role, 99) >= LICENSEE_ROLE_RANK.get(actor.role, 0):
        raise HTTPException(status_code=403, detail="Só o Master pode gerenciar usuários Master ou Administrador")


def _get_member(db: Session, actor: LicenseeUser, user_id: int) -> LicenseeUser:
    member = (
        db.query(LicenseeUser)
        .filter(
            LicenseeUser.id == user_id,
            LicenseeUser.licensee_id == actor.licensee_id,
            LicenseeUser.username != SUPPORT_USERNAME,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    _check_can_manage(actor, member.role)
    return member


def _audit(db: Session, actor: LicenseeUser, action: str, member: LicenseeUser, request: Request, **extra) -> None:
    log_action(
        db,
        username=actor.username,
        role=actor.role,
        action=action,
        entity=f"licensee:{actor.licensee_id}:{member.username}",
        origin="Agência",
        ip_address=client_ip(request),
        **extra,
    )


@router.get("/users", response_model=list[LicenseeUserOut])
def list_team(db: Session = Depends(get_db), actor: LicenseeUser = Depends(require_licensee_role("Administrador"))):
    return (
        db.query(LicenseeUser)
        .filter(LicenseeUser.licensee_id == actor.licensee_id, LicenseeUser.username != SUPPORT_USERNAME)
        .order_by(LicenseeUser.username)
        .all()
    )


@router.post("/users", response_model=LicenseeUserCreateOut)
def create_team_member(
    payload: LicenseeUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    """Cadastro por e-mail: a pessoa recebe um convite para definir a senha."""
    if payload.role not in LICENSEE_ROLES:
        raise HTTPException(status_code=400, detail="Perfil inválido")
    _check_can_manage(actor, payload.role)
    email = payload.email.strip().lower()
    member = LicenseeUser(
        licensee_id=actor.licensee_id,
        username=email,
        email=email,
        full_name=payload.full_name,
        role=payload.role,
        password_hash=UNUSABLE_PASSWORD_HASH,
        active=True,
        created_by=actor.username,
    )
    db.add(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um usuário com esse e-mail nesta loja")
    db.refresh(member)

    link, emailed = issue_and_notify(db, "licensee_user", member.id, "invite", email, member.full_name or email)
    _audit(db, actor, "CADASTRAR_USUARIO_AGENCIA", member, request, after={"role": member.role, "convite_emailed": emailed})
    return LicenseeUserCreateOut(
        **LicenseeUserOut.model_validate(member).model_dump(), invite_emailed=emailed, invite_link=None if emailed else link
    )


@router.post("/users/{user_id}/deactivate", response_model=LicenseeUserOut)
def deactivate_team_member(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    member = _get_member(db, actor, user_id)
    if member.id == actor.id:
        raise HTTPException(status_code=400, detail="Você não pode desativar o seu próprio usuário")
    member.active = False
    db.commit()
    db.refresh(member)
    _audit(db, actor, "DESATIVAR_USUARIO_AGENCIA", member, request)
    return member


@router.post("/users/{user_id}/reset-password", response_model=PasswordLinkOut)
def reset_team_member_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    member = _get_member(db, actor, user_id)
    link, emailed = issue_and_notify(
        db, "licensee_user", member.id, "reset", member.email, member.full_name or member.username
    )
    _audit(db, actor, "ZERAR_SENHA_USUARIO_AGENCIA", member, request, details={"emailed": emailed})
    return PasswordLinkOut(emailed=emailed, link=link)


@router.post("/users/{user_id}/unlock", response_model=LicenseeUserOut)
def unlock_team_member(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: LicenseeUser = Depends(require_licensee_role("Administrador")),
):
    member = _get_member(db, actor, user_id)
    member.locked = False
    member.failed_attempts = 0
    db.commit()
    db.refresh(member)
    _audit(db, actor, "DESBLOQUEAR_USUARIO_AGENCIA", member, request)
    return member


@router.get("/posting-agency", response_model=StorePostingAgencyOut | None)
def get_store_posting_agency(
    db: Session = Depends(get_db), actor: LicenseeUser = Depends(require_licensee_role("Operador de Caixa"))
):
    """Agência postadora vinculada à loja (null se ainda não vinculada)."""
    licensee = db.get(Licensee, actor.licensee_id)
    if not licensee or not licensee.posting_agency_id:
        return None
    return db.get(PostingAgency, licensee.posting_agency_id)
