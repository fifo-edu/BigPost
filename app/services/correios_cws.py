"""Integração com o CWS (Correios Web Services) — a API oficial dos Correios
para sistemas integradores, usada pelo módulo BigPost Cliente para autenticar
e (quando a Pré-Postagem estiver implementada) enviar encomendas aferidas
para gerar rastreio/etiqueta de verdade.

Não confundir com CorreiosCredential/app/api/... (login do site
www.correiosatende.correios.com.br, usado pelos módulos Agência/Operação) —
são sistemas e credenciais completamente diferentes.

Ambiente: controlado por settings.correios_cws_base_url
(app/core/config.py) — começa em homologação (cwshom.correios.com.br) e só
deve trocar para produção (cws.correios.com.br) depois do fluxo validado lá,
porque em produção a Pré-Postagem gera rastreio/etiqueta reais.

Estado desta integração (2026-09-09):
  - Autenticação (token de acesso): CONFIRMADA e implementada abaixo, com
    base no Swagger autenticado do CWS (grupo "Token").
  - Pré-Postagem (enviar a encomenda aferida e receber rastreio/etiqueta):
    AINDA NÃO IMPLEMENTADA — falta confirmar o contrato exato (endpoint,
    corpo da requisição e da resposta) no Swagger autenticado. Ver
    `criar_pre_postagem` abaixo: propositalmente levanta NotImplementedError
    em vez de adivinhar nomes de campo — um corpo errado pode gerar um
    registro real (e cobrança real) nos Correios.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import ClientCorreiosCredential, Shipment
from app.services.crypto import decrypt

# Confirmado no Swagger autenticado do CWS (grupo "Token"):
#   POST /v1/autentica                  -> autentica só com usuário/senha
#   POST /v1/autentica/contrato         -> corpo {"numero": "<contrato>", "dr": <int>}
#   POST /v1/autentica/cartaopostagem   -> mesmo formato de corpo, por analogia
#                                          ao endpoint acima (ver nota em
#                                          get_valid_token)
# Usamos o de cartão de postagem porque é o dado que o BigPost Cliente já
# guarda (ClientCorreiosCredential.postal_card).
PATH_AUTENTICA_CARTAO_POSTAGEM = "/v1/autentica/cartaopostagem"

# Margem de segurança: renova o token um pouco antes do "expiraEm" real
# informado pelos Correios, pra nunca usar um token expirado por causa da
# latência da própria chamada de Pré-Postagem.
TOKEN_REFRESH_MARGIN = timedelta(minutes=2)

# Fallback só usado se a resposta do CWS não trouxer "expiraEm" (não deveria
# acontecer com uma resposta 201 válida, mas evita cachear um token "para
# sempre" por engano se o formato mudar).
FALLBACK_TOKEN_TTL = timedelta(minutes=5)

REQUEST_TIMEOUT_SECONDS = 30.0


class CorreiosCWSError(Exception):
    """Erro de comunicação/autenticação com o CWS dos Correios. `status_code`
    e `msgs` vêm do envelope de erro padrão do CWS quando disponível:
    {"msgs": [...], "date": ..., "method": ..., "path": ..., "causa": ...,
    "stackTrace": ...}."""

    def __init__(self, message: str, *, status_code: int | None = None, msgs: list[str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.msgs = msgs or []


@dataclass
class _CachedToken:
    token: str
    expires_at: datetime


# Cache em memória do processo — suficiente porque o BigPost roda como um
# único processo web (uvicorn) por enquanto. Se um dia rodar com múltiplos
# workers/processos, cada um terá seu próprio cache (token extra sendo
# gerado não é um problema — os Correios permitem múltiplos tokens válidos
# simultâneos por credencial).
_token_cache: dict[int, _CachedToken] = {}
_cache_lock = threading.Lock()


def _extract_error(resp: httpx.Response) -> tuple[str, list[str]]:
    try:
        data = resp.json()
    except ValueError:
        return f"Correios retornou HTTP {resp.status_code}", []
    msgs = [str(m) for m in (data.get("msgs") or [])]
    if msgs:
        return "; ".join(msgs), msgs
    causa = data.get("causa")
    if causa:
        return str(causa), msgs
    return f"Correios retornou HTTP {resp.status_code}", msgs


def _parse_expira_em(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow() + FALLBACK_TOKEN_TTL
    try:
        # "expiraEm" vem como ISO 8601; normaliza um eventual "Z" final e
        # descarta timezone pra comparar com datetime.utcnow() (naive), como
        # o resto do projeto já faz (ver app/models/models.py::now()).
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow() + FALLBACK_TOKEN_TTL


def _autenticar_cartao_postagem(
    *, correios_username: str, codigo_acesso: str, postal_card: str, dr: int
) -> _CachedToken:
    """Chama POST /v1/autentica/cartaopostagem. Autenticação por Basic Auth
    (usuário CWS + código de acesso) — padrão do CWS para os endpoints de
    geração de token; confirme no botão "Authorize" do Swagger autenticado
    se esse projeto ainda não validou isso na prática."""
    url = f"{settings.correios_cws_base_url}{PATH_AUTENTICA_CARTAO_POSTAGEM}"
    body = {"numero": postal_card, "dr": dr}

    try:
        resp = httpx.post(
            url,
            json=body,
            auth=(correios_username, codigo_acesso),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise CorreiosCWSError(f"Falha de comunicação com o CWS dos Correios: {exc}") from exc

    if resp.status_code != 201:
        message, msgs = _extract_error(resp)
        raise CorreiosCWSError(message, status_code=resp.status_code, msgs=msgs)

    data = resp.json()
    token = data.get("token")
    if not token:
        raise CorreiosCWSError(
            "Resposta do CWS sem campo 'token' — formato inesperado, confira se o contrato mudou.",
            status_code=resp.status_code,
        )
    return _CachedToken(token=token, expires_at=_parse_expira_em(data.get("expiraEm")))


def get_valid_token(db: Session, licensee_id: int, *, force_refresh: bool = False) -> str:
    """Retorna um token Bearer válido do CWS para o licenciado, reaproveitando
    o cache em memória enquanto não estiver perto de expirar. Gera um novo
    via /v1/autentica/cartaopostagem quando necessário.

    Levanta CorreiosCWSError se:
      - não houver credencial cadastrada/ativa para o licenciado;
      - a credencial estiver sem código de acesso ou sem DR cadastrados;
      - os Correios recusarem a autenticação (credencial errada, DR errado,
        cartão de postagem vencido/inválido, etc.).
    """
    if not force_refresh:
        with _cache_lock:
            cached = _token_cache.get(licensee_id)
        if cached and datetime.utcnow() < cached.expires_at - TOKEN_REFRESH_MARGIN:
            return cached.token

    cred = (
        db.query(ClientCorreiosCredential)
        .filter(ClientCorreiosCredential.licensee_id == licensee_id)
        .first()
    )
    if not cred or not cred.active:
        raise CorreiosCWSError(
            "Nenhuma credencial de Correios (BigPost Cliente) ativa cadastrada para este licenciado."
        )
    if not cred.token_encrypted:
        raise CorreiosCWSError(
            "Credencial Correios cadastrada sem código de acesso — atualize em Licenças → BigPost."
        )
    if not cred.dr:
        raise CorreiosCWSError(
            "Credencial Correios sem Diretoria Regional (DR) cadastrada — necessária para autenticar no CWS."
        )

    codigo_acesso = decrypt(cred.token_encrypted)
    if codigo_acesso is None:
        raise CorreiosCWSError("Não foi possível decifrar o código de acesso salvo — recadastre a credencial.")

    cached_token = _autenticar_cartao_postagem(
        correios_username=cred.correios_username,
        codigo_acesso=codigo_acesso,
        postal_card=cred.postal_card,
        dr=cred.dr,
    )

    with _cache_lock:
        _token_cache[licensee_id] = cached_token

    cred.last_validated_at = datetime.utcnow()
    db.commit()

    return cached_token.token


def criar_pre_postagem(db: Session, licensee_id: int, shipment: Shipment) -> dict:
    """*** ESTRUTURA/ESQUELETO — AINDA NÃO IMPLEMENTADO ***

    Isto é o ponto de entrada que `app/api/shipments_agencia.py::postar_shipment`
    deve chamar no lugar do preenchimento manual de `tracking_code`, uma vez
    implementado. Propositalmente levanta NotImplementedError em vez de
    adivinhar o contrato da API de Pré-Postagem: falta confirmar, no Swagger
    autenticado do CWS (grupo "Pré-postagem"/"Postagem"), pelo menos:

      1. O endpoint exato (path) da Pré-Postagem.
      2. O corpo da requisição — provável mapeamento a partir do que já
         temos no `Shipment` (não confirmado, só um chute educado):
           - remetente: dados do licenciado (Licensee.legal_name/endereço)
             ou do cartão de postagem, ainda não sabemos qual o CWS espera
           - destinatário: shipment.recipient_name, recipient_tax_id,
             recipient_zip, recipient_street/number/complement/district/
             city/state
           - pacote: shipment.weight_confirmed_kg (aferido, não o
             declarado), length_cm/width_cm/height_cm, declared_value,
             service_type
           - identificadores CWS: cred.postal_card / cred.contract_number
      3. O corpo da resposta — pelo menos o código de rastreio, e
         possivelmente uma etiqueta (PDF/ZPL em base64 ou uma URL).
      4. Qual o código de sucesso HTTP (provavelmente 201, como no grupo
         Token, mas não confirmado para este endpoint).

    Assim que esse contrato estiver confirmado, esta função deve:
      - obter um token válido via `get_valid_token(db, licensee_id)`;
      - montar o corpo confirmado e chamar `httpx.post(...)` com header
        Authorization: Bearer <token>;
      - tratar erro com o mesmo padrão de `_extract_error`/CorreiosCWSError
        usado acima;
      - devolver um dict com pelo menos `tracking_code` (e a etiqueta, se
        vier), pra `postar_shipment` gravar em `shipment.tracking_code`.
    """
    raise NotImplementedError(
        "Pré-Postagem ainda não implementada: falta confirmar o contrato exato "
        "(endpoint, corpo da requisição e da resposta) no Swagger autenticado do "
        "CWS. Ver o TODO detalhado em app/services/correios_cws.py::criar_pre_postagem."
    )
