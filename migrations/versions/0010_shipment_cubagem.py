"""medidas conferidas e peso cúbico na aferição

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02

A aferição passa a guardar as medidas lidas no cubômetro (C x L x A), o peso
cúbico calculado e o peso tarifado (maior entre real e cúbico, conforme a
regra em app/services/cubagem.py). Tudo opcional — aferições antigas e
aferições só com balança continuam válidas.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

COLUMNS = [
    ("length_measured_cm", sa.Numeric(6, 1)),
    ("width_measured_cm", sa.Numeric(6, 1)),
    ("height_measured_cm", sa.Numeric(6, 1)),
    ("cubed_weight_kg", sa.Numeric(8, 3)),
    ("billable_weight_kg", sa.Numeric(8, 3)),
]


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("shipments", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("shipments", name)
