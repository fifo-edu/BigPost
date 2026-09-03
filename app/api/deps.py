"""Utilitário compartilhado pelos routers: extrai IP do cliente pra auditoria."""
from fastapi import Request


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
