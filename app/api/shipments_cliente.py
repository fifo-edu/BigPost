"""Emissão de etiquetas pelo cliente — manual (uma de cada vez, pelo portal)
ou por integração (POST em lote, autenticado com api_key). Depois que a
agência afere/precifica e posta, o cliente acompanha via GET aqui ou recebe
um webhook (ver app/services/webhooks.py e app/api/shipments_agencia.py).

Inclui também a recriação de etiqueta (POST /{id}/recriar) — quando uma
encomenda cai na fila de erro do SAC (status 'Erro', ver
app/api/shipments_sac.py) e o cliente decide corrigir e reenviar: gera uma
NOVA encomenda (número novo) com os dados informados, referenciando a
original via `replaces_shipment_id`. A original nunca é sobrescrita — fica
como histórico com status 'Erro'."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_client
from app.models.models import Client, Shipment, ShipmentEvent
from app.schemas.schemas import ShipmentBulkCreate, ShipmentCreate, ShipmentOut
from app.services.webhooks import send_shipment_webhook

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


@router.post("/{shipment_id}/recriar", response_model=ShipmentOut)
def recriar_shipment(
    shipment_id: int,
    payload: ShipmentCreate,
    db: Session = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    """Recria uma encomenda que caiu em erro, com os dados corrigidos pelo
    cliente (`payload` é uma etiqueta nova por completo — não um patch da
    antiga). Só permitido a partir de uma encomenda própria com status
    'Erro'; a original não é alterada."""
    original = db.query(Shipment).filter(Shipment.id == shipment_id, Shipment.client_id == client.id).first()
    if not original:
        raise HTTPException(status_code=404, detail="Encomenda não encontrada")
    if original.status != "Erro":
        raise HTTPException(status_code=400, detail="Só é possível recriar uma encomenda com status Erro")

    new_shipment = Shipment(
        licensee_id=client.licensee_id,
        client_id=client.id,
        status="Pendente",
        replaces_shipment_id=original.id,
        **payload.model_dump(),
    )
    db.add(new_shipment)
    db.flush()
    db.add(
        ShipmentEvent(
            shipment_id=new_shipment.id,
            status="Pendente",
            description=f"Recriada pelo cliente a partir da encomenda #{original.id} (erro: {original.error_message or '—'})",
            created_by=client.username,
        )
    )
    db.commit()
    db.refresh(new_shipment)

    send_shipment_webhook(db, client, new_shipment, "shipment.recriada")
    return new_shipment
