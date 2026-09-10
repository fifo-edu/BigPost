"""fila de erro / SAC (5º portal) + recriação de etiqueta

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10

Novo portal SAC (papel 'SAC' em licensee_users) e o fluxo de fila de erro:
quando a validação do CWS/PPN recusa uma encomenda criada pelo cliente (hoje
um "carimbo" manual no BigPost Agência, futuramente um webhook real — ver
app/api/shipments_sac.py), ela vira status 'Erro' com o motivo registrado. O
cliente é avisado (e-mail automático, se configurado) e pode recriar a
etiqueta com dados corrigidos: a nova encomenda referencia a original via
`replaces_shipment_id`, que permanece intacta como histórico. O SAC imprime
a etiqueta recriada e marca isso em `sac_printed_at/by` antes dela voltar
pra fila de aferição normal do Operador.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("error_code", sa.String(40), nullable=True))
    op.add_column("shipments", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("shipments", sa.Column("error_flagged_at", sa.DateTime(), nullable=True))
    op.add_column("shipments", sa.Column("error_notified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "shipments", sa.Column("replaces_shipment_id", sa.Integer(), sa.ForeignKey("shipments.id"), nullable=True)
    )
    op.add_column("shipments", sa.Column("sac_printed_at", sa.DateTime(), nullable=True))
    op.add_column(
        "shipments", sa.Column("sac_printed_by", sa.Integer(), sa.ForeignKey("licensee_users.id"), nullable=True)
    )

    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status",
        "shipments",
        "status in ('Pendente','Aferido','Postado','Em Trânsito','Entregue','Devolvido','Cancelado','Erro')",
    )

    op.drop_constraint("ck_licensee_users_role", "licensee_users", type_="check")
    op.create_check_constraint(
        "ck_licensee_users_role",
        "licensee_users",
        "role in ('Master','Administrador','Financeiro','Operador de Caixa','Expedição','SAC')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_licensee_users_role", "licensee_users", type_="check")
    op.create_check_constraint(
        "ck_licensee_users_role",
        "licensee_users",
        "role in ('Master','Administrador','Financeiro','Operador de Caixa','Expedição')",
    )

    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status",
        "shipments",
        "status in ('Pendente','Aferido','Postado','Em Trânsito','Entregue','Devolvido','Cancelado')",
    )

    op.drop_column("shipments", "sac_printed_by")
    op.drop_column("shipments", "sac_printed_at")
    op.drop_column("shipments", "replaces_shipment_id")
    op.drop_column("shipments", "error_notified_at")
    op.drop_column("shipments", "error_flagged_at")
    op.drop_column("shipments", "error_message")
    op.drop_column("shipments", "error_code")
