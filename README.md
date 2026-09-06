# BigPost

ERP de criação, emissão e gerenciamento de postagens via Correios, para agências franqueadas (AGF). O cadastro/licenciamento de agências é feito num sistema externo (Painel Master — ver seção própria abaixo); este projeto cobre a operação de quem já está licenciado, com quatro frentes:

- **Administração interna** (equipe do BigPost): usuários da agência, credenciais Correios, cobrança, parametrização.
- **Módulo Agência** (papéis Master, Administrador, Financeiro): gestão da agência — cadastro de clientes, relação com os módulos Cliente e Operador.
- **Módulo Operador** (papéis Operador de Caixa, Expedição): fila de trabalho da equipe operacional — aferição (peso/preço) e postagem (código de rastreio) das encomendas.
- **Módulo Cliente**: os clientes de uma agência emitem etiquetas (manual pelo portal, ou por integração via API key) e acompanham o envio até a entrega, com notificação por webhook a cada mudança de status.

## Stack

FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL. Sem dependências externas de autenticação/criptografia além do pacote `cryptography` — hash de senha (PBKDF2), sessão (JWT HS256 caseiro) e assinatura de licença (Ed25519) são implementados só com biblioteca padrão do Python, então não há `passlib`/`pyjwt` para instalar.

## Modelo de dados — visão geral

- `users` — equipe interna do BigPost (papéis: Master, Supervisor, Operador).
- `licensees` — agências franqueadas licenciadas. Cadastro detalhado (endereço completo, pessoa de contato, dados de cobrança) + **MCU** (código de 8 dígitos que identifica a franqueada nos Correios — o resto já é dado de CNPJ/endereço).
- `correios_credentials` — usuário/senha (e token) do site **www.correiosatende.correios.com.br**, por agência, **criptografados em repouso** (Fernet) — nunca devolvidos em texto puro pela API.
- `licensee_users` — equipe de uma agência, compartilhada pelos portais Agência e Operador. Hierarquia de 5 papéis: **Master > Administrador > Financeiro > {Operador de Caixa, Expedição}** (esses dois últimos em pé de igualdade — um não manda no outro); os 3 primeiros usam o portal Agência, os 2 últimos o portal Operador. Login próprio, cookie `session_agencia`.
- `clients` — clientes de uma agência (módulo Cliente): quem emite etiqueta com ela. Cadastro detalhado (endereço, contato) + login próprio (usuário/senha, cookie `session_cliente`) + **API key** (`bp_live_...`) para integração programática.
- `shipments` — encomendas/etiquetas: dados do destinatário e do pacote (declarados pelo cliente na emissão), depois peso/preço confirmados e código de rastreio (preenchidos pela agência). Status: `Pendente → Aferido → Postado → Em Trânsito → Entregue` (ou `Devolvido`/`Cancelado`).
- `shipment_events` — histórico/rastreio de cada encomenda.
- `webhook_deliveries` — log de entrega de webhook ao cliente (auditoria/retry).
- `licenses` / `activations` — licenciamento de cada agência (assinatura Ed25519, offline-verificável).
- `system_parameters` — parametrizações de negócio ajustáveis em runtime, sem deploy.
- `charges`, `bank_config`, `bank_imports`, `bank_entries`, `remittances` — cobrança e conciliação bancária (Banco do Brasil) das agências licenciadas.
- `audit_log` — auditoria de ações nos três módulos.

**Fluxo de uma encomenda**: o cliente emite a etiqueta (`POST /api/v1/cliente/shipments`, manual ou via API key) → status `Pendente` → a equipe operacional (portal Operador) afere peso/preço (`POST /api/v1/agencia/shipments/{id}/aferir`, papel Operador de Caixa+) → status `Aferido` → posta e registra o código de rastreio (`POST /api/v1/agencia/shipments/{id}/postar`, papel Expedição+) → status `Postado` → eventos adicionais (`Em Trânsito`, `Entregue`, ...) são lançados manualmente por ora (`POST /api/v1/agencia/shipments/{id}/eventos`) até que uma integração de rastreio automático dos Correios seja plugada aqui. Cada mudança de status dispara um webhook assinado (HMAC-SHA256, header `X-BigPost-Signature`) para a URL cadastrada pelo cliente. Os endpoints continuam sob `/api/v1/agencia/...` (nome histórico) mesmo sendo chamados pelo portal Operador agora — só o frontend que os chama mudou.

