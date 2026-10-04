"""Processamento de encomendas pelo módulo Agência: fila de coleta, aferição
(pesagem/precificação — só Operador de Caixa, ou Administrador/Master),
postagem (código de rastreio — só Expedição, ou Administrador/Master),
postagem automática pelo Correios Atende com as credenciais da agência
postadora da loja (app/services/correios_atende.py) e lançamento manual de
eventos de rastreio. Cada mudança de status dispara um
webhook assinado pro cliente dono da encomenda (ver app/services/webhooks.py)."""
import logging
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
    PostagemAutomaticaStatusOut,
    ShipmentPostagemRequest,
)
from app.services import correios_atende
from app.services.audit import log_action
from app.services.correios_atende import AtendeConfigError, AtendeRecusa, CorreiosAtendeError
from app.services.cubagem import calcular_com_params
from app.services.params import get_param
from app.services.shipment_errors import marcar_erro
from app.services.webhooks import send_shipment_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agencia/shipments", tags=["shipments-agencia"])


def _get_shipment(db: Session, licensee_id: int, shipment_id: int, *, lock: bool = False) -> Shipment:
    q = db.query(Shipment).filter(Shipment.id == shipment_id, Shipment.licensee_id == licensee_id)
    if lock:
        # Trava a linha até o commit: dois cliques em "postar" não podem
        # mandar o mesmo objeto duas vezes aos Correios.
        q = q.with_for_update()
    shipment = q.first()
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


def _postagem_automatica_status(db: Session, licensee_id: int) -> PostagemAutomaticaStatusOut:
    if not get_param(db, "postagem.atende_automatica", False):
        return PostagemAutomaticaStatusOut(
            ativa=False, pronta=False, motivo="Postagem automática desligada (parâmetro postagem.atende_automatica)."
        )
    try:
        cred = correios_atende.credencial_da_loja(db, licensee_id)
    except AtendeConfigError as exc:
        return PostagemAutomaticaStatusOut(ativa=True, pronta=False, motivo=exc.message)
    if not correios_atende.IMPLEMENTADA:
        return PostagemAutomaticaStatusOut(
            ativa=True,
            pronta=False,
            agencia=cred.agency_name,
            motivo="Integração com o Correios Atende ainda não disponível — poste manualmente.",
        )
    return PostagemAutomaticaStatusOut(ativa=True, pronta=True, agencia=cred.agency_name)


@router.get("/postagem-automatica", response_model=PostagemAutomaticaStatusOut)
def postagem_automatica_status(
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_role("Operador de Caixa")),
):
    """Se o operador desta loja pode usar "Aferir e postar" agora."""
    return _postagem_automatica_status(db, user.licensee_id)


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
    _aplicar_afericao(db, shipment, payload, user, request)
    return shipment


def _aplicar_afericao(
    db: Session, shipment: Shipment, payload: ShipmentAfericaoRequest, user: LicenseeUser, request: Request
) -> None:
    cubagem = calcular_com_params(
        db,
        payload.weight_confirmed_kg,
        payload.length_measured_cm,
        payload.width_measured_cm,
        payload.height_measured_cm,
    )
    shipment.weight_confirmed_kg = payload.weight_confirmed_kg
    shipment.length_measured_cm = payload.length_measured_cm
    shipment.width_measured_cm = payload.width_measured_cm
    shipment.height_measured_cm = payload.height_measured_cm
    shipment.cubed_weight_kg = cubagem.cubed_weight_kg
    shipment.billable_weight_kg = cubagem.billable_weight_kg
    shipment.price_confirmed = payload.price_confirmed
    shipment.afericao_by = user.id
    shipment.afericao_at = datetime.utcnow()
    shipment.status = "Aferido"
    if cubagem.cubed_weight_kg is None:
        descricao = "Peso e preço confirmados pela agência"
    else:
        descricao = (
            f"Aferido: {payload.length_measured_cm:g}x{payload.width_measured_cm:g}x{payload.height_measured_cm:g} cm, "
            f"peso real {payload.weight_confirmed_kg:g} kg, cúbico {cubagem.cubed_weight_kg:g} kg, "
            f"tarifado {cubagem.billable_weight_kg:g} kg"
        )
    _add_event(db, shipment, "Aferido", descricao, user.username)
    db.commit()
    db.refresh(shipment)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="AFERIR_ENCOMENDA",
        entity=f"shipment:{shipment.id}",
        after={
            "weight_confirmed_kg": float(payload.weight_confirmed_kg),
            "price_confirmed": float(payload.price_confirmed),
            "measured_cm": [payload.length_measured_cm, payload.width_measured_cm, payload.height_measured_cm],
            "cubed_weight_kg": cubagem.cubed_weight_kg,
            "billable_weight_kg": cubagem.billable_weight_kg,
        },
        origin="Agência",
        ip_address=client_ip(request),
    )
    _notify(db, shipment, "shipment.aferido")


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
    shipment.posted_via = "manual"
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


def _registrar_falha(
    db: Session, shipment: Shipment, user: LicenseeUser, request: Request, message: str, action: str
) -> None:
    shipment.auto_post_last_error = message
    _add_event(db, shipment, shipment.status, f"Postagem automática não realizada: {message}", user.username)
    db.commit()
    db.refresh(shipment)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action=action,
        entity=f"shipment:{shipment.id}",
        after={"erro": message, "tentativas": shipment.auto_post_attempts},
        origin="Agência",
        ip_address=client_ip(request),
    )


