"""Atualiza (ou cria, se não existir nenhum) o usuário Master interno do
BigPost — login do portal Administração (`/`), reaproveitado também pelo
"modo suporte" nos portais Agência/Operador/Cliente.

Por que este script e não só editar o `.env`? `BOOTSTRAP_MASTER_USERNAME`/
`BOOTSTRAP_MASTER_PASSWORD` do `.env` só são usados para *criar* o usuário
Master na primeira subida, quando a tabela `users` está vazia (ver
`bootstrap()` em `app/main.py`). Como este BigPost já tem um usuário Master
no banco, mudar só o `.env` não muda a senha de quem já existe — é preciso
atualizar a linha dele no banco, que é o que este script faz.

Se houver mais de um usuário com papel Master, só o primeiro (menor id) é
atualizado — não dá pra renomear todos para o mesmo login, já que o login
é único.

Rode uma vez, com o venv ativado, na pasta do projeto:

    python scripts\\set_master_credentials.py

Não precisa reiniciar o servidor depois — a mudança já vale na próxima vez
que alguém logar.
"""
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.models import User

NEW_USERNAME = "Fifo"
NEW_PASSWORD = "2010"


def main() -> None:
    db = SessionLocal()
    try:
        master = db.query(User).filter(User.role == "Master").order_by(User.id).first()
        if master:
            print(f"Usuário Master encontrado: '{master.username}' (id={master.id}). Atualizando login/senha...")
            master.username = NEW_USERNAME
            master.password_hash = hash_password(NEW_PASSWORD)
            master.failed_attempts = 0
            master.locked = False
            master.active = True
        else:
            print("Nenhum usuário Master encontrado. Criando um novo...")
            master = User(
                username=NEW_USERNAME,
                full_name="Administrador Master",
                role="Master",
                password_hash=hash_password(NEW_PASSWORD),
                active=True,
            )
            db.add(master)
        db.commit()
        print(f"Pronto. Login: '{NEW_USERNAME}' / Senha: '{NEW_PASSWORD}'.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
