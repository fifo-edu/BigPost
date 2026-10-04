"""controle da postagem automática pelo Correios Atende

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04

Guarda como a encomenda foi postada (manual ou pelo Correios Atende), o
custo cobrado pelos Correios quando a integração informar, e as tentativas
de postagem automática que falharam (para reenviar e para o operador ver o
motivo). Ver app/services/correios_atende.py.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("posted_via", sa.String(10), nullable=True))
    op.add_column("shipments", sa.Column("postage_cost", sa.Numeric(12, 2), nullable=True))
    op.add_column("shipments", sa.Column("auto_post_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("shipments", sa.Column("auto_post_last_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("shipments", sa.Column("auto_post_last_error", sa.Text(), nullable=True))
    # Encomendas já postadas antes desta versão foram todas pelo botão Postar.
    op.execute("update shipments set posted_via = 'manual' where tracking_code is not null")


def downgrade() -> None:
    for col in ("auto_post_last_error", "auto_post_last_attempt_at", "auto_post_attempts", "postage_cost", "posted_via"):
        op.drop_column("shipments", col)