def _postar_pelo_atende(
    db: Session, shipment: Shipment, cred: correios_atende.AtendeCredencial, user: LicenseeUser, request: Request
) -> None:
    """Manda a encomenda (já Aferida) ao Correios Atende e aplica o
    resultado: Postado, fila de erro do SAC (objeto recusado) ou continua
    Aferido com o motivo registrado (falha de cadastro ou temporária)."""
    shipment.auto_post_attempts = (shipment.auto_post_attempts or 0) + 1
    shipment.auto_post_last_attempt_at = datetime.utcnow()
    try:
        resultado = correios_atende.aferir_e_postar(cred, shipment)
    except AtendeRecusa as exc:
        message = f"Correios Atende recusou a postagem: {exc.message}"
        shipment.auto_post_last_error = message
        marcar_erro(db, shipment, exc.code or "ATENDE_RECUSA", message, user.username)
        log_action(
            db,
            username=user.username,
            role=user.role,
            action="POSTAGEM_AUTOMATICA_RECUSADA",
            entity=f"shipment:{shipment.id}",
            after={"codigo": exc.code, "erro": exc.message, "agencia": cred.agency_name},
            origin="Agência",
            ip_address=client_ip(request),
        )
        return
    except CorreiosAtendeError as exc:
        _registrar_falha(db, shipment, user, request, exc.message, "POSTAGEM_AUTOMATICA_FALHOU")
        return
    except Exception:
        logger.exception("Erro inesperado na postagem automática da encomenda %s", shipment.id)
        _registrar_falha(
            db,
            shipment,
            user,
            request,
            "Erro inesperado ao falar com o Correios Atende. Confira no Correios Atende se o objeto foi "
            "postado antes de tentar de novo.",
            "POSTAGEM_AUTOMATICA_FALHOU",
        )
        return

    shipment.tracking_code = resultado.tracking_code
    shipment.postage_cost = resultado.postage_cost
    shipment.posted_via = "atende"
    shipment.auto_post_last_error = None
    shipment.postado_by = user.id
    shipment.postado_at = datetime.utcnow()
    shipment.status = "Postado"
    _add_event(
        db,
        shipment,
        "Postado",
        f"Postado automaticamente pelo Correios Atende ({cred.agency_name}), rastreio {resultado.tracking_code}",
        user.username,
    )
    db.commit()
    db.refresh(shipment)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="POSTAR_ENCOMENDA_AUTOMATICA",
        entity=f"shipment:{shipment.id}",
        after={
            "tracking_code": resultado.tracking_code,
            "postage_cost": resultado.postage_cost,
            "agencia": cred.agency_name,
        },
        origin="Agência",
        ip_address=client_ip(request),
    )
    _notify(db, shipment, "shipment.postado")


def _credencial_pronta(db: Session, licensee_id: int) -> correios_atende.AtendeCredencial:
    """Confere, antes de mexer na encomenda, se a postagem automática pode
    ser usada agora; se não, devolve 409 com o motivo para o operador."""
    status = _postagem_automatica_status(db, licensee_id)
    if not status.pronta:
        raise HTTPException(status_code=409, detail=status.motivo)
    return correios_atende.credencial_da_loja(db, licensee_id)


@router.post("/{shipment_id}/aferir-e-postar", response_model=ShipmentOut)
def aferir_e_postar_shipment(
    shipment_id: int,
    payload: ShipmentAfericaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("Operador de Caixa")),
):
    """Afere e já posta pelo Correios Atende. A aferição é gravada mesmo se a
    postagem falhar; o resultado vem no status da encomenda (Postado, Erro,
    ou Aferido com `auto_post_last_error`)."""
    cred = _credencial_pronta(db, user.licensee_id)
    shipment = _get_shipment(db, user.licensee_id, shipment_id, lock=True)
    if shipment.status != "Pendente":
        raise HTTPException(status_code=400, detail="Só é possível aferir encomendas com status Pendente")
    _aplicar_afericao(db, shipment, payload, user, request)
    # O commit da aferição solta a trava; trava de novo e confere se ninguém
    # postou esta encomenda nesse meio-tempo (ex.: "postar de novo" em outra aba).
    shipment = _get_shipment(db, user.licensee_id, shipment_id, lock=True)
    if shipment.status == "Aferido":
        _postar_pelo_atende(db, shipment, cred, user, request)
    return shipment


@router.post("/{shipment_id}/postar-automatico", response_model=ShipmentOut)
def postar_automatico_shipment(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: LicenseeUser = Depends(require_licensee_any_role("Expedição", "Operador de Caixa")),
):
    """Nova tentativa de postagem automática para uma encomenda já Aferida
    (ex.: depois de uma falha temporária ou de corrigir a credencial)."""
    cred = _credencial_pronta(db, user.licensee_id)
    shipment = _get_shipment(db, user.licensee_id, shipment_id, lock=True)
    if shipment.status != "Aferido":
        raise HTTPException(status_code=400, detail="Só é possível postar encomendas com status Aferido")
    _postar_pelo_atende(db, shipment, cred, user, request)
    return shipment
