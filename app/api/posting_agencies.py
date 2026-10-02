"""Agências postadoras (AGF): cadastro feito no Admin do BigPost, com MCU e
login do site Correios Atende. Diferente da loja licenciada, que vem do
Painel Master — aqui só se vincula quais lojas cada agência atende (uma
agência atende várias lojas; cada loja posta por uma só). A senha do Correios
Atende é guardada criptografada e nunca volta pela API."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_role
from app.models.models import Licensee, PostingAgency, User
from app.schemas.schemas import (
    PostingAgencyOut,
    PostingAgencyStoresUpdate,
    PostingAgencyUpsert,
    StoreOptionOut,
)
from app.services.audit import log_action
from app.services.crypto import encrypt

router = APIRouter(prefix="/api/v1/posting-agencies", tags=["posting-agencies"])


def _to_out(db: Session, agency: PostingAgency) -> PostingAgencyOut:
    stores = (
        db.query(Licensee)
        .filter(Licensee.posting_agency_id == agency.id)
        .order_by(Licensee.legal_name)
        .all()
    )
    fields = set(PostingAgencyOut.model_fields) - {"stores", "has_correios_password"}
    return PostingAgencyOut(
        **{f: getattr(agency, f) for f in fields},
        has_correios_password=bool(agency.correios_password_encrypted),
        stores=[StoreOptionOut.model_validate(s) for s in stores],
    )


def _get_or_404(db: Session, agency_id: int) -> PostingAgency:
    agency = db.get(PostingAgency, agency_id)
    if not agency:
        raise HTTPException(status_code=404, detail="Agência postadora não encontrada")
    return agency


def _audit_data(agency: PostingAgency) -> dict:
    return {"tax_id": agency.tax_id, "mcu": agency.mcu, "correios_username": agency.correios_username}


def _save(db: Session, agency: PostingAgency, payload: PostingAgencyUpsert) -> None:
    for field, value in payload.model_dump(exclude={"correios_password"}).items():
        setattr(agency, field, value)
    if payload.correios_password:
        agency.correios_password_encrypted = encrypt(payload.correios_password)
    agency.updated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe uma agência postadora com esse CNPJ")
    db.refresh(agency)


@router.get("", response_model=list[PostingAgencyOut])
def list_agencies(db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))):
    return [_to_out(db, a) for a in db.query(PostingAgency).order_by(PostingAgency.legal_name).all()]


@router.get("/stores", response_model=list[StoreOptionOut])
def list_stores(db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))):
    """Lojas disponíveis para vincular a uma agência postadora."""
    return db.query(Licensee).order_by(Licensee.legal_name).all()


@router.get("/{agency_id}", response_model=PostingAgencyOut)
def get_agency(agency_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("Supervisor"))):
    return _to_out(db, _get_or_404(db, agency_id))


@router.post("", response_model=PostingAgencyOut)
def create_agency(
    payload: PostingAgencyUpsert,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    agency = PostingAgency(created_by=user.username)
    db.add(agency)
    _save(db, agency, payload)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_AGENCIA_POSTADORA",
        entity=f"posting_agency:{agency.id}",
        after=_audit_data(agency),
        ip_address=client_ip(request),
    )
    return _to_out(db, agency)


@router.put("/{agency_id}", response_model=PostingAgencyOut)
def update_agency(
    agency_id: int,
    payload: PostingAgencyUpsert,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    agency = _get_or_404(db, agency_id)
    before = _audit_data(agency)
    _save(db, agency, payload)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ATUALIZAR_AGENCIA_POSTADORA",
        entity=f"posting_agency:{agency.id}",
        before=before,
        after={**_audit_data(agency), "senha_alterada": bool(payload.correios_password)},
        ip_address=client_ip(request),
    )
    return _to_out(db, agency)


@router.put("/{agency_id}/stores", response_model=PostingAgencyOut)
def set_agency_stores(
    agency_id: int,
    payload: PostingAgencyStoresUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    """Define a lista completa de lojas atendidas por esta agência. Uma loja
    marcada aqui sai da agência anterior (cada loja posta por uma só)."""
    agency = _get_or_404(db, agency_id)
    wanted = set(payload.licensee_ids)
    found = {lic.id: lic for lic in db.query(Licensee).filter(Licensee.id.in_(wanted)).all()} if wanted else {}
    missing = wanted - found.keys()
    if missing:
        raise HTTPException(status_code=400, detail=f"Loja(s) não encontrada(s): {sorted(missing)}")

    moved = sorted(lic.id for lic in found.values() if lic.posting_agency_id not in (None, agency.id))
    for lic in db.query(Licensee).filter(Licensee.posting_agency_id == agency.id).all():
        if lic.id not in wanted:
            lic.posting_agency_id = None
    for lic in found.values():
        lic.posting_agency_id = agency.id
    db.commit()

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="VINCULAR_LOJAS_AGENCIA_POSTADORA",
        entity=f"posting_agency:{agency.id}",
        after={"licensee_ids": sorted(wanted), "movidas_de_outra_agencia": moved},
        ip_address=client_ip(request),
    )
    return _to_out(db, agency)
