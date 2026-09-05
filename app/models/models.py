"""Modelos SQLAlchemy do BigPost.

BigPost é um sistema único e integrado (não mais dividido num "Painel
Master" genérico separado): cadastro e licenciamento dos licenciados (AGF —
agências franqueadas dos Correios), cadastro dos clientes de cada AGF,
emissão de etiquetas/encomendas pelos clientes, e o fluxo de aferição/
postagem pela equipe da agência. Ver app/core/security.py para as duas
hierarquias de usuário (equipe interna do BigPost vs. equipe de cada
agência) e app/services/webhooks.py para a notificação dos clientes.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Usuários internos do BigPost (equipe que administra cadastro/licenciamento
# das agências — não os usuários finais das agências/clientes licenciados)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # Master | Supervisor | Operador
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (
        CheckConstraint("role in ('Master','Supervisor','Operador')", name="ck_users_role"),
    )


# ---------------------------------------------------------------------------
# Licenciados (empresas/agências cadastradas). Cadastro detalhado conforme
# solicitado: endereço completo separado por campo + contato.
# ---------------------------------------------------------------------------
class Product(Base):
    """Um sistema licenciável do catálogo (Agenda, AGF, BigPost, Fluxo
    Financeiro, Minha Cidade Aqui, ...). Uma agência licenciada pode ter
    várias licenças ativas, uma por produto contratado. `is_custom=True`
    marca produtos criados avulsos pelo admin (agrupados sob "Customizados"
    na tela) em vez dos produtos fixos do catálogo padrão."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Licensee(Base):
    __tablename__ = "licensees"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Identificação
    person_type: Mapped[str] = mapped_column(String(2), default="PJ", nullable=False)  # PJ | PF
    legal_name: Mapped[str] = mapped_column(String(180), nullable=False)  # Razão social / nome completo (PF)
    trade_name: Mapped[str | None] = mapped_column(String(180))  # Nome fantasia
    tax_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # CNPJ ou CPF
    state_registration: Mapped[str | None] = mapped_column(String(30))  # Inscrição estadual (opcional)

    # Endereço
    zip_code: Mapped[str | None] = mapped_column(String(10))  # CEP
    address_street: Mapped[str | None] = mapped_column(String(160))  # Logradouro
    address_number: Mapped[str | None] = mapped_column(String(20))  # Número
    address_complement: Mapped[str | None] = mapped_column(String(80))  # Complemento (não obrigatório)
    address_district: Mapped[str | None] = mapped_column(String(80))  # Bairro
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))  # UF
    ibge_city_code: Mapped[str | None] = mapped_column(String(10))  # útil p/ integrações Correios

    # Contato (pessoa responsável)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_role: Mapped[str | None] = mapped_column(String(80))  # cargo
    contact_email: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(30))

    # Contato financeiro/cobrança (pode ser diferente do contato geral)
    billing_email: Mapped[str | None] = mapped_column(String(160))
    billing_phone: Mapped[str | None] = mapped_column(String(30))

    website: Mapped[str | None] = mapped_column(String(160))

    # Dado específico de Correios: uma agência franqueada (AGF) é identificada
    # só pelo MCU (código de 8 dígitos) — o resto da identificação dela já é
    # CNPJ/endereço, campos acima. Credenciais de acesso ao Correios Atende
    # (usuário/senha do site, por MCU) ficam em CorreiosCredential, separado
    # e criptografado — não misturar com o cadastro cadastral.
    correios_mcu: Mapped[str | None] = mapped_column(String(8))  # código MCU (8 dígitos)

    # Comercial
    contracted_users: Mapped[int] = mapped_column(Integer, default=1)
    reported_active_users: Mapped[int] = mapped_column(Integer, default=0)
    monthly_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    billing_day: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(20), default="Ativo", nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    created_by: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        CheckConstraint("person_type in ('PJ','PF')", name="ck_licensees_person_type"),
        CheckConstraint(
            "status in ('Ativo','Inadimplente','Bloqueado','Expirado')", name="ck_licensees_status"
        ),
        CheckConstraint(
            "correios_mcu is null or correios_mcu ~ '^[0-9]{8}$'", name="ck_licensees_mcu_format"
        ),
    )


