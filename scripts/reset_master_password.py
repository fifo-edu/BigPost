"""Recuperação pontual do login Master (banco local).

Uso, na pasta do projeto (onde está o .env), com a venv ativa:

    python scripts/reset_master_password.py --username Fifo

A nova senha é pedida no terminal (não aparece na tela e não fica salva em
arquivo nenhum). O script:

1) Lista os usuários internos (tabela `users`).
2) Se o usuário informado existir, troca a senha, zera o bloqueio
   (failed_attempts=0, locked=False), reativa (active=True) e garante
   o papel Master.
3) Se não existir, cria um novo usuário Master com esse username.

Atenção: isto edita o banco diretamente — exceção à regra "nunca mexer no
banco na mão", só para recuperar acesso quando nenhum Master consegue entrar.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.models import User  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Reseta (ou cria) a senha de um usuário Master.")
    parser.add_argument("--username", required=True, help="login do usuário Master")
    args = parser.parse_args()

    senha = getpass.getpass("Nova senha: ")
    if not senha:
        raise SystemExit("Senha vazia — nada foi alterado.")
    if senha != getpass.getpass("Confirme a nova senha: "):
        raise SystemExit("As senhas não conferem — nada foi alterado.")

    db = SessionLocal()
    try:
        users = db.query(User).all()
        print(f"\n{len(users)} usuário(s) na tabela users:")
        for u in users:
            print(f"  id={u.id} username={u.username!r} email={u.email!r} role={u.role} "
                  f"active={u.active} locked={u.locked} failed_attempts={u.failed_attempts}")

        user = db.query(User).filter(User.username == args.username).one_or_none()
        if user:
            user.password_hash = hash_password(senha)
            user.failed_attempts = 0
            user.locked = False
            user.active = True
            user.role = "Master"
            acao = "Senha resetada"
        else:
            db.add(User(
                username=args.username,
                email=None,
                full_name="Administrador Master",
                role="Master",
                password_hash=hash_password(senha),
                active=True,
            ))
            acao = "Usuário Master criado"
        db.commit()
        print(f"\n{acao}: {args.username}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
