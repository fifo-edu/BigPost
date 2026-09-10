from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def normalize_database_url(url: str) -> str:
    """Garante o driver psycopg (v3 — o que este projeto instala e usa,
    `psycopg[binary]` no requirements.txt) mesmo quando a URL de conexão vem
    sem driver explícito, caso da DATABASE_URL que o Render gera sozinho pro
    banco gerenciado ("postgres://..." ou "postgresql://..."). Sem isso, o
    SQLAlchemy cai no driver padrão (psycopg2, não instalado) e a conexão
    falha com "ModuleNotFoundError: No module named 'psycopg2'" — foi
    exatamente o erro do primeiro deploy em produção (2026-09-10). URLs que
    já vêm com driver (ex.: o padrão local "postgresql+psycopg://...") não
    são alteradas.

    Pública (sem "_" na frente) porque `migrations/env.py` também monta sua
    própria engine pra rodar as migrations (fora do ciclo normal da
    aplicação) e precisa da mesma normalização — ver uso lá."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


engine = create_engine(normalize_database_url(settings.database_url), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
