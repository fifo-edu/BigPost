"""agências postadoras (AGF) e vínculo loja -> agência

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-02

A loja licenciada (licensees, vinda do Painel Master) passa a ser separada
da agência postadora (AGF), cadastrada no Admin do BigPost com MCU e login
do Correios Atende. Uma agência atende várias lojas; cada loja posta por uma.
A tabela antiga correios_credentials (credencial por licenciado) fica como
está, sem uso pelas telas, até decidirmos migrar ou descartar os dados dela.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posting_agencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legal_name", sa.String(180), nullable=False),
        sa.Column("trade_name", sa.String(180), nullable=True),
        sa.Column("tax_id", sa.String(20), nullable=False, unique=True),
        sa.Column("zip_code", sa.String(10), nullable=True),
        sa.Column("address_street", sa.String(160), nullable=True),
        sa.Column("address_number", sa.String(20), nullable=True),
        sa.Column("address_complement", sa.String(80), nullable=True),
        sa.Column("address_district", sa.String(80), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("contact_name", sa.String(120), nullable=True),
        sa.Column("contact_email", sa.String(160), nullable=True),
        sa.Column("contact_phone", sa.String(30), nullable=True),
        sa.Column("mcu", sa.String(8), nullable=True),
        sa.Column("correios_username", sa.String(120), nullable=True),
        sa.Column("correios_password_encrypted", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80), nullable=True),
        sa.CheckConstraint("mcu is null or mcu ~ '^[0-9]{8}$'", name="ck_posting_agencies_mcu_format"),
    )
    op.add_column(
        "licensees",
        sa.Column("posting_agency_id", sa.Integer(), sa.ForeignKey("posting_agencies.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("licensees", "posting_agency_id")
    op.drop_table("posting_agencies")
