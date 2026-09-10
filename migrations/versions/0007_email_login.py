"""cadastro/login por e-mail (convite + esqueci minha senha) para os 3 tipos de conta

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10

A partir de agora o cadastro de usuário (equipe interna, equipe da agência,
clientes) é sempre feito por e-mail: quem cadastra informa só o e-mail (e
nome/perfil), o sistema manda um link de convite pra pessoa definir a
própria senha (política: 6 a 15 caracteres, com maiúscula, minúscula e
número — ver app/services/password_policy.py). O mesmo mecanismo de token
(nova tabela `password_set_tokens`) atende também o "Esqueci minha senha"
de verdade (antes só um texto de instrução, sem enviar nada).

O login continua aceitando o `username` antigo OU o e-mail novo — nenhuma
conta existente para de funcionar. `email`/`contact_email` ficam nullable
(contas antigas não têm) e sem NOT NULL — só únicos.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(160), nullable=True))
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.add_column("licensee_users", sa.Column("email", sa.String(160), nullable=True))
    op.create_unique_constraint("uq_licensee_user_email", "licensee_users", ["licensee_id", "email"])

    # contact_email já existia (nullable) — só falta a unicidade por
    # licenciado, já que agora também serve de login.
    op.create_unique_constraint("uq_client_contact_email", "clients", ["licensee_id", "contact_email"])

    op.create_table(
        "password_set_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("actor_type in ('user','licensee_user','client')", name="ck_password_token_actor_type"),
        sa.CheckConstraint("purpose in ('invite','reset')", name="ck_password_token_purpose"),
    )


def downgrade() -> None:
    op.drop_table("password_set_tokens")
    op.drop_constraint("uq_client_contact_email", "clients", type_="unique")
    op.drop_constraint("uq_licensee_user_email", "licensee_users", type_="unique")
    op.drop_column("licensee_users", "email")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "email")
