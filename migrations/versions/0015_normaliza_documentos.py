"""normaliza CNPJ/CPF já gravados (sem máscara, maiúsculas)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-28

Os cadastros passam a gravar CNPJ/CPF só com os caracteres que importam
(app/core/br.py — o CNPJ alfanumérico mantém as letras, em maiúsculas). O
Painel Master acha a loja pelo CNPJ: um CNPJ antigo gravado com máscara não
seria encontrado e a sincronização criaria uma loja duplicada. Por isso os
documentos já gravados são normalizados aqui. Uma loja só é alterada se
nenhuma outra já tiver o mesmo documento normalizado (aí fica como está,
para não travar o deploy por causa de uma duplicata antiga).

Sem downgrade de dados: a máscara antiga não tem como ser reconstituída e
não faz falta.
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

NORM = "upper(regexp_replace({col}, '[^0-9A-Za-z]', '', 'g'))"


def upgrade() -> None:
    op.execute(
        f"""
        update licensees l set tax_id = n.norm
        from (select id, {NORM.format(col='tax_id')} as norm from licensees) n
        where l.id = n.id and l.tax_id <> n.norm
          and not exists (select 1 from licensees x where x.tax_id = n.norm)
        """
    )
    for table, col in (("clients", "tax_id"), ("posting_agencies", "tax_id"), ("shipments", "recipient_tax_id")):
        op.execute(f"update {table} set {col} = {NORM.format(col=col)} where {col} is not null and {col} <> {NORM.format(col=col)}")


def downgrade() -> None:
    pass
