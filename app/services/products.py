"""Catálogo fixo de produtos licenciáveis, semeado no bootstrap (idempotente
— mesmo padrão de app/services/params.py). Produtos criados depois pela tela
"Novo produto" (ver app/api/products.py) são sempre `is_custom=True` e não
passam por aqui."""
from sqlalchemy.orm import Session

from app.models.models import Product

CORE_PRODUCTS: list[dict] = [
    {"code": "AGENDA", "name": "Agenda"},
    {"code": "AGF", "name": "AGF"},
    {"code": "BIGPOST", "name": "BigPost"},
    {"code": "FLUXO_FINANCEIRO", "name": "Fluxo Financeiro"},
    {"code": "MINHA_CIDADE_AQUI", "name": "Minha Cidade Aqui"},
]


def seed_core_products(db: Session) -> None:
    existing = {p.code for p in db.query(Product.code).all()}
    for cfg in CORE_PRODUCTS:
        if cfg["code"] in existing:
            continue
        db.add(Product(code=cfg["code"], name=cfg["name"], is_custom=False, active=True))
    db.commit()
