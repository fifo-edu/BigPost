"""Portal SAC — fila de encomendas com erro.

Fluxo (confirmado com o Wesley): o cliente cria a encomenda pelo Portal
Cliente; quando a validação do CWS/PPN recusa (hoje um carimbo manual aqui —
o webhook real de validação automática depende do contrato de Pré-Postagem/
PPN ainda não confirmado, ver app/services/correios_cws.py), ela cai nesta
fila com o erro registrado. O cliente é avisado por e-mail automático (se o
SMTP estiver configurado — app/services/email.py) e decide se recria a
etiqueta (com dados corrigidos, número novo — ver
POST /api/v1/cliente/shipments/{id}/recriar em app/api/shipments_cliente.py).
O SAC não cria nada na PPN — só trata objetos já existentes: enxerga a fila
de erro, acompanha a recriação e marca quando imprimiu a etiqueta recriada
antes dela voltar pra fila normal de aferição do Operador.

Ações restritas ao papel SAC (e, por causa de require_licensee_any_role,
também Administrador/Master — mas não Operador de Caixa/Expedição, que não
mexem nesta fila)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_licensee_any_role
from app.models.models import LicenseeUser, Shipment, ShipmentEvent
from app.schemas.schemas import ShipmentErrorFlagRequest, ShipmentOut
from app.services.audit import log_action
from app.services.shipment_errors import marcar_erro

router = APIRouter(prefix="/api/v1/sac/shipments", tags=["shipments-sac"])


def _get_shipment(db: Session, licensee_id: int, shipment_id: int) -> Shipment:
    shipment = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_id, Shipment.licensee_id == licensee_id)
        .first()
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="Encomenda não encontrada")
    return shipment


@router.get("", response_model=list[ShipmentOut])
def list_queue(
    fila: str = Query(default="erros", pattern="^(erros|impressao)$"),
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("SAC")),
):
    """`fila=erros` (padrão): encomendas carimbadas com erro, aguardando o
    cliente decidir (ou já aguardando a recriação ser impressa não aparece
    aqui — some da fila de erro assim que vira Erro->recriada, ela é uma
    encomenda nova). `fila=impressao`: etiquetas recriadas pelo cliente que
    o SAC ainda não marcou como impressas."""
    q = db.query(Shipment).filter(Shipment.licensee_id == user.licensee_id)
    if fila == "erros":
        q = q.filter(Shipment.status == "Erro")
    else:
        q = q.filter(Shipment.replaces_shipment_id.isnot(None), Shipment.sac_printed_at.is_(None))
    return q.order_by(Shipment.id.desc()).limit(500).all()


@router.post("/{shipment_id}/flag-erro", response_model=ShipmentOut)
def flag_erro(
    shipment_id: int,
    payload: ShipmentErrorFlagRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("SAC")),
):
    shipment = _get_shipment(db, user.licensee_id, shipment_id)
    if shipment.status in ("Postado", "Em Trânsito", "Entregue", "Devolvido", "Cancelado", "Erro"):
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível carimbar erro numa encomenda com status {shipment.status}",
        )

    marcar_erro(db, shipment, payload.error_code, payload.error_message, user.username)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="FLAG_ERRO_ENCOMENDA",
        entity=f"shipment:{shipment.id}",
        after={"error_code": payload.error_code, "error_message": payload.error_message},
        origin="SAC",
        ip_address=client_ip(request),
    )
    return shipment


@router.post("/{shipment_id}/imprimir", response_model=ShipmentOut)
def marcar_impresso(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("SAC")),
):
    """Marca que o SAC imprimiu a etiqueta de uma encomenda recriada — não
    muda o status (ela já está Pendente, pronta pra aferição normal do
    Operador), só registra quem/quando imprimiu."""
    shipment = _get_shipment(db, user.licensee_id, shipment_id)
    if shipment.replaces_shipment_id is None:
        raise HTTPException(status_code=400, detail="Esta encomenda não é uma recriação — nada a imprimir aqui")
    if shipment.sac_printed_at is not None:
        raise HTTPException(status_code=400, detail="Esta etiqueta já foi marcada como impressa")

    shipment.sac_printed_at = datetime.utcnow()
    shipment.sac_printed_by = user.id
    db.add(
        ShipmentEvent(
            shipment_id=shipment.id,
            status=shipment.status,
            description="Etiqueta recriada impressa pelo SAC — liberada para aferição",
            created_by=user.username,
        )
    )
    db.commit()
    db.refresh(shipment)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="IMPRIMIR_ETIQUETA_RECRIADA",
        entity=f"shipment:{shipment.id}",
        origin="SAC",
        ip_address=client_ip(request),
    )
    return shipment
