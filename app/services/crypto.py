"""Criptografia simétrica para segredos que precisam ser recuperados em texto
puro pelo backend (ao contrário de senha de login, que só precisa ser
verificada — essa sim, com hash irreversível em core/security.py).

Uso principal: usuário/senha do www.correiosatende.correios.com.br por MCU
(app/models/models.py::CorreiosCredential). Usa Fernet (AES-128-CBC +
HMAC-SHA256 autenticado, da própria lib `cryptography`, já dependência do
projeto por causa da assinatura de licença) com uma chave própria, separada
da chave de assinatura de licença.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _key_path():
    return settings.data_path / "credentials.key"


def ensure_key() -> None:
    path = _key_path()
    if path.exists():
        return
    path.write_bytes(Fernet.generate_key())


def encrypt(plaintext: str) -> str:
    ensure_key()
    fernet = Fernet(_key_path().read_bytes())
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    ensure_key()
    fernet = Fernet(_key_path().read_bytes())
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
