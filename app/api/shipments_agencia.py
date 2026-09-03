"""Processamento de encomendas pelo módulo Agência: fila de coleta, aferição
(pesagem/precificação — só Operador de Caixa, ou Administrador/Master),
postagem (código de rastreio — só Expedição, ou Administrador/Master) e
lançamento manual de eventos de rastreio. Cada mudança de status dispara um
webhook assinado pro cliente dono da encomenda (ver app/services/webhooks.py)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_licensee_any_role, require_licensee_role
from app.models.models import Client, LicenseeUser, Shipment, ShipmentEvent
from app.schemas.schemas import (
    ShipmentAfericaoRequest,
    ShipmentEventCreate,
    ShipmentEventOut,
    ShipmentOut,
    ShipmentPostagemRequest,
)
from app.services.audit import log_action
from app.services.webhooks import send_shipment_webhook

router = APIRouter(prefix="/api/v1/agencia/shipments", tags=["shipments-agencia"])


def _get_shipment(db: Session, licensee_id: int, shipment_id: int) -> Shipment:
    shipment = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_id, Shipment.licensee_id == licensee_id)
        .first()
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="Encomenda não encontrada")
    return shipment


def _add_event(db: Session, shipment: Shipment, status: str, description: str | None, created_by: str) -> None:
    db.add(
        ShipmentEvent(
            shipment_id=shipment.id,
            status=status,
            description=description,
            created_by=created_by,
        )
    )


def _notify(db: Session, shipment: Shipment, event_type: str) -> None:
    client = db.get(Client, shipment.client_id)
    if client:
        send_shipment_webhook(db, client, shipment, event_type)


@router.get("", response_model=list[ShipmentOut])
def list_shipments(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa")),
):
    """Fila de trabalho da agência — por padrão mostra tudo; filtra por
    status (ex. ?status=Pendente pra fila de coleta/aferição)."""
    q = db.query(Shipment).filter(Shipment.licensee_id == user.licensee_id)
    if status:
        q = q.filter(Shipment.status == status)
    return q.order_by(Shipment.id.asc()).limit(500).all()


@router.get("/{shipment_id}", response_model=ShipmentOut)
def get_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa")),
):
    return _get_shipment(db, user.licensee_id, shipment_id)


@router.post("/{shipment_id}/aferir", response_model=ShipmentOut)
def aferir_shipment(
    shipment_id: int,
    payload: ShipmentAfericaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("Operador de Caixa")),
):
    shipment = _get_shipment(db, user.licensee_id, shipment_id)
    if shipment.status != "Pendente":
        raise HTTPException(status_code=400, detail="Só é possível aferir encomendas com status Pendente")

    shipment.weight_confirmed_kg = payload.weight_confirmed_kg
    shipment.price_confirmed = payload.price_confirmed
    shipment.afericao_by = user.id
    shipment.afericao_at = datetime.utcnow()
    shipment.status = "Aferido"
    _add_event(db, shipment, "Aferido", "Peso e preço confirmados pela agência", user.username)
    db.commit()
    db.refresh(shipment)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="AFERIR_ENCOMENDA",
        entity=f"shipment:{shipment.id}",
        after={"weight_confirmed_kg": float(payload.weight_confirmed_kg), "price_confirmed": float(payload.price_confirmed)},
        origin="Agência",
        ip_address=client_ip(request),
    )
    _notify(db, shipment, "shipment.aferido")
    return shipment


@router.post("/{shipment_id}/postar", response_model=ShipmentOut)
def postar_shipment(
    shipment_id: int,
    payload: ShipmentPostagemRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("Expedição")),
):
    shipment = _get_shipment(db, user.licensee_id, shipment_id)
    if shipment.status != "Aferido":
        raise HTTPException(status_code=400, detail="Só é possível postar encomendas com status Aferido")

    shipment.tracking_code = payload.tracking_code
    shipment.postado_by = user.id
    shipment.postado_at = datetime.utcnow()
    shipment.status = "Postado"
    _add_event(db, shipment, "Postado", f"Postado com código de rastreio {payload.tracking_code}", user.username)
    db.commit()
    db.refresh(shipment)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="POSTAR_ENCOMENDA",
        entity=f"shipment:{shipment.id}",
        after={"tracking_code": payload.tracking_code},
        origin="Agência",
        ip_address=client_ip(request),
    )
    _notify(db, shipment, "shipment.postado")
    return shipment


@router.post("/{shipment_id}/eventos", response_model=ShipmentEventOut)
def add_event(
    shipment_id: int,
    payload: ShipmentEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa")),
):
    """Lançamento manual de evento de rastreio (ex.: 'Em Trânsito', 'Entregue',
    'Devolvido') — pra quando ainda não há integração automática de rastreio
    dos Correios atualizando isso sozinho."""
    shipment = _get_shipment(db, user.licensee_id, shipment_id)
    shipment.status = payload.status
    _add_event(db, shipment, payload.status, payload.description, user.username)
    db.commit()

    event = (
        db.query(ShipmentEvent)
        .filter(ShipmentEvent.shipment_id == shipment.id)
        .order_by(ShipmentEvent.id.desc())
        .first()
    )

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="EVENTO_ENCOMENDA",
        entity=f"shipment:{shipment.id}",
        after={"status": payload.status, "description": payload.description},
        origin="Agência",
        ip_address=client_ip(request),
    )
    _notify(db, shipment, "shipment.evento")
    return event


@router.get("/{shipment_id}/eventos", response_model=list[ShipmentEventOut])
def list_events(
    shipment_id: int,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa")),
):
    _get_shipment(db, user.licensee_id, shipment_id)
    return (
        db.query(ShipmentEvent)
        .filter(ShipmentEvent.shipment_id == shipment_id)
        .order_by(ShipmentEvent.occurred_at.asc())
        .all()
    )
