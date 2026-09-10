"""Tokens de convite (1º acesso) e redefinição ("esqueci minha senha") de
senha — mesmo mecanismo pros 3 tipos de conta (User, LicenseeUser, Client).
O token em texto puro só existe no e-mail enviado (ou, se o e-mail não sair,
na resposta da própria ação administrativa que gerou o convite/redefinição —
ver `issue_and_notify` abaixo); o banco guarda só o hash, e cada token só
pode ser usado uma vez. Ver também app/api/auth_password.py."""
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.models import PasswordSetToken
from app.services.email import send_email

INVITE_TTL_HOURS = 7 * 24
RESET_TTL_HOURS = 2


def create_token(db: Session, actor_type: str, actor_id: int, purpose: str) -> str:
    raw = secrets.token_urlsafe(32)
    ttl = INVITE_TTL_HOURS if purpose == "invite" else RESET_TTL_HOURS
    db.add(
        PasswordSetToken(
            actor_type=actor_type,
            actor_id=actor_id,
            token_hash=hash_password(raw),
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(hours=ttl),
        )
    )
    db.commit()
    return raw


def consume_token(db: Session, raw_token: str) -> PasswordSetToken | None:
    """Varre os tokens ainda válidos (não usados, não expirados) e confere o
    hash de cada um — não dá pra fazer isso com WHERE token_hash=... porque o
    hash tem salt (mesmo padrão de verify_api_key). Em escala pequena (uma
    agência) isso é barato; se o volume de convites/redefinições crescer
    muito, vale trocar por um índice determinístico (ex.: HMAC sem salt) em
    vez de hash com salt. Marca como usado e retorna a linha se bater; None
    se não achar nenhum válido (expirado, já usado, ou simplesmente errado)."""
    candidates = (
        db.query(PasswordSetToken)
        .filter(PasswordSetToken.used_at.is_(None), PasswordSetToken.expires_at > datetime.utcnow())
        .all()
    )
    for candidate in candidates:
        if verify_password(raw_token, candidate.token_hash):
            candidate.used_at = datetime.utcnow()
            db.commit()
            return candidate
    return None


def build_set_password_url(token: str) -> str:
    if settings.app_public_base_url:
        return f"{settings.app_public_base_url.rstrip('/')}/set-password.html?token={token}"
    return f"(SEM LINK — app_public_base_url não configurado. Peça pra pessoa colar este código na tela 'Definir senha': {token})"


def _email_copy(purpose: str, name: str, link: str) -> tuple[str, str]:
    if purpose == "invite":
        return (
            "Bem-vindo ao BigPost — defina sua senha",
            f"Olá, {name}.\n\n"
            "Você foi cadastrado no BigPost. Para acessar, defina sua senha (6 a 15 caracteres, com pelo "
            f"menos uma letra maiúscula, uma minúscula e um número) em:\n\n{link}\n\n"
            "Este link expira em 7 dias.",
        )
    return (
        "BigPost — Redefinição de senha",
        f"Olá, {name}.\n\n"
        f"Para definir uma nova senha, acesse:\n\n{link}\n\n"
        "Se você não pediu isso, é só ignorar este e-mail — o link expira em algumas horas.",
    )


def notify_reset_without_link(db: Session, actor_type: str, actor_id: int, to_email: str, name: str) -> None:
    """Como issue_and_notify, mas NUNCA devolve o link pra quem chamou — só
    usado pelo "Esqueci minha senha" público (app/api/auth_password.py), que
    por segurança contra enumeração de contas não pode revelar se o e-mail
    existe nem vazar o token pra quem não é o dono da conta."""
    token = create_token(db, actor_type, actor_id, "reset")
    link = build_set_password_url(token)
    subject, body = _email_copy("reset", name, link)
    send_email(to_email, subject, body)


def issue_and_notify(
    db: Session, actor_type: str, actor_id: int, purpose: str, to_email: str | None, name: str
) -> tuple[str, bool]:
    """Gera o token, tenta mandar o e-mail e SEMPRE devolve o link também —
    quem chama isto é sempre uma ação administrativa autenticada (cadastrar
    usuário, "Zerar Senha"), nunca o "Esqueci minha senha" público (esse usa
    create_token direto, sem devolver o link na resposta — ver
    app/api/auth_password.py, por segurança contra enumeração de contas).
    Devolver o link aqui é o que mantém o cadastro/redefinição utilizável
    mesmo sem SMTP configurado: quem cadastrou copia e manda manualmente."""
    token = create_token(db, actor_type, actor_id, purpose)
    link = build_set_password_url(token)
    if not to_email:
        return link, False
    subject, body = _email_copy(purpose, name, link)
    emailed = send_email(to_email, subject, body)
    return link, emailed
