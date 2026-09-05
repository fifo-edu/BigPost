"""bloqueio de conta por tentativas de login

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03

Adiciona contagem de tentativas de login falhas (failed_attempts) e a flag
de bloqueio (locked) tanto para usuários internos (users) quanto para
usuários de agência (licensee_users). O limite de tentativas é lido do
parâmetro já existente security.login_max_attempts (app/services/params.py);
o bloqueio é liberado pelas ações Zerar Senha / Desbloquear na tela de
Parâmetros (Master para users, Supervisor+ para licensee_users).
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("licensee_users", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("licensee_users", sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("licensee_users", "locked")
    op.drop_column("licensee_users", "failed_attempts")
    op.drop_column("users", "locked")
    op.drop_column("users", "failed_attempts")
