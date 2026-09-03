"""Disparo de webhook para o cliente quando o status de uma encomenda muda —
é assim que o cliente sabe que a agência aferiu/precificou/postou, sem
precisar ficar consultando a API ("painel de acompanhamento de envios, via
webhook").

Entrega síncrona e best-effort (com log em `webhook_deliveries` pra permitir
retry manual/depuração depois) — pra produção real, o ponto natural de
evolução é mover isso pra uma fila (RQ/Celery/etc.) em vez de bloquear a
requisição HTTP que originou a mudança de status; deixado síncrono aqui por
simplicidade, já documentado como próximo passo no README.
"""
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import Client, Shipment, WebhookDelivery

TIMEOUT_SECONDS = 6


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send_shipment_webhook(db: Session, client: Client, shipment: Shipment, event_type: str) -> None:
    if not client.webhook_url:
        return  # cliente não configurou webhook — nada a fazer

    payload = {
        "event": event_type,
        "shipment_id": shipment.id,
        "external_reference": shipment.external_reference,
        "status": shipment.status,
        "tracking_code": shipment.tracking_code,
        "weight_confirmed_kg": float(shipment.weight_confirmed_kg) if shipment.weight_confirmed_kg is not None else None,
        "price_confirmed": float(shipment.price_confirmed) if shipment.price_confirmed is not None else None,
        "occurred_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()

    delivery = WebhookDelivery(
        client_id=client.id,
        shipment_id=shipment.id,
        event_type=event_type,
        url=client.webhook_url,
        payload=payload,
        success=False,
    )

    headers = {"Content-Type": "application/json"}
    if client.webhook_secret:
        headers["X-BigPost-Signature"] = "sha256=" + _sign(client.webhook_secret, body)

    try:
        req = urllib.request.Request(client.webhook_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            delivery.response_status = resp.status
            delivery.success = 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        delivery.response_status = e.code
        delivery.error_message = str(e)[:255]
    except Exception as e:  # DNS, timeout, conexão recusada etc.
        delivery.error_message = str(e)[:255]

    db.add(delivery)
    db.commit()
