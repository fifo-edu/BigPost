"""Política de senha, aplicada em todo lugar que uma senha NOVA é definida
(convite de 1º acesso, "esqueci minha senha") — pedido do usuário: 6 a 15
caracteres, com pelo menos um número, uma letra maiúscula e uma minúscula.
Nunca aplicada em login (não se reavalia a senha antiga de uma conta já
existente contra a regra nova)."""
import re

MIN_LENGTH = 6
MAX_LENGTH = 15


def validate_password_strength(password: str) -> None:
    """Levanta ValueError com uma mensagem pronta pra mostrar ao usuário se a
    senha não seguir a política. Quem chama decide como converter isso numa
    resposta HTTP (normalmente HTTPException(400, str(e)))."""
    if not (MIN_LENGTH <= len(password) <= MAX_LENGTH):
        raise ValueError(f"A senha deve ter entre {MIN_LENGTH} e {MAX_LENGTH} caracteres")
    if not re.search(r"[0-9]", password):
        raise ValueError("A senha precisa de pelo menos um número")
    if not re.search(r"[A-Z]", password):
        raise ValueError("A senha precisa de pelo menos uma letra maiúscula")
    if not re.search(r"[a-z]", password):
        raise ValueError("A senha precisa de pelo menos uma letra minúscula")
