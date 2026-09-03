"""Autenticação e RBAC.

Três tipos de ator, três mecanismos de sessão (cookies com nomes diferentes,
pra não colidir — são portais/páginas HTML separadas):

- `User` (equipe interna do BigPost — administra cadastro/licenciamento de
  todas as agências) — cookie `session`, papéis em ROLE_RANK.
- `LicenseeUser` (equipe de uma agência licenciada — módulo Agência) —
  cookie `session_agencia`, papéis em LICENSEE_ROLE_RANK.
- `Client` (cliente de uma agência — módulo Cliente) — cookie
  `session_cliente` OU `Authorization: Bearer <api_key>` pra integração
  programática (emissão de etiqueta automatizada, sem precisar logar).

Implementado só com biblioteca padrão do Python + `cryptography` (já usada
pra licenças) — sem depender de passlib/pyjwt. O "token de sessão" é um JWT
HS256 minimalista feito à mão; não é uma lib JWT genérica, não usar pra nada
além do login destes três portais.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.models import Client, LicenseeUser, User

# Papéis internos do BigPost — equipe que administra cadastro, licenciamento
# e cobrança de todas as agências licenciadas.
ROLE_RANK = {"Operador": 1, "Supervisor": 2, "Master": 3}

# Papéis dos usuários de uma agência licenciada (tabela LicenseeUser) — quem
# opera o dia a dia no módulo Agência. Master > Administrador > Financeiro;
# Operador de Caixa e Expedição são papéis operacionais paralelos, um não
# manda no outro.
LICENSEE_ROLE_RANK = {
    "Operador de Caixa": 1,
    "Expedição": 1,
    "Financeiro": 2,
    "Administrador": 3,
    "Master": 4,
}

PBKDF2_ITERATIONS = 180_000
API_KEY_PREFIX = "bp_live_"


# --------------------------- senha ---------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = password_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# --------------------------- API key (Client, uso em integração) ---------------------------
def generate_api_key() -> tuple[str, str, str]:
    """Retorna (chave_em_texto_puro, hash_pra_guardar, prefixo_pra_exibir).
    A chave em texto puro só existe aqui — nunca é salva, só devolvida uma
    vez pra API no momento da geração."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(24)
    return raw, hash_password(raw), raw[: len(API_KEY_PREFIX) + 6] + "…"


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    return verify_password(raw_key, key_hash)


# --------------------------- token de sessão (JWT HS256 caseiro) ---------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_token(subject: str, typ: str, extra: dict | None = None) -> str:
    """typ identifica qual tipo de ator o token representa ('admin',
    'licensee_user' ou 'client') — evita que um cookie de um portal seja
    reaproveitado como se fosse de outro."""
    header = {"alg": "HS256", "typ": "JWT"}
    expire = int(time.time()) + settings.jwt_expire_minutes * 60
    payload = {"sub": subject, "typ": typ, "exp": expire, **(extra or {})}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(settings.jwt_secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def decode_token(token: str) -> dict | None:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(settings.jwt_secret.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# Compatibilidade com o código existente do portal admin (User)
def create_access_token(user: User) -> str:
    return create_token(user.username, "admin", {"role": user.role})


# --------------------------- dependências FastAPI: admin interno ---------------------------
def get_current_user(
    session: str | None = Cookie(default=None), db: Session = Depends(get_db)
) -> User:
    payload = decode_token(session) if session else None
    if not payload or payload.get("typ") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    user = db.query(User).filter(User.username == payload["sub"], User.active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida")
    return user


def require_role(min_role: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK.get(min_role, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requer perfil {min_role} ou superior",
            )
        return user

    return checker


# --------------------------- dependências FastAPI: agência (LicenseeUser) ---------------------------
def get_current_licensee_user(
    session_agencia: str | None = Cookie(default=None), db: Session = Depends(get_db)
) -> LicenseeUser:
    payload = decode_token(session_agencia) if session_agencia else None
    if not payload or payload.get("typ") != "licensee_user":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    licensee_user = (
        db.query(LicenseeUser)
        .filter(
            LicenseeUser.id == payload.get("uid"),
            LicenseeUser.licensee_id == payload.get("licensee_id"),
            LicenseeUser.active.is_(True),
        )
        .first()
    )
    if not licensee_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida")
    return licensee_user


def require_licensee_role(min_role: str):
    def checker(user: LicenseeUser = Depends(get_current_licensee_user)) -> LicenseeUser:
        if LICENSEE_ROLE_RANK.get(user.role, 0) < LICENSEE_ROLE_RANK.get(min_role, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requer perfil {min_role} ou superior",
            )
        return user

    return checker


def require_licensee_any_role(*roles: str):
    """Pra ações operacionais específicas de um papel (ex.: só Operador de
    Caixa afere, só Expedição posta) — mas Administrador/Master, por serem
    hierarquicamente superiores aos papéis operacionais, sempre podem fazer
    qualquer coisa que um papel operacional faça."""

    def checker(user: LicenseeUser = Depends(get_current_licensee_user)) -> LicenseeUser:
        if user.role in roles or LICENSEE_ROLE_RANK.get(user.role, 0) >= LICENSEE_ROLE_RANK["Administrador"]:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requer um dos perfis: {', '.join(roles)} (ou Administrador/Master)",
        )

    return checker


# --------------------------- dependências FastAPI: cliente (Client) ---------------------------
def get_current_client(
    session_cliente: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Client:
    # 1) Authorization: Bearer <api_key> — uso em integração programática.
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token.startswith(API_KEY_PREFIX):
            candidates = db.query(Client).filter(Client.active.is_(True), Client.api_key_hash.isnot(None)).all()
            for client in candidates:
                if verify_api_key(token, client.api_key_hash):
                    return client
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chave de API inválida")
        # não é api_key — tenta como JWT (integração que preferiu logar e usar o token)
        payload = decode_token(token)
        if payload and payload.get("typ") == "client":
            client = db.get(Client, payload.get("uid"))
            if client and client.active:
                return client
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    # 2) cookie do portal manual
    payload = decode_token(session_cliente) if session_cliente else None
    if payload and payload.get("typ") == "client":
        client = db.get(Client, payload.get("uid"))
        if client and client.active:
            return client

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
