-- Schema de referência do BigPost (equivalente ao que o Alembic aplica).
-- Útil para revisar o desenho do banco de uma vez só, ou aplicar manualmente
-- com `psql -f scripts/schema.sql bigpost` caso não queira rodar Alembic no
-- primeiro teste. Em produção, prefira sempre as migrations (pasta
-- migrations/), que são a fonte da verdade versionada.

-- Equipe interna do BigPost (administra cadastro/licenciamento das agências).
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    full_name VARCHAR(160),
    role VARCHAR(20) NOT NULL CHECK (role IN ('Master','Supervisor','Operador')),
    password_hash VARCHAR(255) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Catálogo de produtos/sistemas licenciáveis (Agenda, AGF, BigPost, Fluxo
-- Financeiro, Minha Cidade Aqui, ...). Produtos customizados avulsos criados
-- pela tela "Novo produto" ficam com is_custom = TRUE. Semeado no bootstrap
-- da aplicação (app/services/products.py) — não por este schema.sql.
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Agências franqueadas licenciadas a usar o BigPost.
CREATE TABLE licensees (
    id SERIAL PRIMARY KEY,

    person_type VARCHAR(2) NOT NULL DEFAULT 'PJ' CHECK (person_type IN ('PJ','PF')),
    legal_name VARCHAR(180) NOT NULL,
    trade_name VARCHAR(180),
    tax_id VARCHAR(20) NOT NULL UNIQUE,
    state_registration VARCHAR(30),

    zip_code VARCHAR(10),
    address_street VARCHAR(160),
    address_number VARCHAR(20),
    address_complement VARCHAR(80),
    address_district VARCHAR(80),
    city VARCHAR(100),
    state VARCHAR(2),
    ibge_city_code VARCHAR(10),

    contact_name VARCHAR(120),
    contact_role VARCHAR(80),
    contact_email VARCHAR(160),
    contact_phone VARCHAR(30),

    billing_email VARCHAR(160),
    billing_phone VARCHAR(30),
    website VARCHAR(160),

    correios_mcu VARCHAR(8),

    contracted_users INTEGER NOT NULL DEFAULT 1,
    reported_active_users INTEGER NOT NULL DEFAULT 0,
    monthly_fee NUMERIC(12,2) NOT NULL DEFAULT 0,
    billing_day INTEGER NOT NULL DEFAULT 10,
    status VARCHAR(20) NOT NULL DEFAULT 'Ativo'
        CHECK (status IN ('Ativo','Inadimplente','Bloqueado','Expirado')),

    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80),

    CONSTRAINT ck_licensees_mcu_format CHECK (correios_mcu IS NULL OR correios_mcu ~ '^[0-9]{8}$')
);

-- Credenciais do www.correiosatende.correios.com.br por licenciado (MCU +
-- usuário/senha do site). Senha/token ficam criptografados (Fernet, chave em
-- data/credentials.key) — nunca em texto puro.
CREATE TABLE correios_credentials (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL UNIQUE REFERENCES licensees(id),
    mcu VARCHAR(8) NOT NULL CHECK (mcu ~ '^[0-9]{8}$'),
    correios_username VARCHAR(120) NOT NULL,
    password_encrypted TEXT NOT NULL,
    token_encrypted TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_validated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80)
);

-- Credenciais do módulo BigPost Cliente (emissão de etiquetas via contrato),
-- diferente da credencial acima (que é do site Correios Atende, usada pelos
-- módulos BigPost Agência/Operação). Aqui o Correios pede usuário, token de
-- API, cartão de postagem e número do contrato. Token fica criptografado
-- (mesma chave Fernet de correios_credentials) — nunca em texto puro.
CREATE TABLE client_correios_credentials (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL UNIQUE REFERENCES licensees(id),
    correios_username VARCHAR(120) NOT NULL,
    token_encrypted TEXT,
    postal_card VARCHAR(20) NOT NULL,
    contract_number VARCHAR(20) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_validated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80)
);

