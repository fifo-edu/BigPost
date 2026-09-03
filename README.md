# BigPost

ERP de criação, emissão e gerenciamento de postagens via Correios, para agências franqueadas (AGF). Sistema único e integrado — não depende de nenhum serviço externo de licenciamento — com três frentes:

- **Administração interna** (equipe do BigPost): cadastro e licenciamento das agências, cobrança, parametrização.
- **Módulo Agência**: a equipe da agência franqueada processa as encomendas que os clientes emitem — aferição (peso/preço) e postagem (código de rastreio).
- **Módulo Cliente**: os clientes de uma agência emitem etiquetas (manual pelo portal, ou por integração via API key) e acompanham o envio até a entrega, com notificação por webhook a cada mudança de status.

## Stack

FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL. Sem dependências externas de autenticação/criptografia além do pacote `cryptography` — hash de senha (PBKDF2), sessão (JWT HS256 caseiro) e assinatura de licença (Ed25519) são implementados só com biblioteca padrão do Python, então não há `passlib`/`pyjwt` para instalar.

## Modelo de dados — visão geral

- `users` — equipe interna do BigPost (papéis: Master, Supervisor, Operador).
- `licensees` — agências franqueadas licenciadas. Cadastro detalhado (endereço completo, pessoa de contato, dados de cobrança) + **MCU** (código de 8 dígitos que identifica a franqueada nos Correios — o resto já é dado de CNPJ/endereço).
- `correios_credentials` — usuário/senha (e token) do site **www.correiosatende.correios.com.br**, por agência, **criptografados em repouso** (Fernet) — nunca devolvidos em texto puro pela API.
- `licensee_users` — equipe operacional de uma agência (módulo Agência). Hierarquia de 5 papéis: **Master > Administrador > Financeiro > {Operador de Caixa, Expedição}** (esses dois últimos em pé de igualdade — um não manda no outro). Login próprio, cookie `session_agencia`.
- `clients` — clientes de uma agência (módulo Cliente): quem emite etiqueta com ela. Cadastro detalhado (endereço, contato) + login próprio (usuário/senha, cookie `session_cliente`) + **API key** (`bp_live_...`) para integração programática.
- `shipments` — encomendas/etiquetas: dados do destinatário e do pacote (declarados pelo cliente na emissão), depois peso/preço confirmados e código de rastreio (preenchidos pela agência). Status: `Pendente → Aferido → Postado → Em Trânsito → Entregue` (ou `Devolvido`/`Cancelado`).
- `shipment_events` — histórico/rastreio de cada encomenda.
- `webhook_deliveries` — log de entrega de webhook ao cliente (auditoria/retry).
- `licenses` / `activations` — licenciamento de cada agência (assinatura Ed25519, offline-verificável).
- `system_parameters` — parametrizações de negócio ajustáveis em runtime, sem deploy.
- `charges`, `bank_config`, `bank_imports`, `bank_entries`, `remittances` — cobrança e conciliação bancária (Banco do Brasil) das agências licenciadas.
- `audit_log` — auditoria de ações nos três módulos.

**Fluxo de uma encomenda**: o cliente emite a etiqueta (`POST /api/v1/cliente/shipments`, manual ou via API key) → status `Pendente` → a agência afere peso/preço (`POST /api/v1/agencia/shipments/{id}/aferir`, papel Operador de Caixa+) → status `Aferido` → a agência posta e registra o código de rastreio (`POST /api/v1/agencia/shipments/{id}/postar`, papel Expedição+) → status `Postado` → eventos adicionais (`Em Trânsito`, `Entregue`, ...) são lançados manualmente por ora (`POST /api/v1/agencia/shipments/{id}/eventos`) até que uma integração de rastreio automático dos Correios seja plugada aqui. Cada mudança de status dispara um webhook assinado (HMAC-SHA256, header `X-BigPost-Signature`) para a URL cadastrada pelo cliente.

## Três autenticações, três portais

| Ator | Cookie / header | Papéis | Portal |
|---|---|---|---|
| `User` (equipe BigPost) | `session` | Master, Supervisor, Operador | `/` |
| `LicenseeUser` (equipe da agência) | `session_agencia` | Master, Administrador, Financeiro, Operador de Caixa, Expedição | `/agencia/` |
| `Client` (cliente da agência) | `session_cliente` ou `Authorization: Bearer <api_key>` | — | `/cliente/` |

Os três portais são páginas HTML/JS estáticas, sem build step, servidas pela própria API.

## Dependências e o que foi validado nesta sessão

Este ambiente de build não tinha acesso à internet para instalar pacotes (PyPI/apt bloqueados), então **não foi possível subir o servidor FastAPI de ponta a ponta aqui**. O que foi validado diretamente:

