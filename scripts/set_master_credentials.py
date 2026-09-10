"""DESCONTINUADO — não rode este script.

Existia aqui uma versão anterior que editava a linha do usuário Master
direto no banco (fora da aplicação). Depois da premissa combinada com o
usuário em 2026-09-10 — "sempre que houver alteração, nunca mexeremos no
banco de dados" (leia-se: nada de UPDATE/DELETE/script manual tocando dados
direto; mudança de estrutura via migration do Alembic, que roda sozinha no
deploy, continua normal) — isso deixou de ser aceitável.

Pra trocar (ou criar) o usuário Master, use a própria aplicação, sem tocar
no banco:

  1. Entre no portal Administração (`/`) com QUALQUER usuário Master que já
     funcione hoje.
  2. Aba "Usuários" → cadastre um novo usuário com o login/senha desejados e
     perfil "Master" (`POST /api/v1/users`, já exige o próprio papel Master
     pra chamar — ver app/api/users.py::create_user).
  3. Pronto — o login novo já funciona. O usuário Master antigo continua
     existindo (não há endpoint de desativar usuário interno hoje); se
     quiser, pode trocar a senha dele por algo aleatório com "Zerar Senha"
     pela mesma tela, só pra ele parar de ser usado.

Se, no dia da primeira instalação (banco `users` ainda vazio), quiser que o
Master já suba com um login específico, isso é feito só editando
`BOOTSTRAP_MASTER_USERNAME`/`BOOTSTRAP_MASTER_PASSWORD` no `.env` ANTES da
primeira subida do servidor (`bootstrap()` em app/main.py cria o Master só
quando a tabela está vazia) — de novo, sem precisar de script.
"""

raise SystemExit(
    "Este script foi descontinuado — veja as instruções no topo do arquivo "
    "para trocar o usuário Master pela própria aplicação, sem editar o banco na mão."
)