-- Usuários da agência licenciada (equipe operacional — login no módulo
-- Agência, não no admin interno do BigPost).
CREATE TABLE licensee_users (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL REFERENCES licensees(id),
    username VARCHAR(80) NOT NULL,
    full_name VARCHAR(160),
    role VARCHAR(20) NOT NULL CHECK (role IN ('Master','Administrador','Financeiro','Operador de Caixa','Expedição')),
    password_hash VARCHAR(255) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80),
    UNIQUE (licensee_id, username)
);

-- Clientes de uma agência (quem emite etiqueta com ela — módulo Cliente).
-- Login por usuário/senha (portal) ou api_key (integração programática).
CREATE TABLE clients (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL REFERENCES licensees(id),

    person_type VARCHAR(2) NOT NULL DEFAULT 'PJ' CHECK (person_type IN ('PJ','PF')),
    legal_name VARCHAR(180) NOT NULL,
    trade_name VARCHAR(180),
    tax_id VARCHAR(20) NOT NULL,

    zip_code VARCHAR(10),
    address_street VARCHAR(160),
    address_number VARCHAR(20),
    address_complement VARCHAR(80),
    address_district VARCHAR(80),
    city VARCHAR(100),
    state VARCHAR(2),

    contact_name VARCHAR(120),
    contact_email VARCHAR(160),
    contact_phone VARCHAR(30),

    username VARCHAR(80) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    api_key_hash VARCHAR(255),
    api_key_prefix VARCHAR(12),
    webhook_url VARCHAR(500),
    webhook_secret VARCHAR(120),

    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80),

    UNIQUE (licensee_id, username)
);

-- Encomendas/etiquetas emitidas por um cliente, processadas pela agência.
CREATE TABLE shipments (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL REFERENCES licensees(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),

    external_reference VARCHAR(80),

    recipient_name VARCHAR(180) NOT NULL,
    recipient_tax_id VARCHAR(20),
    recipient_phone VARCHAR(30),
    recipient_email VARCHAR(160),
    recipient_zip VARCHAR(10) NOT NULL,
    recipient_street VARCHAR(160),
    recipient_number VARCHAR(20),
    recipient_complement VARCHAR(80),
    recipient_district VARCHAR(80),
    recipient_city VARCHAR(100),
    recipient_state VARCHAR(2),

    service_type VARCHAR(30),
    weight_declared_kg NUMERIC(8,3),
    length_cm NUMERIC(6,1),
    width_cm NUMERIC(6,1),
    height_cm NUMERIC(6,1),
    declared_value NUMERIC(12,2),
    contents_description VARCHAR(255),

    weight_confirmed_kg NUMERIC(8,3),
    price_confirmed NUMERIC(12,2),
    afericao_by INTEGER REFERENCES licensee_users(id),
    afericao_at TIMESTAMP,

    tracking_code VARCHAR(30),
    postado_by INTEGER REFERENCES licensee_users(id),
    postado_at TIMESTAMP,

    status VARCHAR(20) NOT NULL DEFAULT 'Pendente'
        CHECK (status IN ('Pendente','Aferido','Postado','Em Trânsito','Entregue','Devolvido','Cancelado')),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Histórico/rastreio de uma encomenda — cada linha aqui também vira uma
-- notificação de webhook pro cliente.
CREATE TABLE shipment_events (
    id SERIAL PRIMARY KEY,
    shipment_id INTEGER NOT NULL REFERENCES shipments(id),
    status VARCHAR(20) NOT NULL,
    description VARCHAR(255),
    occurred_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80)
);

-- Log de tentativas de entrega de webhook pro cliente — auditoria e
-- retry/debug quando o endpoint do cliente estiver fora do ar.
CREATE TABLE webhook_deliveries (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    shipment_id INTEGER REFERENCES shipments(id),
    event_type VARCHAR(40) NOT NULL,
    url VARCHAR(500) NOT NULL,
    payload JSONB NOT NULL,
    response_status INTEGER,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    error_message VARCHAR(255),
    attempted_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE licenses (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL REFERENCES licensees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    license_code TEXT NOT NULL UNIQUE,
    license_uid VARCHAR(40) NOT NULL UNIQUE,
    expires_at VARCHAR(20),
    max_users INTEGER NOT NULL DEFAULT 1,
    features JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'Ativa' CHECK (status IN ('Ativa','Revogada','Expirada')),
    revoked_at TIMESTAMP,
    revoked_reason VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80)
);