class CorreiosCredential(Base):
    """Credenciais de acesso ao www.correiosatende.correios.com.br para um
    licenciado: o site pede o MCU (8 dígitos) e, na tela seguinte, usuário e
    senha. Guardado separado do cadastro do licenciado e com a senha (e o
    token, se houver) criptografados em repouso — nunca em texto puro e nunca
    devolvidos em texto puro pela API (só usados internamente quando o
    backend precisar autenticar contra o Correios). Ver app/services/crypto.py.
    """

    __tablename__ = "correios_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False, unique=True)
    mcu: Mapped[str] = mapped_column(String(8), nullable=False)
    correios_username: Mapped[str] = mapped_column(String(120), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_encrypted: Mapped[str | None] = mapped_column(Text)  # token de API, se/quando o Correios fornecer
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    created_by: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (CheckConstraint("mcu ~ '^[0-9]{8}$'", name="ck_correios_cred_mcu_format"),)


class ClientCorreiosCredential(Base):
    """Credenciais dos Correios para o módulo BigPost Cliente (emissão de
    etiquetas/postagem via contrato) — diferente da credencial de
    CorreiosCredential (que é do site Correios Atende/CA, usada pelo MCU nos
    módulos BigPost Agência/Operação). Aqui o Correios pede usuário, token de
    API, número do cartão de postagem e número do contrato. Implantado pelo
    Painel Master junto com a licença BigPost. Token fica criptografado em
    repouso (app/services/crypto.py) e nunca é devolvido em texto puro."""

    __tablename__ = "client_correios_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False, unique=True)
    correios_username: Mapped[str] = mapped_column(String(120), nullable=False)
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    postal_card: Mapped[str] = mapped_column(String(20), nullable=False)  # Cartão de postagem
    contract_number: Mapped[str] = mapped_column(String(20), nullable=False)  # Número do contrato
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    created_by: Mapped[str | None] = mapped_column(String(80))


# ---------------------------------------------------------------------------
# Usuários da AGÊNCIA licenciada (equipe que opera o dia a dia no módulo
# Agência — login próprio, cookie session_agencia). Propositalmente uma
# tabela separada de `users` (equipe interna do BigPost que administra
# cadastro e licenciamento das agências). Papéis: Master, Administrador,
# Financeiro, Operador de Caixa, Expedição — ver LICENSEE_ROLE_RANK em
# app/core/security.py para a hierarquia (Master > Administrador > Financeiro
# > Caixa/Expedição, esses dois últimos em pé de igualdade).
# ---------------------------------------------------------------------------
class LicenseeUser(Base):
    __tablename__ = "licensee_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_by: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("licensee_id", "username", name="uq_licensee_user_username"),
        CheckConstraint(
            "role in ('Master','Administrador','Financeiro','Operador de Caixa','Expedição')",
            name="ck_licensee_users_role",
        ),
    )


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    license_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # token assinado (Ed25519)
    license_uid: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(20))  # ISO date ou "PERPETUA"
    max_users: Mapped[int] = mapped_column(Integer, default=1)
    features: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="Ativa", nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_by: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        CheckConstraint("status in ('Ativa','Revogada','Expirada')", name="ck_licenses_status"),
    )


class Activation(Base):
    """Instalações/ativações reportadas pelos apps clientes (Cliente/Agência)
    que consomem uma licença emitida pelo Master. Preenchida via
    POST /api/v1/licenses/heartbeat."""

    __tablename__ = "activations"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False)
    license_id: Mapped[int | None] = mapped_column(ForeignKey("licenses.id"))
    installation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    app_name: Mapped[str | None] = mapped_column(String(40))  # cliente | agencia
    app_version: Mapped[str | None] = mapped_column(String(40))
    active_users: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    status: Mapped[str] = mapped_column(String(20), default="Ativa", nullable=False)

    __table_args__ = (UniqueConstraint("licensee_id", "installation_id", name="uq_activation_install"),)


