from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import get_current_user, require_role
from app.models.models import Licensee, User
from app.schemas.schemas import LicenseeCreate, LicenseeOut, LicenseeStatusUpdate
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/licensees", tags=["licensees"])

VALID_STATUS = ("Ativo", "Inadimplente", "Bloqueado", "Expirado")


def _serialize(licensee: Licensee, user: User) -> LicenseeOut:
    """`notes` é de uso interno do Master (anotação livre sobre o licenciado,
    ex.: combinados de cobrança, histórico de problema) — Supervisor/Operador
    continuam vendo o resto do cadastro normalmente, só esse campo é
    zerado na resposta para eles."""
    out = LicenseeOut.model_validate(licensee)
    if user.role != "Master":
        out.notes = None
    return out


@router.get("", response_model=list[LicenseeOut])
def list_licensees(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Licensee).order_by(Licensee.id.desc()).all()
    return [_serialize(row, user) for row in rows]


@router.get("/{licensee_id}", response_model=LicenseeOut)
def get_licensee(licensee_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    licensee = db.get(Licensee, licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")
    return _serialize(licensee, user)


@router.post("", response_model=LicenseeOut)
def create_licensee(
    payload: LicenseeCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.person_type not in ("PJ", "PF"):
        raise HTTPException(status_code=400, detail="Tipo de pessoa inválido")
    licensee = Licensee(**payload.model_dump(), created_by=user.username)
    db.add(licensee)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="CNPJ/CPF já cadastrado")
    db.refresh(licensee)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_LICENCIADO",
        entity=licensee.legal_name,
        after={"id": licensee.id, "tax_id": licensee.tax_id},
        ip_address=client_ip(request),
    )
    return licensee


@router.put("/{licensee_id}", response_model=LicenseeOut)
def update_licensee(
    licensee_id: int,
    payload: LicenseeCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Master")),
):
    """Edição local do cadastro do licenciado (endereço, contato, faturamento,
    observações) — pensada para o dia a dia (ex.: agência mudou de endereço,
    trocou o contato), não para reescrever o vínculo com o Painel Master.
    Por isso só Master pode chamar, e o frontend mantém `tax_id` (a chave que
    o Painel Master usa para casar o licenciado numa próxima sincronização)
    somente leitura — mudar aqui não impede tecnicamente, mas descasa do que
    o Painel Master reconhece. Uma sincronização futura do Painel Master
    ainda sobrescreve tudo que ele manda (é um upsert completo), então essa
    edição local vale até a próxima sincronização de lá."""
    licensee = db.get(Licensee, licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")
    before = {"legal_name": licensee.legal_name, "status": licensee.status}
    for field, value in payload.model_dump().items():
        setattr(licensee, field, value)
    licensee.updated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="CNPJ/CPF já cadastrado em outro licenciado")
    db.refresh(licensee)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ATUALIZAR_LICENCIADO",
        entity=licensee.legal_name,
        before=before,
        after={"legal_name": licensee.legal_name},
        ip_address=client_ip(request),
    )
    return licensee


@router.post("/{licensee_id}/status", response_model=LicenseeOut)
def set_status(
    licensee_id: int,
    payload: LicenseeStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    if payload.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="Status inválido")
    licensee = db.get(Licensee, licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")
    before_status = licensee.status
    licensee.status = payload.status
    db.commit()
    db.refresh(licensee)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="ALTERAR_STATUS_LICENCIADO",
        entity=f"licensee:{licensee_id}",
        before={"status": before_status},
        after={"status": payload.status},
        ip_address=client_ip(request),
    )
    return licensee
