"""Assinatura e verificação de licenças com Ed25519.

Reaproveita o padrão do protótipo "Gestão Financeira Master": o payload da
licença é serializado em JSON canônico e assinado com uma chave Ed25519 da
instalação Master. O token resultante (formato "PM1.<payload_b64>.<assinatura_b64>")
pode ser validado OFFLINE por qualquer módulo (Cliente, Agência) que tenha a
chave pública — sem precisar chamar o Master a cada verificação. O endpoint
de heartbeat (online) serve para revogação/expiração e para contar uso real.

A chave privada NUNCA deve sair desta instalação Master.
"""
import base64
import json
import secrets
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy.orm import Session

from app.core.config import settings

TOKEN_PREFIX = "PM1"
# Prefixo usado pelo protótipo anterior ("Gestão Financeira Master"). Mantido
# apenas para que licenças já emitidas e distribuídas antes da migração
# continuem validando (a chave Ed25519 é a mesma, só o prefixo do token muda).
LEGACY_TOKEN_PREFIXES = ("FAGF1",)


def _key_paths() -> tuple[Path, Path]:
    d = settings.data_path
    return d / "license_private.pem", d / "license_public.pem"


def ensure_keys() -> None:
    priv_path, pub_path = _key_paths()
    if priv_path.exists() and pub_path.exists():
        return
    key = Ed25519PrivateKey.generate()
    priv_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def sign_payload(payload: dict) -> str:
    ensure_keys()
    priv_path, _ = _key_paths()
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    key = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    signature = key.sign(raw)
    return f"{TOKEN_PREFIX}.{_b64(raw)}.{_b64(signature)}"


def verify_license_code(license_code: str) -> dict | None:
    """Retorna o payload se a assinatura for válida, ou None caso contrário."""
    ensure_keys()
    try:
        prefix, raw_b64, sig_b64 = license_code.split(".")
        if prefix != TOKEN_PREFIX and prefix not in LEGACY_TOKEN_PREFIXES:
            return None
        raw = _unb64(raw_b64)
        signature = _unb64(sig_b64)
        _, pub_path = _key_paths()
        pub_key: Ed25519PublicKey = serialization.load_pem_public_key(pub_path.read_bytes())
        pub_key.verify(signature, raw)
        return json.loads(raw)
    except Exception:
        return None


def public_key_pem() -> str:
    ensure_keys()
    _, pub_path = _key_paths()
    return pub_path.read_text()


def build_license(
    db: Session,
    *,
    licensee,
    product,
    expires_at: str | None,
    max_users: int | None,
    features: dict | None,
    created_by: str | None,
):
    """Monta, assina e persiste uma `License` para (licensee, product).

    Extraído para cá para que o endpoint interno de emissão
    (app/api/licenses.py::generate_license, usado pela equipe BigPost) e a
    integração do Painel Master (app/api/integrations_painel_master.py,
    usada pelo sistema externo que realmente vende/cobra a licença) gerem
    sempre o mesmo formato de token, pela mesma lógica.

    Retorna (license_row, token_payload) — o payload é devolvido também para
    quem chama poder registrar no log de auditoria com o detalhe completo.
    """
    from app.models.models import License  # import local: evita import circular com app.models

    features = features or {"cliente": True, "agencia": True}
    license_uid = secrets.token_hex(8).upper()
    token_payload = {
        "license_id": license_uid,
        "product_code": product.code,
        "customer_name": licensee.legal_name,
        "tax_id": licensee.tax_id,
        "issued_at": date.today().isoformat(),
        "expires_at": expires_at or "PERPETUA",
        "max_users": max_users or licensee.contracted_users,
        "features": features,
    }
    license_code = sign_payload(token_payload)

    license_row = License(
        licensee_id=licensee.id,
        product_id=product.id,
        license_code=license_code,
        license_uid=license_uid,
        expires_at=token_payload["expires_at"],
        max_users=token_payload["max_users"],
        features=features,
        status="Ativa",
        created_by=created_by,
    )
    db.add(license_row)
    db.commit()
    db.refresh(license_row)
    return license_row, token_payload