# ---------------------------------------------------------------------------
# Clientes de cada agência licenciada (módulo CLIENTE). Não confundir com
# `Licensee` (a AGF que licencia o BigPost) nem com `LicenseeUser` (a equipe
# da AGF) — um Client é o cliente FINAL da agência: quem manda encomendas.
# Login de duas formas: usuário/senha (portal manual) ou api_key (integração
# programática) — "emite as etiquetas por integrações ou manuais".
# ---------------------------------------------------------------------------
class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False)

    person_type: Mapped[str] = mapped_column(String(2), default="PJ", nullable=False)  # PJ | PF
    legal_name: Mapped[str] = mapped_column(String(180), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(180))
    tax_id: Mapped[str] = mapped_column(String(20), nullable=False)  # CNPJ ou CPF

    zip_code: Mapped[str | None] = mapped_column(String(10))
    address_street: Mapped[str | None] = mapped_column(String(160))
    address_number: Mapped[str | None] = mapped_column(String(20))
    address_complement: Mapped[str | None] = mapped_column(String(80))
    address_district: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))

    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_email: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(30))

    username: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Chave de API pra integração (emissão de etiqueta automatizada). Só o
    # hash fica guardado — o valor em texto puro só existe no momento em que
    # é gerado (ver /api/v1/cliente/api-key/rotate) e não pode ser recuperado
    # depois, só regerado.
    api_key_hash: Mapped[str | None] = mapped_column(String(255))
    api_key_prefix: Mapped[str | None] = mapped_column(String(12))  # só pra exibir "bp_live_ab12..." na UI

    webhook_url: Mapped[str | None] = mapped_column(String(500))
    webhook_secret: Mapped[str | None] = mapped_column(String(120))

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    created_by: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("licensee_id", "username", name="uq_client_username"),
        CheckConstraint("person_type in ('PJ','PF')", name="ck_clients_person_type"),
    )


