"""remove o controle da postagem automática pelo Correios Atende

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04

O fluxo confirmado é outro: o BigPost Cliente gera a pré-postagem pela API
oficial dos Correios, a AGF afere e posta no balcão (Correios Atende) e o
BigPost busca o resultado depois. As colunas de tentativas de postagem
automática e o parâmetro postagem.atende_automatica deixam de existir;
posted_via e postage_cost continuam (servem ao fluxo novo).
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("auto_post_last_error", "auto_post_last_attempt_at", "auto_post_attempts"):
        op.drop_column("shipments", col)
    op.execute("delete from system_parameters where key = 'postagem.atende_automatica'")


def downgrade() -> None:
    op.add_column("shipments", sa.Column("auto_post_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("shipments", sa.Column("auto_post_last_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("shipments", sa.Column("auto_post_last_error", sa.Text(), nullable=True))
