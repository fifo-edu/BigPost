"""telefone celular separado do telefone fixo, no cadastro de Cliente

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-12

Pedido do usuário: no cadastro de Cliente (tela Cliente > Cadastrar Cliente
do Admin, e futuramente também na Agência), fixo e celular devem ser dois
campos separados, nenhum dos dois obrigatório — não dá pra usar um único
campo "detecta pelo tamanho" (10 x 11 dígitos) como fizemos em CPF/CNPJ,
porque aqui a pessoa pode querer informar os dois ao mesmo tempo.

`contact_phone` (já existia, nullable) passa a significar especificamente
telefone fixo — não foi renomeada no banco pra não quebrar nada que já
aponta pra ela, só a UI passou a rotular como "Telefone Fixo". Nova coluna
`contact_phone_mobile` guarda o celular, também nullable (opcional)."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("contact_phone_mobile", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "contact_phone_mobile")
