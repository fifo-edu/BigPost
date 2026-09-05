"""'Modo suporte': permite que um usuário Master interno (equipe BigPost, a
mesma conta usada pra entrar na Administração) entre nos módulos Agência,
Operador e Cliente de QUALQUER licenciado já sincronizado do Painel Master,
sem precisar saber o "Código do licenciado (ID)" nem ter uma conta própria
cadastrada naquela agência.

Como funciona (ver app/api/auth_support.py pro fluxo completo):
1. Na tela de login de um dos 3 portais, a pessoa escolhe "Entrar com usuário
   master" e informa usuário+senha do BigPost (mesma conta da Administração,
   perfil Master) — validado contra a tabela `users`, NÃO contra um valor
   fixo lido do .env a cada vez (assim continua funcionando mesmo depois de
   trocar a senha pela tela de Usuários, e qualquer Master pode usar, não só
   o Master de bootstrap).
2. O backend devolve a lista de licenciados (a mesma que já veio do Painel
   Master) pra escolher qual acessar.
3. Ao escolher, entra automaticamente naquele licenciado com acesso total —
   sem digitar senha de novo.

Para o módulo Agência/Operador (tabela LicenseeUser) e o módulo Cliente
(tabela Client), este acesso precisa de uma linha real na respectiva tabela
pra reaproveitar 100% das dependências de autenticação/autorização já
existentes (get_current_licensee_user / get_current_client) — por isso,
criamos (uma vez só, sob demanda) uma conta técnica reservada por licenciado,
identificada pelo username fixo abaixo. Essa conta:
- Fica com perfil Master (LicenseeUser) — acesso total ao módulo Agência e
  Operador daquele licenciado.
- NUNCA aparece nas telas normais (Usuários da agência, Clientes) — as
  listagens excluem explicitamente esse username. Ver o filtro em
  app/api/licensee_users.py e app/api/clients.py.
- Tem uma senha aleatória que nunca é usada/exibida — o login real acontece
  via /api/v1/auth/support/enter, que já emite a sessão direto, sem
  conferir essa senha."""
import secrets

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.models import Client, LicenseeUser

SUPPORT_USERNAME = "_suporte_bigpost"
SUPPORT_FULL_NAME = "Acesso de suporte BigPost (login com usuário master)"


def get_or_create_support_licensee_user(db: Session, licensee_id: int) -> LicenseeUser:
    lu = (
        db.query(LicenseeUser)
        .filter(LicenseeUser.licensee_id == licensee_id, LicenseeUser.username == SUPPORT_USERNAME)
        .first()
    )
    if lu:
        if not lu.active or lu.locked:
            lu.active = True
            lu.locked = False
            lu.failed_attempts = 0
            db.commit()
            db.refresh(lu)
        return lu
    lu = LicenseeUser(
        licensee_id=licensee_id,
        username=SUPPORT_USERNAME,
        full_name=SUPPORT_FULL_NAME,
        role="Master",
        password_hash=hash_password(secrets.token_urlsafe(32)),
        active=True,
        created_by="suporte-master",
    )
    db.add(lu)
    db.commit()
    db.refresh(lu)
    return lu


def get_or_create_support_client(db: Session, licensee_id: int) -> Client:
    client = (
        db.query(Client)
        .filter(Client.licensee_id == licensee_id, Client.username == SUPPORT_USERNAME)
        .first()
    )
    if client:
        if not client.active:
            client.active = True
            db.commit()
            db.refresh(client)
        return client
    client = Client(
        licensee_id=licensee_id,
        person_type="PJ",
        legal_name=SUPPORT_FULL_NAME,
        tax_id="00000000000000",
        username=SUPPORT_USERNAME,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        active=True,
        created_by="suporte-master",
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client
