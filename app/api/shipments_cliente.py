"""Emissão de etiquetas pelo cliente — manual (uma de cada vez, pelo portal)
ou por integração (POST em lote, autenticado com api_key). Depois que a
agência afere/precifica e posta, o cliente acompanha via GET aqui ou recebe
um webhook (ver app/services/webhooks.py e app/api/shipments_agencia.py)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_client
from app.models.models import Client, Shipment
from app.schemas.schemas import ShipmentBulkCreate, ShipmentCreate, ShipmentOut

router = APIRouter(prefix="/api/v1/cliente/shipments", tags=["shipments-cliente"])


def _create_shipment(db: Session, client: Client, payload: ShipmentCreate) -> Shipment:
    shipment = Shipment(
        licensee_id=client.licensee_id,
        client_id=client.id,
        status="Pendente",
        **payload.model_dump(),
    )
    db.add(shipment)
    return shipment


@router.post("", response_model=ShipmentOut)
def create_shipment(
    payload: ShipmentCreate, db: Session = Depends(get_db), client: Client = Depends(get_current_client)
):
    shipment = _create_shipment(db, client, payload)
    db.commit()
    db.refresh(shipment)
    return shipment


@router.post("/bulk", response_model=list[ShipmentOut])
def create_shipments_bulk(
    payload: ShipmentBulkCreate, db: Session = Depends(get_db), client: Client = Depends(get_current_client)
):
    """Pensado pra integração: manda várias etiquetas numa chamada só."""
    if len(payload.shipments) > 200:
        raise HTTPException(status_code=400, detail="Máximo de 200 etiquetas por chamada")
    shipments = [_create_shipment(db, client, item) for item in payload.shipments]
    db.commit()
    for shipment in shipments:
        db.refresh(shipment)
    return shipments


@router.get("", response_model=list[ShipmentOut])
def list_shipments(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    q = db.query(Shipment).filter(Shipment.client_id == client.id)
    if status:
        q = q.filter(Shipment.status == status)
    return q.order_by(Shipment.id.desc()).limit(500).all()


@router.get("/{shipment_id}", response_model=ShipmentOut)
def get_shipment(
    shipment_id: int, db: Session = Depends(get_db), client: Client = Depends(get_current_client)
):
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id, Shipment.client_id == client.id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Encomenda não encontrada")
    return shipment
