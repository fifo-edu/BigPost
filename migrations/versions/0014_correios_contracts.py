"""contratos dos Correios compartilháveis entre clientes (marketplace)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-28

Antes cada cliente tinha a própria credencial CWS (client_contract_credentials,
uma linha por cliente). Agora o contrato é um cadastro da loja
(correios_contracts) e o cliente aponta para ele (clients.correios_contract_id),
para que vários clientes possam usar o mesmo contrato (marketplace).

Migração dos dados: uma credencial antiga vira um contrato; credenciais de
clientes da mesma loja com o mesmo cartão de postagem viram um contrato só
(vale o cadastro mais recente). O código de acesso é copiado já
criptografado, sem decifrar.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "correios_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
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
        sa.UniqueConstraint("licensee_id", "postal_card", name="uq_correios_contract_postal_card"),
    )
    op.add_column(
        "clients",
        sa.Column("correios_contract_id", sa.Integer(), sa.ForeignKey("correios_contracts.id"), nullable=True),
    )

    # Um contrato por (loja, cartão de postagem), com os dados do cadastro mais recente.
    op.execute(
        """
        insert into correios_contracts (licensee_id, label, correios_username, access_code_encrypted,
            postal_card, contract_number, dr, active, last_validated_at, created_at, updated_at, created_by)
        select distinct on (c.licensee_id, cc.postal_card)
            c.licensee_id, 'Contrato ' || cc.contract_number, cc.correios_username, cc.access_code_encrypted,
            cc.postal_card, cc.contract_number, cc.dr, cc.active, cc.last_validated_at, cc.created_at,
            cc.updated_at, cc.created_by
        from client_contract_credentials cc
        join clients c on c.id = cc.client_id
        order by c.licensee_id, cc.postal_card, cc.updated_at desc, cc.id desc
        """
    )
    op.execute(
        """
        update clients c set correios_contract_id = k.id
        from client_contract_credentials cc, correios_contracts k
        where cc.client_id = c.id and k.licensee_id = c.licensee_id and k.postal_card = cc.postal_card
        """
    )
    op.drop_table("client_contract_credentials")


def downgrade() -> None:
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
    # Volta a ter uma credencial por cliente (copiada do contrato que ele usa).
    # Contrato sem nenhum cliente não tem onde ficar no formato antigo e se perde.
    op.execute(
        """
        insert into client_contract_credentials (client_id, correios_username, access_code_encrypted,
            postal_card, contract_number, dr, active, last_validated_at, created_at, updated_at, created_by)
        select c.id, k.correios_username, k.access_code_encrypted, k.postal_card, k.contract_number, k.dr,
            k.active, k.last_validated_at, k.created_at, k.updated_at, k.created_by
        from clients c join correios_contracts k on k.id = c.correios_contract_id
        """
    )
    op.drop_column("clients", "correios_contract_id")
    op.drop_table("correios_contracts")
