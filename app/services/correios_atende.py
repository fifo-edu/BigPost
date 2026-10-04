"""Postagem automática pelo Correios Atende, com as credenciais da agência
postadora (AGF) da loja: o objeto aferido no BigPost é registrado na
integração do Correios Atende, que confirma a aferição e posta o objeto.

Estado (2026-10-04): o fluxo do BigPost em volta disto está pronto (ver
POST /api/v1/agencia/shipments/{id}/aferir-e-postar), mas a chamada aos
Correios em `aferir_e_postar` AINDA NÃO ESTÁ IMPLEMENTADA — não há
documentação pública dessa integração, e um corpo de requisição errado gera
postagem e cobrança reais. Ela levanta AtendeNaoImplementado até recebermos
o manual/Swagger da integração e, de preferência, um ambiente de homologação.

Ao implementar, classifique cada falha numa das exceções abaixo — o BigPost
decide o que fazer com a encomenda a partir do tipo:
  - AtendeRecusa: os Correios recusaram o objeto por causa dos dados dele
    (CEP inválido, medida/peso fora do limite, serviço indisponível...).
    A encomenda vai para a fila de erro do SAC e o cliente é avisado.
  - AtendeIndisponivel: falha temporária (rede, timeout, 5xx). A encomenda
    continua Aferida e pode ser reenviada. ATENÇÃO: num timeout não dá para
    saber se a postagem aconteceu — antes de reenviar, a implementação deve
    consultar nos Correios se o objeto já foi postado, para não postar duas
    vezes.
  - AtendeConfigError: problema de cadastro/credencial (senha errada, MCU
    errado, agência bloqueada). A encomenda continua Aferida; quem resolve é
    o Master no cadastro da agência postadora.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.models import Licensee, PostingAgency, Shipment
from app.services.crypto import decrypt


# Vira True quando `aferir_e_postar` estiver implementada e validada em
# homologação. Enquanto False, o BigPost nem oferece a postagem automática
# (mesmo com o parâmetro postagem.atende_automatica ligado).
IMPLEMENTADA = False


class CorreiosAtendeError(Exception):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


class AtendeConfigError(CorreiosAtendeError):
    """Cadastro/credencial impede a postagem — não é culpa do objeto."""


class AtendeNaoImplementado(AtendeConfigError):
    """A chamada aos Correios ainda não foi implementada."""


class AtendeRecusa(CorreiosAtendeError):
    """Os Correios recusaram o objeto pelos dados dele — vai para o SAC."""


class AtendeIndisponivel(CorreiosAtendeError):
    """Falha temporária de comunicação — pode tentar de novo."""


@dataclass
class AtendeCredencial:
    agency_id: int
    agency_name: str
    mcu: str
    username: str
    password: str = field(repr=False)  # nunca aparece em log/repr


@dataclass
class ResultadoPostagem:
    tracking_code: str
    # Valor que os Correios cobraram da agência pela postagem, se a
    # integração informar (diferente de Shipment.price_confirmed, que é o
    # preço cobrado do cliente).
    postage_cost: float | None = None


def credencial_da_loja(db: Session, licensee_id: int) -> AtendeCredencial:
    """Credencial do Correios Atende da agência postadora vinculada à loja.
    Levanta AtendeConfigError com uma mensagem para o operador se faltar algo."""
    licensee = db.get(Licensee, licensee_id)
    if not licensee or not licensee.posting_agency_id:
        raise AtendeConfigError(
            "Esta loja ainda não tem agência postadora vinculada (Admin → Agências Postadoras → Lojas).",
            code="SEM_AGENCIA",
        )
    agency = db.get(PostingAgency, licensee.posting_agency_id)
    name = agency.trade_name or agency.legal_name
    if not agency.active:
        raise AtendeConfigError(f"A agência postadora {name} está inativa.", code="AGENCIA_INATIVA")
    missing = [
        label
        for label, value in (
            ("MCU", agency.mcu),
            ("usuário do Correios Atende", agency.correios_username),
            ("senha do Correios Atende", agency.correios_password_encrypted),
        )
        if not value
    ]
    if missing:
        raise AtendeConfigError(
            f"Cadastro da agência postadora {name} incompleto: falta {', '.join(missing)}.",
            code="CREDENCIAL_INCOMPLETA",
        )
    password = decrypt(agency.correios_password_encrypted)
    if password is None:
        raise AtendeConfigError(
            f"Não foi possível decifrar a senha salva da agência {name} — cadastre a senha de novo.",
            code="SENHA_ILEGIVEL",
        )
    return AtendeCredencial(
        agency_id=agency.id, agency_name=name, mcu=agency.mcu, username=agency.correios_username, password=password
    )


def aferir_e_postar(cred: AtendeCredencial, shipment: Shipment) -> ResultadoPostagem:
    """Registra no Correios Atende a aferição do objeto (peso real, medidas
    conferidas, peso tarifado) e posta o objeto. Devolve o código de
    rastreio. Ver o docstring do módulo para a classificação de erros."""
    raise AtendeNaoImplementado(
        "A postagem automática pelo Correios Atende ainda não está disponível: falta a documentação "
        "da integração. Poste manualmente pelo botão Postar.",
        code="NAO_IMPLEMENTADO",
    )
