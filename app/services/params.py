"""Parametrizações de negócio editáveis em runtime (sem deploy).

Qualquer valor que tende a mudar por decisão de negócio (não de infra) deve
viver aqui: dias de tolerância de licença expirada, texto de aviso, taxa
padrão, etc. Guardado como JSON em `system_parameters`, com valores padrão
que são semeados na primeira execução (ver seed_defaults) mas que o Master
pode alterar a qualquer momento pela API/tela de Parâmetros sem precisar de
uma nova versão do código.
"""
from sqlalchemy.orm import Session

from app.models.models import SystemParameter

DEFAULTS: dict[str, dict] = {
    "license.grace_period_days": {
        "value": 7,
        "description": "Dias de tolerância após o vencimento de uma licença antes de bloquear o app cliente.",
    },
    "license.heartbeat_max_gap_hours": {
        "value": 72,
        "description": "Horas sem heartbeat de uma instalação antes de marcá-la como inativa.",
    },
    "billing.default_due_day": {
        "value": 10,
        "description": "Dia de vencimento padrão sugerido ao cadastrar um novo licenciado.",
    },
    "security.login_max_attempts": {
        "value": 5,
        "description": "Tentativas de login incorretas permitidas antes de exigir espera.",
    },
}


def seed_defaults(db: Session) -> None:
    existing = {p.key for p in db.query(SystemParameter.key).all()}
    for key, cfg in DEFAULTS.items():
        if key in existing:
            continue
        db.add(SystemParameter(key=key, value={"v": cfg["value"]}, description=cfg["description"]))
    db.commit()


def get_param(db: Session, key: str, default=None):
    row = db.query(SystemParameter).filter(SystemParameter.key == key).first()
    if not row:
        return default
    return row.value.get("v", default)


def set_param(db: Session, key: str, value, updated_by: str, description: str | None = None) -> SystemParameter:
    row = db.query(SystemParameter).filter(SystemParameter.key == key).first()
    if not row:
        row = SystemParameter(key=key, value={"v": value}, description=description)
        db.add(row)
    else:
        row.value = {"v": value}
        row.updated_by = updated_by
        if description:
            row.description = description
    db.commit()
    db.refresh(row)
    return row
