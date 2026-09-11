"""Uso único: rode dentro da venv, na pasta do projeto (onde está o .env):

    cd C:\\BigPost
    .venv\\Scripts\\activate
    python reset_master.py

1) Lista todos os usuários internos (tabela `users`) — username, e-mail,
   papel, ativo/bloqueado — pra sabermos o que existe de verdade no banco.
2) Se existir pelo menos um usuário com papel Master, reseta a senha dele
   para o valor definido em NOVA_SENHA abaixo, e também zera o bloqueio
   (failed_attempts=0, locked=False) e reativa (active=True), caso esteja
   travado por tentativas erradas.
3) Se não existir NENHUM usuário Master, cria um novo com o username/senha
   definidos abaixo.

Depois de confirmar que o login funciona, pode apagar este arquivo — ele
não faz parte do sistema, é só uma ferramenta de recuperação pontual.
"""

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.models import User

NOVA_SENHA = "BigPost@2026"  # troque aqui se quiser outra senha antes de rodar

db = SessionLocal()
try:
    users = db.query(User).all()
    print(f"\n{len(users)} usuário(s) encontrado(s) na tabela users:")
    for u in users:
        print(f"  id={u.id} username={u.username!r} email={u.email!r} role={u.role} "
              f"active={u.active} locked={u.locked} failed_attempts={u.failed_attempts}")

    masters = [u for u in users if u.role == "Master"]

    if masters:
        for m in masters:
            m.password_hash = hash_password(NOVA_SENHA)
            m.failed_attempts = 0
            m.locked = False
            m.active = True
        db.commit()
        print(f"\nSenha resetada para {len(masters)} usuário(s) Master. Use um destes logins:")
        for m in masters:
            print(f"  usuário: {m.username}   senha: {NOVA_SENHA}")
    else:
        novo = User(
            username="master",
            email=None,
            full_name="Administrador Master",
            role="Master",
            password_hash=hash_password(NOVA_SENHA),
            active=True,
        )
        db.add(novo)
        db.commit()
        print(f"\nNenhum Master existia — criei um novo:")
        print(f"  usuário: master   senha: {NOVA_SENHA}")
finally:
    db.close()