## Integração com o Painel Master (sistema externo)

O **Painel Master** (`www.painel.fluxoempresa.com.br`, "Gestão Financeira Master") é um sistema **externo, já existente, que não faz parte deste projeto**. É lá que um licenciado é cadastrado e uma licença é emitida/cobrada — por isso o admin deste BigPost **não tem** telas de "Cadastrar Licenciado" nem "Licenças" (isso continua exclusivo do Painel Master). O que o BigPost tem é uma **edição local** dos dados do licenciado (endereço, contato, faturamento, observações — botão "Editar dados" na tela Licenciados, só pro Master), igual ao "Dados da Empresa" do Financeiro AGF: o cadastro inicial vem de lá, mas o dia a dia (agência mudou de endereço, trocou o contato) é ajustado direto aqui, sem precisar passar pelo Painel Master. Uma sincronização futura do Painel Master ainda sobrescreve tudo que ele manda (é um upsert completo por `tax_id`), então essa edição local vale até a próxima sincronização de lá — e por isso o `CNPJ/CPF` não é editável nessa tela (é a chave que o Painel Master usa pra reconhecer o licenciado).

Para o BigPost ficar sabendo de um licenciado novo (ou de uma licença nova) cadastrado no Painel Master, é o **Painel Master quem chama a API deste BigPost** — dois endpoints, autenticados por segredo compartilhado (não é login de usuário):

| Endpoint | Quando chamar | Efeito |
|---|---|---|
| `POST /api/v1/integrations/painel-master/licensees` | Ao cadastrar ou editar um licenciado no Painel Master | Cria o licenciado aqui se `tax_id` (CNPJ/CPF) ainda não existir, ou atualiza o cadastro existente (idempotente — pode reenviar) |
| `POST /api/v1/integrations/painel-master/licenses` | Ao emitir/renovar uma licença no Painel Master | Gera e assina (Ed25519) uma licença para o licenciado (por `tax_id`) + produto (por `product_code`, ex. `BIGPOST`, `AGF`) já cadastrado |

**Autenticação**: cabeçalho `X-API-Key: <segredo>` em toda chamada. Configure o mesmo valor aleatório (ex. `openssl rand -hex 32`) na variável `PAINEL_MASTER_API_KEY` do `.env` deste BigPost **e** no Painel Master. Enquanto `PAINEL_MASTER_API_KEY` estiver vazio no `.env`, os dois endpoints respondem sempre `401` (integração desligada).

**Exemplo — cadastrar/atualizar um licenciado:**
```bash
curl -X POST https://SEU-BIGPOST/api/v1/integrations/painel-master/licensees \
  -H "X-API-Key: SEGREDO_COMPARTILHADO" \
  -H "Content-Type: application/json" \
  -d '{
    "person_type": "PJ",
    "legal_name": "Agência Exemplo LTDA",
    "trade_name": "AGF Exemplo",
    "tax_id": "12345678000199",
    "zip_code": "01310100",
    "address_street": "Av. Paulista",
    "address_number": "1000",
    "address_complement": "",
    "address_district": "Bela Vista",
    "city": "São Paulo",
    "state": "SP",
    "contact_name": "Fulano de Tal",
    "contact_email": "fulano@exemplo.com.br",
    "billing_email": "financeiro@exemplo.com.br",
    "correios_mcu": "12345678",
    "contracted_users": 3,
    "monthly_fee": 199.90,
    "billing_day": 10
  }'
```
Resposta: o licenciado (com `id` interno do BigPost), formato igual ao de `GET /api/v1/licensees/{id}`. **Envie sempre o objeto completo** — é um "replace", igual à tela de edição do admin: campos omitidos são gravados como vazio quando o licenciado já existe.

