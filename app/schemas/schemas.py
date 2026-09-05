from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --------------------------- Auth ---------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str | None = None
    role: str
    active: bool
    locked: bool = False


class UserCreate(BaseModel):
    username: str
    full_name: str | None = None
    password: str = Field(min_length=6)
    role: str = "Operador"


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=6)


# --------------------------- Licensees (cadastro detalhado) ---------------------------
class LicenseeCreate(BaseModel):
    person_type: str = "PJ"  # PJ | PF
    legal_name: str
    trade_name: str | None = None
    tax_id: str
    state_registration: str | None = None

    zip_code: str | None = None
    address_street: str | None = None
    address_number: str | None = None
    address_complement: str | None = None
    address_district: str | None = None
    city: str | None = None
    state: str | None = None
    ibge_city_code: str | None = None

    contact_name: str | None = None
    contact_role: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None

    billing_email: EmailStr | None = None
    billing_phone: str | None = None
    website: str | None = None

    correios_mcu: str | None = Field(default=None, pattern=r"^[0-9]{8}$")

    contracted_users: int = 1
    monthly_fee: float = 0
    billing_day: int = 10
    notes: str | None = None


class LicenseeStatusUpdate(BaseModel):
    status: str


class LicenseeOut(LicenseeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    reported_active_users: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


# --------------------------- Licenses ---------------------------
class LicenseGenerateRequest(BaseModel):
    licensee_id: int
    product_id: int
    expires_at: str | None = None  # YYYY-MM-DD ou vazio = PERPETUA
    max_users: int | None = None
    features: dict | None = None


class LicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    licensee_id: int
    product_id: int
    license_uid: str
    expires_at: str | None
    max_users: int
    status: str
    created_at: datetime
    created_by: str | None


# --------------------------- Integração Painel Master ---------------------------
# O Painel Master (sistema externo de gestão financeira/licenciamento — NÃO faz
# parte deste projeto) chama a API abaixo quando cadastra um licenciado ou
# emite uma licença por lá, para replicar aqui o necessário à operação
# (usuários da agência, credenciais Correios, cobranças). Ver
# app/api/integrations_painel_master.py.
class PainelMasterLicenseeUpsert(LicenseeCreate):
    """Mesmos campos de LicenseeCreate. O identificador usado para decidir
    entre criar e atualizar é `tax_id` (CNPJ/CPF) — não um ID interno do
    BigPost, que o Painel Master não tem como conhecer de antemão."""

    pass


class PainelMasterLicenseRequest(BaseModel):
    tax_id: str
    product_code: str
    expires_at: str | None = None  # YYYY-MM-DD ou vazio = PERPETUA
    max_users: int | None = None
    features: dict | None = None


class PainelMasterLicenseOut(LicenseOut):
    """Igual a LicenseOut, mas também inclui o token assinado (license_code):
    o Painel Master precisa desse código para repassar ao licenciado ativar
    o app — o endpoint interno de listagem não devolve isso hoje."""

    license_code: str


# --------------------------- Produtos / catálogo de licenças ---------------------------
class ProductCreate(BaseModel):
    code: str
    name: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    is_custom: bool
    active: bool


class LicenseValidateRequest(BaseModel):
    license_code: str


class LicenseHeartbeatRequest(BaseModel):
    license_code: str
    installation_id: str
    app_name: str | None = None
    app_version: str | None = None
    active_users: int = 0


# --------------------------- Charges / Billing ---------------------------
class ChargeCreate(BaseModel):
    licensee_id: int
    reference_month: str
    due_date: str
    amount: float


class MassChargeRequest(BaseModel):
    reference_month: str
    due_date: str
    licensee_ids: list[int] | None = None


class ChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    licensee_id: int
    reference_month: str
    due_date: str
    amount: float
    status: str
    paid_at: datetime | None


# --------------------------- Bank / BB ---------------------------
class BankConfigUpdate(BaseModel):
    agreement: str | None = None
    wallet: str | None = None
    agency: str | None = None
    account_no: str | None = None
    account_digit: str | None = None
    cnab_layout: str | None = None
    beneficiary_name: str | None = None
    beneficiary_tax_id: str | None = None


class BankImportRequest(BaseModel):
    file_name: str
    content: str


class BankReconcileRequest(BaseModel):
    entry_id: int
    charge_id: int


class RemittanceRequest(BaseModel):
    reference_month: str


# --------------------------- System parameters ---------------------------
class ParamUpdate(BaseModel):
    value: object
    description: str | None = None


# --------------------------- Correios Atende (credenciais por MCU) ---------------------------
class CorreiosCredentialUpsert(BaseModel):
    mcu: str = Field(pattern=r"^[0-9]{8}$")
    correios_username: str
    password: str
    token: str | None = None


class CorreiosCredentialOut(BaseModel):
    """Nunca inclui a senha/token em texto puro — só o necessário pra
    confirmar que está cadastrado e qual MCU/usuário está associado."""

    licensee_id: int
    mcu: str
    correios_username: str
    has_password: bool
    active: bool
    last_validated_at: datetime | None
    updated_at: datetime


# --------------------------- BigPost Cliente: credenciais Correios (contrato) ---------------------------
class ClientCorreiosCredentialUpsert(BaseModel):
    correios_username: str
    token: str | None = None
    postal_card: str
    contract_number: str


class ClientCorreiosCredentialOut(BaseModel):
    """Nunca inclui o token em texto puro."""

    licensee_id: int
    correios_username: str
    postal_card: str
    contract_number: str
    has_token: bool
    active: bool
    last_validated_at: datetime | None
    updated_at: datetime


# --------------------------- Usuários da agência licenciada ---------------------------
LICENSEE_ROLES = ("Master", "Administrador", "Financeiro", "Operador de Caixa", "Expedição")


class LicenseeUserCreate(BaseModel):
    username: str
    full_name: str | None = None
    password: str = Field(min_length=6)
    role: str = "Operador de Caixa"


class LicenseeUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    licensee_id: int
    username: str
    full_name: str | None
    role: str
    active: bool
    locked: bool = False


# --------------------------- Auth: Agência (LicenseeUser) e Cliente (Client) ---------------------------
class LicenseeUserLoginRequest(BaseModel):
    licensee_id: int
    username: str
    password: str
    # Qual dos 2 portais fez a chamada — "agencia" (Master/Administrador/
    # Financeiro) ou "operador" (Operador de Caixa/Expedição). Cada frontend
    # estático manda seu próprio valor fixo; usado só para impedir login
    # "no portal errado" (ver app/api/auth_agencia.py). Default "agencia"
    # por compatibilidade com chamadas antigas.
    portal: str = "agencia"


class ClientLoginRequest(BaseModel):
    licensee_id: int
    username: str
    password: str


# --------------------------- Auth: "modo suporte" (Master interno entra em qualquer licenciado) ---------------------------
class SupportLoginRequest(BaseModel):
    username: str
    password: str


class SupportLicenseeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    legal_name: str
    trade_name: str | None = None
    tax_id: str
    city: str | None = None
    state: str | None = None
    status: str


class SupportEnterRequest(BaseModel):
    # "agencia" | "operador" | "cliente" — qual portal fez a chamada (cada
    # frontend estático manda o seu próprio valor fixo).
    portal: str


# --------------------------- Clientes de cada agência ---------------------------
class ClientCreate(BaseModel):
    person_type: str = "PJ"
    legal_name: str
    trade_name: str | None = None
    tax_id: str

    zip_code: str | None = None
    address_street: str | None = None
    address_number: str | None = None
    address_complement: str | None = None
    address_district: str | None = None
    city: str | None = None
    state: str | None = None

    contact_name: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None

    username: str
    password: str = Field(min_length=6)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    licensee_id: int
    person_type: str
    legal_name: str
    trade_name: str | None
    tax_id: str
    zip_code: str | None
    address_street: str | None
    address_number: str | None
    address_complement: str | None
    address_district: str | None
    city: str | None
    state: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    username: str
    api_key_prefix: str | None
    webhook_url: str | None
    active: bool
    created_at: datetime


class ClientApiKeyOut(BaseModel):
    api_key: str  # texto puro — só aparece nesta resposta, uma vez
    api_key_prefix: str


class ClientWebhookConfig(BaseModel):
    webhook_url: str | None = None
    webhook_secret: str | None = None  # se omitido, o backend gera um novo


class ClientWebhookOut(BaseModel):
    webhook_url: str | None
    webhook_secret: str | None


# --------------------------- Encomendas / Etiquetas (módulo Cliente) ---------------------------
class ShipmentCreate(BaseModel):
    external_reference: str | None = None

    recipient_name: str
    recipient_tax_id: str | None = None
    recipient_phone: str | None = None
    recipient_email: EmailStr | None = None
    recipient_zip: str
    recipient_street: str | None = None
    recipient_number: str | None = None
    recipient_complement: str | None = None
    recipient_district: str | None = None
    recipient_city: str | None = None
    recipient_state: str | None = None

    service_type: str | None = None
    weight_declared_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    declared_value: float | None = None
    contents_description: str | None = None


class ShipmentBulkCreate(BaseModel):
    shipments: list[ShipmentCreate]


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    licensee_id: int
    client_id: int
    external_reference: str | None
    recipient_name: str
    recipient_zip: str
    recipient_city: str | None
    recipient_state: str | None
    service_type: str | None
    weight_declared_kg: float | None
    declared_value: float | None
    weight_confirmed_kg: float | None
    price_confirmed: float | None
    tracking_code: str | None
    status: str
    created_at: datetime
    updated_at: datetime


# --------------------------- Encomendas (módulo Agência) ---------------------------
class ShipmentAfericaoRequest(BaseModel):
    weight_confirmed_kg: float
    price_confirmed: float


class ShipmentPostagemRequest(BaseModel):
    tracking_code: str


class ShipmentEventCreate(BaseModel):
    status: str
    description: str | None = None


class ShipmentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shipment_id: int
    status: str
    description: str | None
    occurred_at: datetime
    created_by: str | None
