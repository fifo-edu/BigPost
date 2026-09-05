"""Catálogo de produtos/sistemas licenciáveis (Agenda, AGF, BigPost, Fluxo
Financeiro, Minha Cidade Aqui, ...). Uma agência licenciada pode ter uma
licença por produto contratado. Os produtos fixos do catálogo são semeados
no bootstrap (ver app/services/products.py); qualquer produto criado por
aqui é sempre marcado `is_custom=True` e aparece agrupado sob "Customizados"
na tela de Licenças."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.db import get_db
from app.core.security import require_role
from app.models.models import Product, User
from app.schemas.schemas import ProductCreate, ProductOut
from app.services.audit import log_action

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), user: User = Depends(require_role("Operador"))):
    return db.query(Product).filter(Product.active.is_(True)).order_by(Product.is_custom, Product.name).all()


@router.post("", response_model=ProductOut)
def create_product(
    payload: ProductCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("Supervisor")),
):
    """Cria um produto customizado (fora do catálogo fixo) — aparece
    agrupado sob "Customizados" na tela de Licenças."""
    product = Product(code=payload.code.strip().upper(), name=payload.name.strip(), is_custom=True, active=True)
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Já existe um produto com esse código")
    db.refresh(product)
    log_action(
        db,
        username=user.username,
        role=user.role,
        action="CADASTRAR_PRODUTO_CUSTOMIZADO",
        entity=f"product:{product.id}",
        after={"code": product.code, "name": product.name},
        ip_address=client_ip(request),
    )
    return product
