"""Configuração da aplicação, lida do ambiente (.env).

Mantemos aqui apenas o que é configuração de *infraestrutura* (onde está o banco,
segredo do JWT, etc). Parâmetros de *negócio* que podem mudar com frequência
(dias de tolerância, limites, textos, taxas padrão) NÃO ficam aqui — ficam na
tabela `system_parameters`, editável em runtime pelo Master sem precisar
reiniciar/reimplantar a aplicação. Ver app/services/params.py.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://bigpost:bigpost@localhost:5432/bigpost"

    jwt_secret: str = "troque-esta-chave-em-producao"
    jwt_expire_minutes: int = 480
    jwt_algorithm: str = "HS256"

    bootstrap_master_username: str = "Fifo"
    bootstrap_master_password: str = "troque-esta-senha"
    # Opcional — se vazio, a conta Master de bootstrap fica sem e-mail (ainda
    # loga normalmente pelo username, já que o login aceita username OU
    # e-mail — ver app/api/auth.py). Preencher deixa essa conta também apta
    # a usar "Esqueci minha senha"/redefinição por e-mail, igual às contas
    # novas (que desde 2026-09-10 são sempre cadastradas por e-mail).
    bootstrap_master_email: str = ""

    data_dir: str = "./data"

    # Deixe True em produção (exige HTTPS). Em dev local via http://, defina
    # COOKIE_SECURE=false no .env para conseguir logar pelo navegador.
    cookie_secure: bool = True

    # Segredo compartilhado que o Painel Master (sistema externo, fora deste
    # projeto) usa para chamar a API de integração deste BigPost (cabeçalho
    # X-API-Key) quando cadastra um licenciado ou emite uma licença por lá.
    # Vazio = integração desligada (endpoints respondem 401 sempre). Ver
    # app/api/integrations_painel_master.py.
    painel_master_api_key: str = ""

    # Base da API oficial dos Correios para sistemas integrados (CWS —
    # Correios Web Services), usada pela aferição/postagem do módulo Operador
    # (ver app/services/correios_cws.py). Comece em homologação e só troque
    # para produção depois de validar o fluxo — pré-postagem em produção gera
    # rastreio/etiqueta reais.
    #   Homologação (padrão): https://cwshom.correios.com.br
    #   Produção:              https://cws.correios.com.br
    correios_cws_base_url: str = "https://cwshom.correios.com.br"

    # SMTP para o e-mail automático que o Portal SAC dispara pro cliente
    # quando uma encomenda cai na fila de erro (ver app/services/email.py).
    # smtp_host vazio = envio de e-mail desligado (a encomenda ainda vai pra
    # fila do SAC normalmente — só o aviso por e-mail não sai — e nada
    # quebra: nunca lance exceção por falta de config aqui, mesmo padrão do
    # painel_master_api_key acima).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from_email: str = ""
    smtp_from_name: str = "BigPost"

    # URL pública (raiz, sem barra no fim) onde o BigPost responde — usada só
    # pra montar o link de "definir senha" (convite/redefinição) mandado por
    # e-mail, ex.: "https://bigpost.onrender.com". Vazio = o e-mail (quando
    # sai) traz o token em texto puro com instrução manual em vez de link
    # clicável — nunca quebra, só fica menos prático até isto ser preenchido.
    app_public_base_url: str = ""

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
