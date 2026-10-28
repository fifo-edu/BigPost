from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import UNUSABLE_PASSWORD_HASH, require_role
from app.api.correios_contracts import contratos_da_loja, contrato_da_loja_ou_400, criar_contrato
from app.models.models import Client, Licensee, User
from app.schemas.schemas import ClientAdminCreate, ClientAdminOut, ClientCreateOut, ClientOut, CorreiosContractOut
from app.services.audit import log_action
from app.services.password_tokens import issue_and_notify
from app.services.support_access import SUPPORT_USERNAME

router = APIRouter(prefix="/api/v1/clients", tags=["clients-admin"])


@router.get("", response_model=list[ClientAdminOut])
def list_clients_admin(
    licensee_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    """Consulta somente leitura, cross-licenciado, dos clientes cadastrados —
    usada pela aba Cliente > Relatórios do Admin (ver static/index.html,
    botão 'Cliente' no menu). O cadastro em si continua sendo feito no
    portal da Agência (POST /api/v1/agencia/clients); esta rota é só para
    consulta/conferência pela equipe BigPost, por isso exige Supervisor+
    (mesmo critério de visibilidade usado no menu do Admin)."""
    query = (
        db.query(Client, Licensee)
        .join(Licensee, Licensee.id == Client.licensee_id)
        .filter(Client.username != SUPPORT_USERNAME)
    )
    if licensee_id:
        query = query.filter(Client.licensee_id == licensee_id)
    rows = query.order_by(Client.legal_name).all()

    out = []
    for client, licensee in rows:
        data = ClientAdminOut.model_validate(client).model_dump()
        data["licensee_name"] = licensee.trade_name or licensee.legal_name
        out.append(data)
    return out


@router.get("/correios-contracts", response_model=list[CorreiosContractOut])
def list_contracts_admin(
    licensee_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    """Contratos dos Correios de uma loja, para escolher no cadastro de
    cliente pelo Admin (ex.: cliente novo de um marketplace já cadastrado)."""
    return contratos_da_loja(db, licensee_id)


@router.post("", response_model=ClientCreateOut)
def create_client_admin(
    payload: ClientAdminCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    """Cadastro de cliente pelo Admin, cross-licenciado — aba Cliente >
    Cadastrar Cliente (ver static/index.html). Pedido do usuário: mesmo que o
    cadastro normal já seja feito pelo portal da Agência, a equipe BigPost
    também precisa conseguir cadastrar direto por aqui, escolhendo a qual
    licenciado o cliente pertence (`licensee_id` no corpo), além da credencial
    CWS própria do cliente, que não faz parte do cadastro feito pela Agência.

    Mesma regra de sempre-por-e-mail: quem cadastra não define senha, o
    cliente recebe um convite pra definir a própria (ver
    app/services/password_tokens.py) — igual ao POST /api/v1/agencia/clients."""
    licensee = db.get(Licensee, payload.licensee_id)
    if not licensee:
        raise HTTPException(status_code=404, detail="Licenciado não encontrado")

    email = payload.contact_email.strip().lower()
    client = Client(
        **payload.model_dump(exclude={"contact_email", "licensee_id", "correios_credential", "correios_contract_id"}),
        licensee_id=payload.licensee_id,
        contact_email=email,
        username=email,
        password_hash=UNUSABLE_PASSWORD_HASH,
        created_by=user.username,
    )
    if payload.correios_contract_id is not None:
        contrato = contrato_da_loja_ou_400(db, licensee.id, payload.correios_contract_id)
    else:
        contrato = criar_contrato(db, licensee.id, payload.correios_credential, user.username)
    client.correios_contract_id = contrato.id
    db.add(client)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um cliente com esse e-mail nesta agência")
    db.refresh(client)

    link, emailed = issue_and_notify(db, "client", client.id, "invite", email, client.legal_name)

    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_CLIENTE",
        entity=f"client:{client.id}",
        after={
            "legal_name": client.legal_name,
            "tax_id": client.tax_id,
            "licensee_id": licensee.id,
            "correios_contract_id": contrato.id,
            "contrato_novo": payload.correios_credential is not None,
            "convite_emailed": emailed,
        },
        origin="Admin",
        ip_address=client_ip(request),
    )
    return ClientCreateOut(**ClientOut.model_validate(client).model_dump(), invite_emailed=emailed, invite_link=None if emailed else link)
