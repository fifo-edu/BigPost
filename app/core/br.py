"""Padrões brasileiros de cadastro: CPF, CNPJ (inclusive o alfanumérico), CEP,
UF e telefone (DDD + fixo/celular). Aceitam o valor com ou sem máscara e
devolvem só os caracteres que importam ("12.345.678/0001-95" -> "12345678000195");
valor inválido levanta ValueError com a mensagem para o usuário.

Os tipos `Cpf`, `Cnpj`, `Cep`, `Uf`, `TelefoneFixo`, `TelefoneCelular` e
`Telefone` servem direto nos schemas Pydantic (vazio vira None).

CNPJ alfanumérico (IN RFB 2.229/2024, emitido desde julho de 2026): as 12
primeiras posições podem ter letras maiúsculas e os 2 dígitos verificadores
continuam numéricos. O cálculo é o mesmo módulo 11 do CNPJ numérico, usando
para cada caractere o valor do código ASCII menos 48 (dígitos valem 0–9,
"A" vale 17, "B" 18...)."""
import re
from typing import Annotated

from pydantic import BeforeValidator

UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

DDDS = frozenset(
    int(d)
    for d in (
        "11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 "
        "51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 "
        "91 92 93 94 95 96 97 98 99"
    ).split()
)


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _vazio(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _dv_mod11(valores: list[int], pesos: list[int]) -> int:
    resto = sum(v * p for v, p in zip(valores, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cpf_valido(cpf: str) -> bool:
    d = only_digits(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    nums = [int(c) for c in d]
    dv1 = _dv_mod11(nums[:9], list(range(10, 1, -1)))
    dv2 = _dv_mod11(nums[:10], list(range(11, 1, -1)))
    return nums[9] == dv1 and nums[10] == dv2


def normalizar_cnpj(cnpj: str | None) -> str:
    """Tira máscara e põe em maiúsculas (aceita o CNPJ alfanumérico)."""
    return re.sub(r"[^0-9A-Z]", "", (cnpj or "").upper())


def cnpj_valido(cnpj: str) -> bool:
    c = normalizar_cnpj(cnpj)
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", c) or c == c[0] * 14:
        return False
    valores = [ord(ch) - 48 for ch in c]
    dv1 = _dv_mod11(valores[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    dv2 = _dv_mod11(valores[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return valores[12] == dv1 and valores[13] == dv2


def validar_cpf(value):
    if _vazio(value):
        return None
    if not cpf_valido(str(value)):
        raise ValueError("CPF inválido")
    return only_digits(str(value))


def validar_cnpj(value):
    if _vazio(value):
        return None
    if not cnpj_valido(str(value)):
        raise ValueError("CNPJ inválido")
    return normalizar_cnpj(str(value))


def validar_cpf_cnpj(value):
    """Campo que aceita os dois: 11 dígitos = CPF; senão, CNPJ."""
    if _vazio(value):
        return None
    norm = normalizar_cnpj(str(value))
    if len(norm) == 11 and norm.isdigit():
        return validar_cpf(norm)
    if len(norm) == 14:
        return validar_cnpj(norm)
    raise ValueError("CPF/CNPJ inválido: informe 11 dígitos (CPF) ou 14 caracteres (CNPJ)")


def validar_documento(person_type: str, value) -> str:
    """CPF para pessoa física (PF), CNPJ para pessoa jurídica (PJ)."""
    if person_type == "PF":
        doc = validar_cpf(value)
    else:
        doc = validar_cnpj(value)
    if not doc:
        raise ValueError("Informe o CPF" if person_type == "PF" else "Informe o CNPJ")
    return doc


def validar_cep(value):
    if _vazio(value):
        return None
    d = only_digits(str(value))
    if len(d) != 8 or d == "00000000":
        raise ValueError("CEP inválido: informe os 8 dígitos")
    return d


def validar_uf(value):
    if _vazio(value):
        return None
    uf = str(value).strip().upper()
    if uf not in UFS:
        raise ValueError("UF inválida")
    return uf


def _telefone(value, *, fixo: bool, celular: bool):
    if _vazio(value):
        return None
    d = only_digits(str(value))
    if d.startswith("0") and len(d) in (11, 12):  # "0 11 ..." (prefixo de longa distância)
        d = d[1:]
    if len(d) not in (10, 11) or int(d[:2]) not in DDDS:
        raise ValueError("Telefone inválido: informe DDD + número")
    eh_celular = len(d) == 11 and d[2] == "9"
    eh_fixo = len(d) == 10 and d[2] in "2345"
    if celular and fixo:
        if not (eh_celular or eh_fixo):
            raise ValueError("Telefone inválido: fixo tem 8 dígitos (começa com 2 a 5) e celular 9 (começa com 9)")
    elif celular and not eh_celular:
        raise ValueError("Celular inválido: DDD + 9 dígitos começando com 9")
    elif fixo and not eh_fixo:
        raise ValueError("Telefone fixo inválido: DDD + 8 dígitos começando com 2 a 5")
    return d


Cpf = Annotated[str | None, BeforeValidator(validar_cpf)]
Cnpj = Annotated[str | None, BeforeValidator(validar_cnpj)]
CpfCnpj = Annotated[str | None, BeforeValidator(validar_cpf_cnpj)]
Cep = Annotated[str | None, BeforeValidator(validar_cep)]
Uf = Annotated[str | None, BeforeValidator(validar_uf)]
TelefoneFixo = Annotated[str | None, BeforeValidator(lambda v: _telefone(v, fixo=True, celular=False))]
TelefoneCelular = Annotated[str | None, BeforeValidator(lambda v: _telefone(v, fixo=False, celular=True))]
Telefone = Annotated[str | None, BeforeValidator(lambda v: _telefone(v, fixo=True, celular=True))]
def validar_somente_digitos(value):
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"\d+", value):
            raise ValueError("Use só números")
    return value


SomenteDigitos = Annotated[str, BeforeValidator(validar_somente_digitos)]


def aplicar(model, regras: dict[str, tuple[str, object]]):
    """Valida e normaliza campos de um modelo Pydantic já montado (usar num
    `model_validator(mode="after")`). `regras` = {campo: (rótulo, função)};
    o erro sai com o rótulo na frente ("CEP do destinatário: CEP inválido...").
    Fica fora da declaração dos campos de propósito: os schemas de saída que
    herdam dos de entrada não revalidam dado antigo do banco."""
    for campo, (rotulo, funcao) in regras.items():
        try:
            setattr(model, campo, funcao(getattr(model, campo)))
        except ValueError as exc:
            raise ValueError(f"{rotulo}: {exc}") from None
    return model


def telefone(value):
    return _telefone(value, fixo=True, celular=True)


def telefone_fixo(value):
    return _telefone(value, fixo=True, celular=False)


def telefone_celular(value):
    return _telefone(value, fixo=False, celular=True)


def cep_obrigatorio(value):
    cep = validar_cep(value)
    if not cep:
        raise ValueError("informe o CEP")
    return cep