**Exemplo — emitir uma licença:**
```bash
curl -X POST https://SEU-BIGPOST/api/v1/integrations/painel-master/licenses \
  -H "X-API-Key: SEGREDO_COMPARTILHADO" \
  -H "Content-Type: application/json" \
  -d '{
    "tax_id": "12345678000199",
    "product_code": "BIGPOST",
    "expires_at": "2027-12-31",
    "max_users": 5
  }'
```
Resposta (`PainelMasterLicenseOut`): inclui `license_code` — o token assinado (formato `PM1.<payload>.<assinatura>`) que o Painel Master deve repassar ao licenciado para ativar o app. `expires_at` vazio/omitido = licença perpétua. O licenciado precisa já existir aqui (chame `/licensees` antes, se for a primeira vez) e o produto precisa existir no catálogo (`code` de um `Product` ativo — os produtos padrão são semeados automaticamente na subida do BigPost: `AGENDA`, `AGF`, `BIGPOST`, `FLUXO_FINANCEIRO`, `MINHA_CIDADE_AQUI`).

Não é necessária nenhuma migration de banco para essa integração — ela só reaproveita tabelas/colunas que já existiam (`licensees.tax_id`, `products.code`, a mesma lógica de assinatura de `licenses` já usada pelo admin interno).

## Quatro portais, três autenticações

`LicenseeUser` é uma única tabela/cookie (`session_agencia`) compartilhada por 2 portais — o papel de cada usuário decide qual dos dois ele pode usar:

| Ator | Cookie / header | Papéis | Portal (caminho) | Subdomínio (produção) |
|---|---|---|---|---|
| `User` (equipe BigPost) | `session` | Master, Supervisor, Operador | `/` | *(sem subdomínio dedicado ainda)* |
| `LicenseeUser` — gestão da agência | `session_agencia` | Master, Administrador, Financeiro | `/agencia/` | `agencia.bigpost.fluxoempresa.com.br` |
| `LicenseeUser` — equipe operacional | `session_agencia` | Operador de Caixa, Expedição | `/operador/` | `operador.bigpost.fluxoempresa.com.br` |
| `Client` (cliente da agência) | `session_cliente` ou `Authorization: Bearer <api_key>` | — | `/cliente/` | `cliente.bigpost.fluxoempresa.com.br` |

Os 4 portais são páginas HTML/JS estáticas, sem build step, servidas pela própria API. O login de `LicenseeUser` (`POST /api/v1/auth/agencia/login`) recebe um campo `portal: "agencia"|"operador"` — cada frontend manda o seu fixo — e a API rejeita (403) se o papel do usuário não bate com o portal (ex.: um usuário Expedição tentando logar em `/agencia/`), pra evitar confusão de quem deveria usar qual portal.

### Modo suporte (Master interno entra em qualquer licenciado, sem saber o ID)

As telas de login de `/agencia/`, `/operador/` e `/cliente/` pedem, além de usuário/senha, o "Código do licenciado (ID)" — cada uma delas é o portal de UM licenciado só. Pra quem faz suporte (equipe BigPost, conta `User` com papel Master), isso é ruim: precisaria descobrir o ID numérico interno de cada agência antes de logar.

O link **"Sou da equipe BigPost (suporte)"**, na própria tela de login, resolve isso:

1. Some o campo de ID; pede só usuário/senha — as mesmas credenciais de uma conta Master interna (a mesma que loga em `/`, a Administração). Validado contra a tabela `users`, não contra um valor fixo do `.env` — então funciona com qualquer Master (não só a conta de bootstrap) e continua funcionando depois de trocar a senha pela tela de Usuários.
2. Autenticado, mostra a lista de licenciados (a mesma que já veio do Painel Master) pra escolher.
3. Ao escolher, entra automaticamente naquele licenciado, já com acesso total (perfil Master) — sem digitar senha de novo.

Endpoints (`app/api/auth_support.py`): `POST /api/v1/auth/support/login` → `GET /api/v1/auth/support/licensees` → `POST /api/v1/auth/support/enter/{licensee_id}` (corpo `{"portal": "agencia"|"operador"|"cliente"}`). O passo 1 usa uma sessão transitória de 10 minutos (cookie `session_support`) só pra sustentar a escolha do licenciado — não é uma sessão de trabalho.