# ---------------------------------------------------------------------------
# Encomendas/etiquetas emitidas pelos clientes e processadas pela agência.
# Fluxo: Cliente cria (Pendente) -> Agência afere peso/valor (Aferido) ->
# Agência posta e informa o código de rastreio (Postado) -> eventos de
# rastreio subsequentes (Em Trânsito/Entregue/Devolvido) via ShipmentEvent.
# Cada mudança de status relevante dispara um webhook pro cliente.
# ---------------------------------------------------------------------------
class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)

    external_reference: Mapped[str | None] = mapped_column(String(80))  # id da encomenda no sistema do cliente

    # Destinatário
    recipient_name: Mapped[str] = mapped_column(String(180), nullable=False)
    recipient_tax_id: Mapped[str | None] = mapped_column(String(20))
    recipient_phone: Mapped[str | None] = mapped_column(String(30))
    recipient_email: Mapped[str | None] = mapped_column(String(160))
    recipient_zip: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient_street: Mapped[str | None] = mapped_column(String(160))
    recipient_number: Mapped[str | None] = mapped_column(String(20))
    recipient_complement: Mapped[str | None] = mapped_column(String(80))
    recipient_district: Mapped[str | None] = mapped_column(String(80))
    recipient_city: Mapped[str | None] = mapped_column(String(100))
    recipient_state: Mapped[str | None] = mapped_column(String(2))

    # Pacote (declarado pelo cliente na emissão)
    service_type: Mapped[str | None] = mapped_column(String(30))  # PAC | SEDEX | ... (texto livre por ora)
    weight_declared_kg: Mapped[float | None] = mapped_column(Numeric(8, 3))
    length_cm: Mapped[float | None] = mapped_column(Numeric(6, 1))
    width_cm: Mapped[float | None] = mapped_column(Numeric(6, 1))
    height_cm: Mapped[float | None] = mapped_column(Numeric(6, 1))
    declared_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    contents_description: Mapped[str | None] = mapped_column(String(255))

    # Aferição (preenchido pela agência)
    weight_confirmed_kg: Mapped[float | None] = mapped_column(Numeric(8, 3))
    price_confirmed: Mapped[float | None] = mapped_column(Numeric(12, 2))
    afericao_by: Mapped[int | None] = mapped_column(ForeignKey("licensee_users.id"))
    afericao_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Postagem (preenchido pela agência — integração real com Correios é um
    # próximo passo; por ora o código de rastreio é registrado manualmente
    # ou por outro processo que chame este mesmo endpoint)
    tracking_code: Mapped[str | None] = mapped_column(String(30))
    postado_by: Mapped[int | None] = mapped_column(ForeignKey("licensee_users.id"))
    postado_at: Mapped[datetime | None] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(20), default="Pendente", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    __table_args__ = (
        CheckConstraint(
            "status in ('Pendente','Aferido','Postado','Em Trânsito','Entregue','Devolvido','Cancelado')",
            name="ck_shipments_status",
        ),
    )


class ShipmentEvent(Base):
    """Histórico/rastreio de uma encomenda — cada linha aqui é um evento que
    também vira uma notificação de webhook pro cliente."""

    __tablename__ = "shipment_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_by: Mapped[str | None] = mapped_column(String(80))  # username do licensee_user, ou 'sistema'


class WebhookDelivery(Base):
    """Log de tentativas de entrega de webhook pro cliente — pra auditoria e
    retry/debug quando o endpoint do cliente estiver fora do ar."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(255))
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ---------------------------------------------------------------------------
# Parametrizações rápidas: qualquer parâmetro de negócio que o Master precise
# ajustar em runtime, sem deploy, fica aqui como chave/valor (JSON).
# Ex.: {"key": "license.grace_period_days", "value": 7}
# ---------------------------------------------------------------------------
class SystemParameter(Base):
    __tablename__ = "system_parameters"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    updated_by: Mapped[str | None] = mapped_column(String(80))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    username: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(120))
    result: Mapped[str] = mapped_column(String(20), default="OK")
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    origin: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))


# ---------------------------------------------------------------------------
# Cobrança / conciliação bancária (portado do protótipo)
# ---------------------------------------------------------------------------
class Charge(Base):
    __tablename__ = "charges"

    id: Mapped[int] = mapped_column(primary_key=True)
    licensee_id: Mapped[int] = mapped_column(ForeignKey("licensees.id"), nullable=False)
    reference_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    due_date: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Aberta", nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (
        UniqueConstraint("licensee_id", "reference_month", name="uq_charge_licensee_month"),
        CheckConstraint("status in ('Aberta','Paga','Cancelada')", name="ck_charges_status"),
    )


class BankConfig(Base):
    __tablename__ = "bank_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    bank_name: Mapped[str] = mapped_column(String(60), default="Banco do Brasil")
    agreement: Mapped[str | None] = mapped_column(String(40))  # Convênio
    wallet: Mapped[str | None] = mapped_column(String(10))  # Carteira
    agency: Mapped[str | None] = mapped_column(String(20))
    account_no: Mapped[str | None] = mapped_column(String(20))
    account_digit: Mapped[str | None] = mapped_column(String(4))
    cnab_layout: Mapped[str] = mapped_column(String(20), default="A DEFINIR")
    beneficiary_name: Mapped[str | None] = mapped_column(String(160))
    beneficiary_tax_id: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    __table_args__ = (CheckConstraint("id = 1", name="ck_bank_config_singleton"),)


class BankImport(Base):
    __tablename__ = "bank_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(160))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    imported_by: Mapped[str | None] = mapped_column(String(80))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    matched_rows: Mapped[int] = mapped_column(Integer, default=0)
    pending_rows: Mapped[int] = mapped_column(Integer, default=0)


class BankEntry(Base):
    __tablename__ = "bank_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("bank_imports.id"))
    entry_date: Mapped[str | None] = mapped_column(String(20))
    document: Mapped[str | None] = mapped_column(String(60))
    payer: Mapped[str | None] = mapped_column(String(160))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    raw_line: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="Pendente")
    charge_id: Mapped[int | None] = mapped_column(ForeignKey("charges.id"))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime)
    matched_by: Mapped[str | None] = mapped_column(String(80))


class Remittance(Base):
    __tablename__ = "remittances"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_month: Mapped[str | None] = mapped_column(String(7))
    due_date: Mapped[str | None] = mapped_column(String(20))
    layout: Mapped[str | None] = mapped_column(String(20))
    file_name: Mapped[str | None] = mapped_column(String(160))
    total_titles: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_by: Mapped[str | None] = mapped_column(String(80))
    content: Mapped[str | None] = mapped_column(Text)
