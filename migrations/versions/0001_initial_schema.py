"""schema inicial do BigPost

Revision ID: 0001
Revises:
Create Date: 2026-08-31

Espelha exatamente o schema validado manualmente em scripts/schema.sql —
qualquer alteração de modelo deve gerar uma nova revision (nunca editar esta
depois que já tiver rodado em algum ambiente).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("full_name", sa.String(160)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role in ('Master','Supervisor','Operador')", name="ck_users_role"),
    )

    op.create_table(
        "licensees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person_type", sa.String(2), nullable=False, server_default="PJ"),
        sa.Column("legal_name", sa.String(180), nullable=False),
        sa.Column("trade_name", sa.String(180)),
        sa.Column("tax_id", sa.String(20), nullable=False, unique=True),
        sa.Column("state_registration", sa.String(30)),
        sa.Column("zip_code", sa.String(10)),
        sa.Column("address_street", sa.String(160)),
        sa.Column("address_number", sa.String(20)),
        sa.Column("address_complement", sa.String(80)),
        sa.Column("address_district", sa.String(80)),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(2)),
        sa.Column("ibge_city_code", sa.String(10)),
        sa.Column("contact_name", sa.String(120)),
        sa.Column("contact_role", sa.String(80)),
        sa.Column("contact_email", sa.String(160)),
        sa.Column("contact_phone", sa.String(30)),
        sa.Column("billing_email", sa.String(160)),
        sa.Column("billing_phone", sa.String(30)),
        sa.Column("website", sa.String(160)),
        sa.Column("correios_mcu", sa.String(8)),
        sa.Column("contracted_users", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reported_active_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("billing_day", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("status", sa.String(20), nullable=False, server_default="Ativo"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
        sa.CheckConstraint("person_type in ('PJ','PF')", name="ck_licensees_person_type"),
        sa.CheckConstraint(
            "status in ('Ativo','Inadimplente','Bloqueado','Expirado')", name="ck_licensees_status"
        ),
        sa.CheckConstraint(
            "correios_mcu is null or correios_mcu ~ '^[0-9]{8}$'", name="ck_licensees_mcu_format"
        ),
    )
    op.create_index("idx_licensees_status", "licensees", ["status"])

    op.create_table(
        "correios_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False, unique=True),
        sa.Column("mcu", sa.String(8), nullable=False),
        sa.Column("correios_username", sa.String(120), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("token_encrypted", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_validated_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
        sa.CheckConstraint("mcu ~ '^[0-9]{8}$'", name="ck_correios_cred_mcu_format"),
    )

    op.create_table(
        "licensee_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("full_name", sa.String(160)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
        sa.UniqueConstraint("licensee_id", "username", name="uq_licensee_user_username"),
        sa.CheckConstraint(
            "role in ('Master','Administrador','Financeiro','Operador de Caixa','Expedição')",
            name="ck_licensee_users_role",
        ),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("person_type", sa.String(2), nullable=False, server_default="PJ"),
        sa.Column("legal_name", sa.String(180), nullable=False),
        sa.Column("trade_name", sa.String(180)),
        sa.Column("tax_id", sa.String(20), nullable=False),
        sa.Column("zip_code", sa.String(10)),
        sa.Column("address_street", sa.String(160)),
        sa.Column("address_number", sa.String(20)),
        sa.Column("address_complement", sa.String(80)),
        sa.Column("address_district", sa.String(80)),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(2)),
        sa.Column("contact_name", sa.String(120)),
        sa.Column("contact_email", sa.String(160)),
        sa.Column("contact_phone", sa.String(30)),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("api_key_hash", sa.String(255)),
        sa.Column("api_key_prefix", sa.String(12)),
        sa.Column("webhook_url", sa.String(500)),
        sa.Column("webhook_secret", sa.String(120)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
        sa.UniqueConstraint("licensee_id", "username", name="uq_client_username"),
        sa.CheckConstraint("person_type in ('PJ','PF')", name="ck_clients_person_type"),
    )
    op.create_index("idx_clients_licensee", "clients", ["licensee_id"])

    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("external_reference", sa.String(80)),
        sa.Column("recipient_name", sa.String(180), nullable=False),
        sa.Column("recipient_tax_id", sa.String(20)),
        sa.Column("recipient_phone", sa.String(30)),
        sa.Column("recipient_email", sa.String(160)),
        sa.Column("recipient_zip", sa.String(10), nullable=False),
        sa.Column("recipient_street", sa.String(160)),
        sa.Column("recipient_number", sa.String(20)),
        sa.Column("recipient_complement", sa.String(80)),
        sa.Column("recipient_district", sa.String(80)),
        sa.Column("recipient_city", sa.String(100)),
        sa.Column("recipient_state", sa.String(2)),
        sa.Column("service_type", sa.String(30)),
        sa.Column("weight_declared_kg", sa.Numeric(8, 3)),
        sa.Column("length_cm", sa.Numeric(6, 1)),
        sa.Column("width_cm", sa.Numeric(6, 1)),
        sa.Column("height_cm", sa.Numeric(6, 1)),
        sa.Column("declared_value", sa.Numeric(12, 2)),
        sa.Column("contents_description", sa.String(255)),
        sa.Column("weight_confirmed_kg", sa.Numeric(8, 3)),
        sa.Column("price_confirmed", sa.Numeric(12, 2)),
        sa.Column("afericao_by", sa.Integer(), sa.ForeignKey("licensee_users.id")),
        sa.Column("afericao_at", sa.DateTime()),
        sa.Column("tracking_code", sa.String(30)),
        sa.Column("postado_by", sa.Integer(), sa.ForeignKey("licensee_users.id")),
        sa.Column("postado_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False, server_default="Pendente"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status in ('Pendente','Aferido','Postado','Em Trânsito','Entregue','Devolvido','Cancelado')",
            name="ck_shipments_status",
        ),
    )
    op.create_index("idx_shipments_licensee_status", "shipments", ["licensee_id", "status"])
    op.create_index("idx_shipments_client", "shipments", ["client_id"])

    op.create_table(
        "shipment_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
    )
    op.create_index("idx_shipment_events_shipment", "shipment_events", ["shipment_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipments.id")),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.String(255)),
        sa.Column("attempted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_webhook_deliveries_client", "webhook_deliveries", ["client_id"])

    op.create_table(
        "licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("license_code", sa.Text(), nullable=False, unique=True),
        sa.Column("license_uid", sa.String(40), nullable=False, unique=True),
        sa.Column("expires_at", sa.String(20)),
        sa.Column("max_users", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="Ativa"),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("revoked_reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
        sa.CheckConstraint("status in ('Ativa','Revogada','Expirada')", name="ck_licenses_status"),
    )
    op.create_index("idx_licenses_licensee", "licenses", ["licensee_id"])

    op.create_table(
        "activations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("license_id", sa.Integer(), sa.ForeignKey("licenses.id")),
        sa.Column("installation_id", sa.String(80), nullable=False),
        sa.Column("app_name", sa.String(40)),
        sa.Column("app_version", sa.String(40)),
        sa.Column("active_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(20), nullable=False, server_default="Ativa"),
        sa.UniqueConstraint("licensee_id", "installation_id", name="uq_activation_install"),
    )

    op.create_table(
        "system_parameters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(80)),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("username", sa.String(80)),
        sa.Column("role", sa.String(20)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity", sa.String(120)),
        sa.Column("result", sa.String(20), nullable=False, server_default="OK"),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("after", postgresql.JSONB()),
        sa.Column("origin", sa.String(40)),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(45)),
    )
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "charges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("licensee_id", sa.Integer(), sa.ForeignKey("licensees.id"), nullable=False),
        sa.Column("reference_month", sa.String(7), nullable=False),
        sa.Column("due_date", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="Aberta"),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("licensee_id", "reference_month", name="uq_charge_licensee_month"),
        sa.CheckConstraint("status in ('Aberta','Paga','Cancelada')", name="ck_charges_status"),
    )
    op.create_index("idx_charges_licensee", "charges", ["licensee_id"])

    op.create_table(
        "bank_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_name", sa.String(60), nullable=False, server_default="Banco do Brasil"),
        sa.Column("agreement", sa.String(40)),
        sa.Column("wallet", sa.String(10)),
        sa.Column("agency", sa.String(20)),
        sa.Column("account_no", sa.String(20)),
        sa.Column("account_digit", sa.String(4)),
        sa.Column("cnab_layout", sa.String(20), nullable=False, server_default="A DEFINIR"),
        sa.Column("beneficiary_name", sa.String(160)),
        sa.Column("beneficiary_tax_id", sa.String(20)),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_bank_config_singleton"),
    )

    op.create_table(
        "bank_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(160)),
        sa.Column("imported_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("imported_by", sa.String(80)),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_rows", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "bank_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("bank_imports.id")),
        sa.Column("entry_date", sa.String(20)),
        sa.Column("document", sa.String(60)),
        sa.Column("payer", sa.String(160)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("raw_line", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="Pendente"),
        sa.Column("charge_id", sa.Integer(), sa.ForeignKey("charges.id")),
        sa.Column("matched_at", sa.DateTime()),
        sa.Column("matched_by", sa.String(80)),
    )
    op.create_index("idx_bank_entries_status", "bank_entries", ["status"])

    op.create_table(
        "remittances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference_month", sa.String(7)),
        sa.Column("due_date", sa.String(20)),
        sa.Column("layout", sa.String(20)),
        sa.Column("file_name", sa.String(160)),
        sa.Column("total_titles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(60)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(80)),
        sa.Column("content", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("remittances")
    op.drop_table("bank_entries")
    op.drop_table("bank_imports")
    op.drop_table("bank_config")
    op.drop_table("charges")
    op.drop_table("audit_log")
    op.drop_table("system_parameters")
    op.drop_table("activations")
    op.drop_table("licenses")
    op.drop_table("webhook_deliveries")
    op.drop_table("shipment_events")
    op.drop_table("shipments")
    op.drop_table("clients")
    op.drop_table("licensee_users")
    op.drop_table("correios_credentials")
    op.drop_table("licensees")
    op.drop_table("users")
