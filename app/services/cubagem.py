"""Peso cubado (cúbico) da aferição — regra dos Correios para encomendas
nacionais: peso cúbico = C x L x A (cm) / divisor. Se o peso cúbico passar do
limite mínimo, o peso tarifado é o maior entre o real e o cúbico; abaixo do
limite vale só o peso real. Divisor e limite são parâmetros de negócio
(app/services/params.py), ajustáveis sem deploy se o Correios mudar a regra
ou o contrato da agência tiver condição própria."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.params import get_param

DEFAULT_DIVISOR = 6000
DEFAULT_MIN_CUBED_KG = 5.0


@dataclass
class Cubagem:
    cubed_weight_kg: float | None
    billable_weight_kg: float


def calcular(
    weight_kg: float,
    length_cm: float | None,
    width_cm: float | None,
    height_cm: float | None,
    *,
    divisor: float = DEFAULT_DIVISOR,
    min_cubed_kg: float = DEFAULT_MIN_CUBED_KG,
) -> Cubagem:
    if not (length_cm and width_cm and height_cm):
        return Cubagem(cubed_weight_kg=None, billable_weight_kg=round(weight_kg, 3))
    cubed = round(length_cm * width_cm * height_cm / divisor, 3)
    billable = max(weight_kg, cubed) if cubed > min_cubed_kg else weight_kg
    return Cubagem(cubed_weight_kg=cubed, billable_weight_kg=round(billable, 3))


def calcular_com_params(
    db: Session, weight_kg: float, length_cm: float | None, width_cm: float | None, height_cm: float | None
) -> Cubagem:
    return calcular(
        weight_kg,
        length_cm,
        width_cm,
        height_cm,
        divisor=float(get_param(db, "afericao.cubagem_divisor", DEFAULT_DIVISOR)),
        min_cubed_kg=float(get_param(db, "afericao.cubagem_min_kg", DEFAULT_MIN_CUBED_KG)),
    )
