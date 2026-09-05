"""API de integração para o Painel Master.

O Painel Master é um sistema EXTERNO (já existente, fora deste projeto —
www.painel.fluxoempresa.com.br) que cadastra licenciados e emite/cobra as
licenças. O cadastro de licenciados ("Cadastrar Licenciado") e a emissão de
licença ("Licenças") não existem mais no admin deste BigPost porque esse
trabalho é feito por lá.

Para que este BigPost fique sabendo de um licenciado novo (ou de uma licença
nova) sem precisar de tela própria para isso, o Painel Master CHAMA estes
dois endpoints sempre que cadastra ou licencia uma agência:

    POST /api/v1/integrations/painel-master/licensees   (cria ou atualiza o
        cadastro operacional do licenciado aqui, casando por `tax_id`)
    POST /api/v1/integrations/painel-master/licenses    (gera e assina uma
        licença para um licenciado + produto já existentes)

Autenticação: segredo compartilhado por cabeçalho `X-API-Key` — o Painel
Master não é um usuário `User` interno, então não usa login/cookie de sessão
normal. Ver app/api/deps.py::require_painel_master_key e a variável de
ambiente PAINEL_MASTER_API_KEY (vazia = integração desligada, todo endpoint
aqui responde 401).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_painel_master_key
from app.core.db import get_db
from app.models.models import Licensee, Product
from app.schemas.schemas import (
    LicenseeOut,
    PainelMasterLicenseeUpsert,
    PainelMasterLicenseOut,
    PainelMasterLicenseRequest,
)
from app.services.audit import log_action
from app.services.licensing import build_license

router = APIRouter(
    prefix="/api/v1/integrations/painel-master",
    tags=["integracao-painel-master"],
    dependencies=[Depends(require_painel_master_key)],
)


@router.post("/licensees", response_model=LicenseeOut)
def upsert_licensee(
    payload: PainelMasterLicenseeUpsert,
    request: Request,
    db: Session = Depends(get_db),
):
    """Cria o licenciado se `tax_id` ainda não existir aqui, ou atualiza o
    cadastro existente. Idempotente — seguro chamar de novo com os mesmos
    dados (ex.: reenvio automático após falha de rede no Painel Master)."""
    if payload.person_type not in ("PJ", "PF"):
        raise HTTPException(status_code=400, detail="Tipo de pessoa inválido")

    licensee = db.query(Licensee).filter(Licensee.tax_id == payload.tax_id).first()
    before = None
    if licensee:
        action = "ATUALIZAR_LICENCIADO"
        before = {"legal_name": licensee.legal_name, "status": licensee.status}
        for field, value in payload.model_dump().items():
            setattr(licensee, field, value)
        licensee.updated_at = datetime.utcnow()
    else:
        action = "CADASTRAR_LICENCIADO"
        licensee = Licensee(**payload.model_dump(), created_by="painel-master")
        db.add(licensee)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="CNPJ/CPF já cadastrado em outro licenciado")
    db.refresh(licensee)

    log_action(
        db,
        username="painel-master",
        role="Integração",
        action=action,
        entity=licensee.legal_name,
        before=before,
        after={"id": licensee.id, "tax_id": licensee.tax_id},
        origin="Painel Master",
        ip_address=client_ip(request),
    )
    return licensee


@router.post("/licenses", response_model=PainelMasterLicenseOut)
def issue_license(
    payload: PainelMasterLicenseRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Gera e assina uma licença BigPost para um licenciado (por `tax_id`) e
    um produto do catálogo (por `product_code`, ex.: 'BIGPOST', 'AGF'). O
    licenciado precisa já existir aqui — chame /licensees antes, se ainda não
    tiver sido enviado."""
    licensee = db.query(Licensee).filter(Licensee.tax_id == payload.tax_id).first()
    if not licensee:
        raise HTTPException(
            status_code=404,
            detail="Licenciado não encontrado neste BigPost (cadastre via /licensees antes)",
        )

    product = db.query(Product).filter(Product.code == payload.product_code).first()
    if not product or not product.active:
        raise HTTPException(status_code=404, detail="Produto não encontrado ou inativo")

    license_row, token_payload = build_license(
        db,
        licensee=licensee,
        product=product,
        expires_at=payload.expires_at,
        max_users=payload.max_users,
        features=payload.features,
        created_by="painel-master",
    )

    log_action(
        db,
        username="painel-master",
        role="Integração",
        action="GERAR_LICENCA",
        entity=f"licensee:{licensee.id}",
        after=token_payload,
        origin="Painel Master",
        ip_address=client_ip(request),
    )
    return license_row
