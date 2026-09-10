from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_role
from app.models.models import Client, Licensee, User
from app.schemas.schemas import ClientAdminOut
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
