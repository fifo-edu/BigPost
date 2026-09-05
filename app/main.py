from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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
from app.models.models import BankConfig, User
from app.services.licensing import ensure_keys
from app.services.params import seed_defaults
from app.services.products import seed_core_products


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
# senão o mount de "/" (admin interno) engoliria as rotas abaixo.
app.mount("/agencia", StaticFiles(directory="static/agencia", html=True), name="static-agencia")
app.mount("/cliente", StaticFiles(directory="static/cliente", html=True), name="static-cliente")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
