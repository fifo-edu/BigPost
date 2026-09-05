"""catálogo de produtos licenciáveis

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03

Reintroduz um catálogo de produtos (Agenda, AGF, BigPost, Fluxo Financeiro,
Minha Cidade Aqui + produtos customizados criados avulsos) e amarra cada
licença a um produto — uma agência pode ter várias licenças ativas, uma por
produto contratado. Os 5 produtos fixos abaixo são semeados aqui para que
qualquer licença já existente (se houver) seja migrada para BIGPOST; o
catálogo completo também é semeado de forma idempotente no bootstrap da
aplicação (ver app/services/products.py), então rodar esta migration num
banco vazio ou já semeado tem o mesmo efeito.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CORE_PRODUCTS = [
    {"code": "AGENDA", "name": "Agenda"},
    {"code": "AGF", "name": "AGF"},
    {"code": "BIGPOST", "name": "BigPost"},
    {"code": "FLUXO_FINANCEIRO", "name": "Fluxo Financeiro"},
    {"code": "MINHA_CIDADE_AQUI", "name": "Minha Cidade Aqui"},
]


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    products_table = sa.table(
        "products",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("is_custom", sa.Boolean),
    )
    op.bulk_insert(products_table, [{**p, "is_custom": False} for p in CORE_PRODUCTS])

    op.add_column("licenses", sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True))
    op.create_index("idx_licenses_product", "licenses", ["product_id"])

    # Qualquer licença emitida antes desta migration era, por definição, do
    # BigPost (era o único produto do sistema) — backfill e trava NOT NULL.
    op.execute("UPDATE licenses SET product_id = (SELECT id FROM products WHERE code = 'BIGPOST') WHERE product_id IS NULL")
    op.alter_column("licenses", "product_id", nullable=False)


def downgrade() -> None:
    op.drop_index("idx_licenses_product", table_name="licenses")
    op.drop_column("licenses", "product_id")
    op.drop_table("products")
