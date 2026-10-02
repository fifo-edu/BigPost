"""credenciais de contrato dos Correios por cliente

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02

Cada cliente final pode usar seu próprio usuário CWS, cartão de postagem e
contrato. As credenciais existentes por licenciado são mantidas para
compatibilidade com a configuração anterior.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_contract_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False, unique=True),
        sa.Column("correios_username", sa.String(120), nullable=False),
        sa.Column("access_code_encrypted", sa.Text(), nullable=False),
        sa.Column("postal_card", sa.String(20), nullable=False),
        sa.Column("contract_number", sa.String(20), nullable=False),
        sa.Column("dr", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("client_contract_credentials")