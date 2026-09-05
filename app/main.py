import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import (
    auth,
    auth_agencia,
    auth_cliente,
    bank,
    charges,
    client_correios,
    clients,
    correios,
    dashboard,
    integrations_painel_master,
    licensee_users,
    licenses,
    licensees,
    params,
    products,
    shipments_agencia,
    shipments_cliente,
    users,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.core.subdomain_static import SubdomainStaticMiddleware
from app.models.models import BankConfig, User
from app.services.licensing import ensure_keys
from app.services.params import seed_defaults
from app.services.products import seed_core_products

logger = logging.getLogger("bigpost")


def _static_app(directory: str) -> ASGIApp:
    """Monta StaticFiles(directory) normalmente. Se a pasta não existir (ex.:
    um zip de atualização extraído no lugar errado, faltando um diretório
    novo como "static/operador"), NÃO derruba o servidor inteiro só por
    causa de um portal — sem isto, `StaticFiles.__init__` levanta
    `RuntimeError` na subida e os 4 portais ficam fora do ar, não só o que
    está com a pasta faltando. Em vez disso, loga um erro claro e serve uma
    resposta explicando o problema só para esse portal."""
    if not os.path.isdir(directory):
        logger.error(
            "Pasta de portal estático não encontrada: '%s' (diretório atual: '%s'). "
            "O servidor vai subir mesmo assim, mas esse portal vai responder erro até "
            "a pasta existir no lugar certo — confira se o zip da atualização foi "
            "extraído dentro da instalação correta do BigPost.",
            directory,
            os.getcwd(),
        )

        async def missing(scope: Scope, receive: Receive, send: Send) -> None:
            response = PlainTextResponse(
                f"Pasta '{directory}' não encontrada no servidor (diretório atual: '{os.getcwd()}'). "
                "Provavelmente a atualização foi extraída no lugar errado — confira se essa pasta "
                "existe dentro da instalação do BigPost e reinicie o servidor.",
                status_code=500,
            )
            await response(scope, receive, send)

        return missing
    return StaticFiles(directory=directory, html=True)


def bootstrap() -> None:
    """Roda na subida do processo: garante chaves de licença, usuário Master
    inicial e parâmetros padrão. Idempotente — seguro rodar toda vez."""
    ensure_keys()
    db = SessionLocal()
    try:
        if not db.query(User).first():
            db.add(
                User(
                    username=settings.bootstrap_master_username,
                    full_name="Administrador Master",
                    role="Master",
                    password_hash=hash_password(settings.bootstrap_master_password),
                    active=True,
                )
            )
        if not db.get(BankConfig, 1):
            db.add(BankConfig(id=1))
        db.commit()
        seed_defaults(db)
        seed_core_products(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="BigPost", lifespan=lifespan)

# Administração interna (equipe BigPost: cadastro/licenciamento de agências)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(licensees.router)
app.include_router(licensee_users.router)
app.include_router(correios.router)
app.include_router(client_correios.router)
app.include_router(products.router)
app.include_router(licenses.router)
app.include_router(charges.router)
app.include_router(bank.router)
app.include_router(params.router)
app.include_router(dashboard.router)

# Integração com o Painel Master (sistema externo — cadastra/licencia por lá
# e chama esta API para replicar o necessário aqui). Ver
# app/api/integrations_painel_master.py.
app.include_router(integrations_painel_master.router)

# Módulo Agência (equipe da agência licenciada)
app.include_router(auth_agencia.router)
app.include_router(clients.router)
app.include_router(shipments_agencia.router)

# Módulo Cliente (clientes da agência — portal e integração)
app.include_router(auth_cliente.router)
app.include_router(shipments_cliente.router)

# Portais estáticos (HTML/JS puro, sem build step) — mais específicos primeiro,
# senão o mount de "/" (admin interno) engoliria as rotas abaixo. Usa
# _static_app (acima) em vez de StaticFiles(...) direto para que uma pasta
# faltando não derrube o servidor inteiro — só aquele portal fica com erro.
static_agencia = _static_app("static/agencia")
static_cliente = _static_app("static/cliente")
static_operador = _static_app("static/operador")
static_admin = _static_app("static")

app.mount("/agencia", static_agencia, name="static-agencia")
app.mount("/cliente", static_cliente, name="static-cliente")
app.mount("/operador", static_operador, name="static-operador")
app.mount("/", static_admin, name="static")

# Em produção os 3 portais operacionais vivem em subdomínios próprios
# (agencia./cliente./operador.bigpost.fluxoempresa.com.br) servidos por este
# mesmo backend — o middleware abaixo decide qual portal estático servir em
# "/" olhando o cabeçalho Host. Fora desses 3 subdomínios (domínio raiz,
# localhost puro, etc.) nada muda: continua caindo nos mounts por caminho
# acima. Ver app/core/subdomain_static.py.
app.add_middleware(
    SubdomainStaticMiddleware,
    portal_apps={"agencia": static_agencia, "cliente": static_cliente, "operador": static_operador},
)
