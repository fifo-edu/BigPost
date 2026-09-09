"""adiciona dr (Diretoria Regional) às credenciais Correios do BigPost Cliente

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-09

A autenticação da API do CWS (Correios Web Services) — usada pela
Pré-Postagem do módulo BigPost Cliente — exige o código da Diretoria
Regional (DR) junto do número do cartão de postagem/contrato (endpoints
POST /v1/autentica/cartaopostagem e /v1/autentica/contrato). Esse dado não
existia no cadastro de credenciais do BigPost Cliente — esta migration
adiciona a coluna. Nullable porque credenciais já cadastradas antes desta
mudança ainda não têm o valor; precisa ser preenchido antes de a
autenticação no CWS funcionar (ver app/services/correios_cws.py).
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_correios_credentials", sa.Column("dr", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("client_correios_credentials", "dr")