- Todo o código Python passa em `python3 -m py_compile` (sem erro de sintaxe) — modelos, schemas, routers, serviços e a migration Alembic.
- O JavaScript dos três portais (`static/index.html`, `static/agencia/index.html`, `static/cliente/index.html`) passa em `node --check`.
- O schema SQL (`scripts/schema.sql`, espelhado na migration `0001`, 17 tabelas) foi aplicado num Postgres 16 real e testado de ponta a ponta com dados: cadastro de agência (com MCU), usuários de agência nos 5 papéis, cliente com webhook configurado, emissão de encomenda, aferição, postagem, evento manual, log de entrega de webhook — `UNIQUE`, `CHECK` (formato do MCU, status da encomenda, papéis) e chaves estrangeiras testados, inclusive rejeição de status inválido.
- A assinatura/verificação de licença Ed25519 (`app/services/licensing.py`) foi testada de ponta a ponta (gerar, verificar, detectar adulteração) — só depende de `cryptography`, que estava disponível.
- O hash de senha PBKDF2, a criação/verificação de token de sessão (JWT HS256 caseiro, com o campo `typ` isolando os 3 tipos de ator) e a geração/verificação de API key (`app/core/security.py`) foram testados isoladamente.
- A assinatura HMAC de webhook (`app/services/webhooks.py`) foi testada isoladamente (determinística, 64 hex chars).
- O script de migração do protótipo antigo (`scripts/migrate_from_sqlite.py`) foi atualizado (removida a dependência do antigo cadastro de "produtos") e revalidado: gera SQL a partir de um SQLite de teste e aplica sem erro num Postgres limpo.

O que **não pôde ser testado aqui** por falta de rede: subir o `uvicorn` de verdade e bater nos endpoints HTTP, rodar `alembic upgrade head` (a ferramenta em si), e testar os três portais num navegador de verdade. A migration foi escrita para espelhar exatamente o `schema.sql` já validado, mas faça o smoke test abaixo na sua máquina antes de considerar isso produção.

## Como rodar

### Opção A — Docker (mais simples)

```bash
docker compose up --build
```

Sobe Postgres + API. Acesse http://localhost:8000 (admin), http://localhost:8000/agencia/ e http://localhost:8000/cliente/. Usuário Master inicial: `Fifo` / senha definida em `BOOTSTRAP_MASTER_PASSWORD` no `docker-compose.yml` (troque antes de expor publicamente).

### Opção B — Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edite .env: DATABASE_URL, JWT_SECRET, BOOTSTRAP_MASTER_PASSWORD
# se for testar em http:// (sem HTTPS), defina também COOKIE_SECURE=false

createdb bigpost   # ou: psql -c "CREATE DATABASE bigpost;"
alembic upgrade head

uvicorn app.main:app --reload
```

Depois de subir, pelo portal admin (`/`) cadastre a primeira agência (com MCU, se já for franqueada) e gere a licença; pela tela "Agência: Usuários & Correios" cadastre o primeiro usuário `Master` da agência (que já pode logar em `/agencia/` e cadastrar clientes e demais usuários da equipe) e, se aplicável, as credenciais do Correios Atende.

### Migrando os dados do protótipo antigo ("Gestão Financeira Master")

```bash
python3 scripts/migrate_from_sqlite.py /caminho/para/master.db > migration_data.sql
psql "$DATABASE_URL" -f migration_data.sql
```

Depois, copie `data/license_private.pem` e `data/license_public.pem` do protótipo antigo para o `DATA_DIR` do sistema novo (mesma chave = licenças antigas continuam válidas, inclusive o prefixo de token legado `FAGF1`). Complete endereço/contato/MCU dos licenciados migrados pela tela "Licenciados" — esses campos não existiam no protótipo antigo. Cadastre também os usuários da agência e clientes — são conceitos novos, não existiam no protótipo.

## Estrutura

```
app/
  core/       # config, banco, segurança (hash de senha, JWT, API key, RBAC dos 3 atores)
  models/     # SQLAlchemy (schema)
  schemas/    # Pydantic (validação de entrada/saída da API)
  api/        # routers FastAPI — internos (auth, licensees, ...), agência (auth_agencia,
              # clients, shipments_agencia) e cliente (auth_cliente, shipments_cliente)
  services/   # licenciamento (Ed25519), parametrizações, auditoria, webhooks
migrations/   # Alembic
scripts/      # schema.sql (referência) e migração do SQLite antigo
static/       # 3 portais HTML/JS puro, sem build step
  index.html      # admin interno
  agencia/        # módulo Agência
  cliente/        # módulo Cliente
```

## Próximos passos sugeridos

1. Rodar o smoke test completo numa máquina com internet (Docker é o caminho mais rápido) e testar os três portais num navegador de verdade.
2. Trocar `JWT_SECRET` e a senha do usuário Master antes de qualquer uso real.
3. Colocar atrás de HTTPS antes de aceitar tráfego de fora da rede local (`COOKIE_SECURE=true`).
4. Integração real com os Correios: hoje o código de rastreio é lançado manualmente pela agência (`POST /api/v1/agencia/shipments/{id}/postar`) — o próximo passo natural é automatizar isso (geração de etiqueta e postagem via API dos Correios, usando as credenciais do Correios Atende já cadastradas) e plugar rastreio automático (que hoje é lançado manualmente via `POST /api/v1/agencia/shipments/{id}/eventos`).
5. Entrega de webhook hoje é síncrona/best-effort (uma tentativa, sem retry automático) — evoluir para uma fila com retry usando o log em `webhook_deliveries`.