Como o módulo Agência/Operador (`LicenseeUser`) e o módulo Cliente (`Client`) exigem uma linha real na respectiva tabela para reaproveitar toda a autorização já existente, o primeiro acesso de suporte a um licenciado cria (uma vez só) uma conta técnica reservada nele — username fixo `_suporte_bigpost`, ver `app/services/support_access.py`. Essa conta **nunca aparece** nas listagens normais ("Usuários da agência" no admin, "Clientes" na Agência — os dois endpoints filtram esse username). Todo login e toda entrada em modo suporte gera auditoria (`LOGIN_SUPORTE`, `ENTRAR_SUPORTE`, visíveis em Logs/Auditoria no admin) com o licenciado acessado.

### Roteamento por subdomínio (produção)

O mesmo processo/backend atende os 3 subdomínios (`agencia.`, `cliente.`, `operador.`) e o admin interno — é tudo a mesma API e o mesmo banco, só o HTML/JS estático servido em `/` muda conforme o cabeçalho `Host` (`app/core/subdomain_static.py`, ligado em `app/main.py`). Fora desses 3 subdomínios (domínio raiz, `localhost` puro, etc.) nada muda: os 4 portais continuam acessíveis por caminho (`/`, `/agencia/`, `/cliente/`, `/operador/`), como sempre — útil em desenvolvimento local.

**Isso não inclui apontar o DNS** dos 3 subdomínios para o servidor — isso é configuração de infraestrutura de quem administra `bigpost.fluxoempresa.com.br`, fora do escopo deste código. Depois de apontado (registro `CNAME`/`A` de cada subdomínio pro mesmo servidor/IP onde o BigPost já roda) e com HTTPS/certificado cobrindo os 3 (um certificado wildcard `*.bigpost.fluxoempresa.com.br` resolve os 3 de uma vez), o roteamento por `Host` já funciona sem precisar mexer em mais nada no código.

Pra testar isso localmente sem depender de DNS: a maioria dos navegadores/SOs resolve `*.localhost` para `127.0.0.1` automaticamente — experimente `http://agencia.localhost:8000`, `http://cliente.localhost:8000` e `http://operador.localhost:8000` (todos apontando pro mesmo `uvicorn` rodando na 8000). No Windows, se não resolver sozinho, basta adicionar 3 linhas no arquivo `hosts` (`C:\Windows\System32\drivers\etc\hosts`) apontando cada subdomínio pra `127.0.0.1`.

## Dependências e o que foi validado nesta sessão

Este ambiente de build não tinha acesso à internet para instalar pacotes (PyPI/apt bloqueados), então **não foi possível subir o servidor FastAPI de ponta a ponta aqui**. O que foi validado diretamente:

- Todo o código Python passa em `python3 -m py_compile` (sem erro de sintaxe) — modelos, schemas, routers, serviços e a migration Alembic.
- O JavaScript dos três portais (`static/index.html`, `static/agencia/index.html`, `static/cliente/index.html`) passa em `node --check`.
- O schema SQL (`scripts/schema.sql`, espelhado na migration `0001`, 17 tabelas) foi aplicado num Postgres 16 real e testado de ponta a ponta com dados: cadastro de agência (com MCU), usuários de agência nos 5 papéis, cliente com webhook configurado, emissão de encomenda, aferição, postagem, evento manual, log de entrega de webhook — `UNIQUE`, `CHECK` (formato do MCU, status da encomenda, papéis) e chaves estrangeiras testados, inclusive rejeição de status inválido.
- A assinatura/verificação de licença Ed25519 (`app/services/licensing.py`) foi testada de ponta a ponta (gerar, verificar, detectar adulteração) — só depende de `cryptography`, que estava disponível.
- O hash de senha PBKDF2, a criação/verificação de token de sessão (JWT HS256 caseiro, com o campo `typ` isolando os 3 tipos de ator) e a geração/verificação de API key (`app/core/security.py`) foram testados isoladamente.
- A assinatura HMAC de webhook (`app/services/webhooks.py`) foi testada isoladamente (determinística, 64 hex chars).
- O script de migração do protótipo antigo (`scripts/migrate_from_sqlite.py`) foi atualizado (removida a dependência do antigo cadastro de "produtos") e revalidado: gera SQL a partir de um SQLite de teste e aplica sem erro num Postgres limpo.
- O fluxo de "modo suporte" (`app/api/auth_support.py`, `app/services/support_access.py`) e as telas de login atualizadas passam em `py_compile`/`node --check`, mas **não foram exercitadas contra um Postgres real** (sem rede pra subir o servidor aqui) — faça um teste manual completo (login master → escolher licenciado → entrar → conferir que a conta `_suporte_bigpost` não aparece em "Usuários da agência" nem em "Clientes") antes de considerar produção.

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

