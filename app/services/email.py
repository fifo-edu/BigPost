"""Envio de e-mail — usado hoje só pelo aviso automático do Portal SAC pro
cliente quando uma encomenda cai na fila de erro (ver app/api/shipments_sac.py).

Só biblioteca padrão do Python (smtplib/email), sem dependência nova. Segue o
mesmo padrão de "desligado por padrão, nunca quebra a requisição" usado em
app/api/deps.py::require_painel_master_key: se SMTP_HOST não estiver
configurado no .env, `send_email` simplesmente não faz nada (loga e retorna
False) — quem chama decide o que fazer com o retorno (aqui, só deixa
`error_notified_at` em branco), nunca deixa a ação principal (carimbar o
erro) falhar por causa do e-mail.
"""
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("bigpost")


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def send_email(to: str, subject: str, body: str) -> bool:
    """Retorna True se o e-mail foi (aparentemente) entregue ao servidor
    SMTP. Nunca levanta exceção — falha de e-mail não pode derrubar a
    requisição que a originou (ex.: carimbar uma encomenda como erro tem que
    funcionar mesmo se o SMTP estiver fora do ar)."""
    if not is_configured():
        logger.info("E-mail não enviado (SMTP não configurado): para=%s assunto=%s", to, subject)
        return False
    if not to:
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>" if settings.smtp_from_name else settings.smtp_from_email
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Falha ao enviar e-mail para %s", to)
        return False
