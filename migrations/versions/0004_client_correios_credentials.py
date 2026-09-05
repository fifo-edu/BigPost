"""credenciais Correios do módulo BigPost Cliente

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03

BigPost tem três módulos separados: BigPost Agência (dados cadastrais +
credencial Correios Atende por MCU — já coberto por correios_credentials,
usado também por BigPost Operação: Aferição/Painel/Expedição), e BigPost
Cliente, que usa um conjunto de credenciais Correios diferente (contrato):
usuário, token de API, cartão de postagem e número do contrato. Esta
migration cria a tabela separada para essas credenciais, implantadas pelo
Painel Master junto com a licença BigPost.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_correios_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False, unique=True),
        sa.Column("correios_username", sa.String(120), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("postal_card", sa.String(20), nullable=False),
        sa.Column("contract_number", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("client_correios_credentials")
