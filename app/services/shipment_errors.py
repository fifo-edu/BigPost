"""Coloca uma encomenda na fila de erro do SAC: status 'Erro', evento no
histórico, e-mail automático para o cliente (se houver SMTP e e-mail) e
webhook `shipment.erro`. Usado pelo carimbo manual do SAC
(app/api/shipments_sac.py) e pela postagem automática quando os Correios
recusam o objeto (app/api/shipments_agencia.py). A auditoria fica com quem
chama, porque a origem (SAC, Agência) muda."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import Client, Shipment, ShipmentEvent
from app.services.email import send_email
from app.services.webhooks import send_shipment_webhook


def marcar_erro(db: Session, shipment: Shipment, error_code: str | None, error_message: str, created_by: str) -> None:
    shipment.status = "Erro"
    shipment.error_code = error_code
    shipment.error_message = error_message
    shipment.error_flagged_at = datetime.utcnow()
    db.add(ShipmentEvent(shipment_id=shipment.id, status="Erro", description=error_message, created_by=created_by))
    db.commit()
    db.refresh(shipment)

    client = db.get(Client, shipment.client_id)
    if client and client.contact_email:
        sent = send_email(
            client.contact_email,
            f"Encomenda #{shipment.id} com pendência",
            (
                f"Olá, {client.legal_name}.\n\n"
                f"A encomenda #{shipment.id} (destinatário: {shipment.recipient_name}) não pôde ser "
                f"processada:\n\n{error_message}\n\n"
                "Acesse o Portal BigPost Cliente para recriar a etiqueta com os dados corrigidos, se for "
                "o caso."
            ),
        )
        if sent:
            shipment.error_notified_at = datetime.utcnow()
            db.commit()
            db.refresh(shipment)

    if client:
        send_shipment_webhook(db, client, shipment, "shipment.erro")
