"""Roteamento dos 3 portais operacionais (Agência, Cliente, Operador) por
subdomínio, para produção — ex.: agencia.bigpost.fluxoempresa.com.br,
cliente.bigpost.fluxoempresa.com.br, operador.bigpost.fluxoempresa.com.br.

O mesmo backend/banco atende os 3 (e o admin interno) — só o HTML/JS estático
servido em "/" muda conforme o cabeçalho Host. Chamadas de API (`/api/...`)
nunca passam por aqui: são as mesmas nos 3 subdomínios.

Implementado como middleware ASGI simples (sem depender de recursos de Host
routing do Starlette que não dá pra testar de ponta a ponta neste ambiente
sem acesso à internet) — só olha o primeiro rótulo do Host e delega pro
app estático correspondente; qualquer Host que não bata com nenhum dos 3
(domínio raiz, "localhost" puro, IP, etc.) segue normalmente para o resto da
aplicação, que já serve o admin interno em "/" e os 3 portais também por
caminho (`/agencia`, `/cliente`, `/operador`) — útil em desenvolvimento local
ou enquanto o DNS dos subdomínios não estiver apontado.

Dica pra testar localmente sem mexer em DNS: a maioria dos navegadores/SOs
resolve "*.localhost" para 127.0.0.1 automaticamente — dá pra tentar
http://agencia.localhost:8000, http://cliente.localhost:8000 e
http://operador.localhost:8000 (no Windows, se não resolver sozinho, basta
adicionar as 3 linhas no arquivo hosts apontando pra 127.0.0.1)."""
from starlette.types import ASGIApp, Receive, Scope, Send


class SubdomainStaticMiddleware:
    def __init__(self, app: ASGIApp, portal_apps: dict[str, ASGIApp]):
        self.app = app
        self.portal_apps = portal_apps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return

        host = b""
        for key, value in scope.get("headers") or []:
            if key == b"host":
                host = value
                break
        subdomain = host.decode(errors="ignore").split(":")[0].split(".")[0].lower()

        portal_app = self.portal_apps.get(subdomain)
        if portal_app is not None:
            await portal_app(scope, receive, send)
            return

        await self.app(scope, receive, send)
