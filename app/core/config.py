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

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