CREATE TABLE activations (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL REFERENCES licensees(id),
    license_id INTEGER REFERENCES licenses(id),
    installation_id VARCHAR(80) NOT NULL,
    app_name VARCHAR(40),
    app_version VARCHAR(40),
    active_users INTEGER NOT NULL DEFAULT 0,
    last_seen TIMESTAMP NOT NULL DEFAULT now(),
    status VARCHAR(20) NOT NULL DEFAULT 'Ativa',
    UNIQUE (licensee_id, installation_id)
);

CREATE TABLE system_parameters (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) NOT NULL UNIQUE,
    value JSONB NOT NULL,
    description VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_by VARCHAR(80)
);

CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    username VARCHAR(80),
    role VARCHAR(20),
    action VARCHAR(80) NOT NULL,
    entity VARCHAR(120),
    result VARCHAR(20) NOT NULL DEFAULT 'OK',
    before JSONB,
    after JSONB,
    origin VARCHAR(40),
    details JSONB,
    ip_address VARCHAR(45)
);

CREATE TABLE charges (
    id SERIAL PRIMARY KEY,
    licensee_id INTEGER NOT NULL REFERENCES licensees(id),
    reference_month VARCHAR(7) NOT NULL,
    due_date VARCHAR(20) NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Aberta' CHECK (status IN ('Aberta','Paga','Cancelada')),
    paid_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (licensee_id, reference_month)
);

CREATE TABLE bank_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bank_name VARCHAR(60) NOT NULL DEFAULT 'Banco do Brasil',
    agreement VARCHAR(40),
    wallet VARCHAR(10),
    agency VARCHAR(20),
    account_no VARCHAR(20),
    account_digit VARCHAR(4),
    cnab_layout VARCHAR(20) NOT NULL DEFAULT 'A DEFINIR',
    beneficiary_name VARCHAR(160),
    beneficiary_tax_id VARCHAR(20),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE bank_imports (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(160),
    imported_at TIMESTAMP NOT NULL DEFAULT now(),
    imported_by VARCHAR(80),
    total_rows INTEGER NOT NULL DEFAULT 0,
    matched_rows INTEGER NOT NULL DEFAULT 0,
    pending_rows INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE bank_entries (
    id SERIAL PRIMARY KEY,
    import_id INTEGER REFERENCES bank_imports(id),
    entry_date VARCHAR(20),
    document VARCHAR(60),
    payer VARCHAR(160),
    amount NUMERIC(12,2) NOT NULL,
    raw_line TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'Pendente',
    charge_id INTEGER REFERENCES charges(id),
    matched_at TIMESTAMP,
    matched_by VARCHAR(80)
);

CREATE TABLE remittances (
    id SERIAL PRIMARY KEY,
    reference_month VARCHAR(7),
    due_date VARCHAR(20),
    layout VARCHAR(20),
    file_name VARCHAR(160),
    total_titles INTEGER NOT NULL DEFAULT 0,
    total_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    status VARCHAR(60),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(80),
    content TEXT
);

CREATE INDEX idx_licensees_status ON licensees(status);
CREATE INDEX idx_licenses_licensee ON licenses(licensee_id);
CREATE INDEX idx_licenses_product ON licenses(product_id);
CREATE INDEX idx_charges_licensee ON charges(licensee_id);
CREATE INDEX idx_bank_entries_status ON bank_entries(status);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);

CREATE INDEX idx_clients_licensee ON clients(licensee_id);
CREATE INDEX idx_shipments_licensee_status ON shipments(licensee_id, status);
CREATE INDEX idx_shipments_client ON shipments(client_id);
CREATE INDEX idx_shipment_events_shipment ON shipment_events(shipment_id);
CREATE INDEX idx_webhook_deliveries_client ON webhook_deliveries(client_id);
