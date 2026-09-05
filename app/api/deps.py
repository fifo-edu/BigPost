"""Utilitários compartilhados pelos routers."""
import hmac

from fastapi import Header, HTTPException, Request

from app.core.config import settings


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def require_painel_master_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Autenticação por segredo compartilhado para a API de integração usada
    pelo Painel Master (sistema externo) — não é um usuário `User` interno,
    então não passa pelo login/cookie de sessão normal. Configurar
    PAINEL_MASTER_API_KEY no .env (aqui) e o mesmo valor no Painel Master."""
    if not settings.painel_master_api_key:
        raise HTTPException(status_code=401, detail="Integração com o Painel Master não está configurada neste BigPost")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.painel_master_api_key):
        raise HTTPException(status_code=401, detail="Chave de API inválida")