Depois de subir, cadastre o licenciado e a licença pelo Painel Master (sistema externo — ver seção "Integração com o Painel Master" acima) ou, em dev, direto via `POST /api/v1/integrations/painel-master/licensees` com a `X-API-Key`. Pelo portal admin (`/`) cadastre o primeiro usuário `Master` da agência na tela "Licenciados" (que já pode logar em `/agencia/`, se for Administrador/Financeiro, ou `/operador/`, se for Operador de Caixa/Expedição — o papel escolhido decide qual portal ele usa) e, se aplicável, as credenciais do Correios Atende.

### Migrando os dados do protótipo antigo ("Gestão Financeira Master")

```bash
python3 scripts/migrate_from_sqlite.py /caminho/para/master.db > migration_data.sql
psql "$DATABASE_URL" -f migration_data.sql
```

Depois, copie `data/license_private.pem` e `data/license_public.pem` do protótipo antigo para o `DATA_DIR` do sistema novo (mesma chave = licenças antigas continuam válidas, inclusive o prefixo de token legado `FAGF1`). Complete endereço/contato/MCU dos licenciados migrados pela tela "Licenciados" — esses campos não existiam no protótipo antigo. Cadastre também os usuários da agência e clientes — são conceitos novos, não existiam no protótipo.

## Estrutura

```
app/
  core/       # config, banco, segurança (hash de senha, JWT, API key, RBAC), roteamento por
              # subdomínio dos portais (subdomain_static.py)
  models/     # SQLAlchemy (schema)
  schemas/    # Pydantic (validação de entrada/saída da API)
  api/        # routers FastAPI — internos (auth, licensees, ...), integração com o Painel
              # Master, agência+operador (auth_agencia, clients, shipments_agencia) e
              # cliente (auth_cliente, shipments_cliente)
  services/   # licenciamento (Ed25519), parametrizações, auditoria, webhooks
migrations/   # Alembic
scripts/      # schema.sql (referência) e migração do SQLite antigo
static/       # 4 portais HTML/JS puro, sem build step (+ br-utils.js compartilhado)
  index.html      # admin interno
  agencia/        # módulo Agência (Master, Administrador, Financeiro)
  operador/       # módulo Operador (Operador de Caixa, Expedição)
  cliente/        # módulo Cliente
```

## Próximos passos sugeridos

1. Rodar o smoke test completo numa máquina com internet (Docker é o caminho mais rápido) e testar os três portais num navegador de verdade.
2. Trocar `JWT_SECRET` e a senha do usuário Master antes de qualquer uso real.
3. Colocar atrás de HTTPS antes de aceitar tráfego de fora da rede local (`COOKIE_SECURE=true`).
4. Integração real com os Correios: hoje o código de rastreio é lançado manualmente pela agência (`POST /api/v1/agencia/shipments/{id}/postar`) — o próximo passo natural é automatizar isso (geração de etiqueta e postagem via API dos Correios, usando as credenciais do Correios Atende já cadastradas) e plugar rastreio automático (que hoje é lançado manualmente via `POST /api/v1/agencia/shipments/{id}/eventos`).
5. Entrega de webhook hoje é síncrona/best-effort (uma tentativa, sem retry automático) — evoluir para uma fila com retry usando o log em `webhook_deliveries`.
