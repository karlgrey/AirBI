from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from airbi.config import settings


class Base(DeclarativeBase):
    """Gemeinsame Declarative-Base für alle ORM-Modelle."""


def make_engine(url: str | None = None) -> Engine:
    """Erzeugt eine SQLAlchemy-Engine. Ohne Argument: produktive DB."""
    return create_engine(url or settings.database_url, future=True)


def make_session_factory(bind) -> sessionmaker:
    """Erzeugt eine Session-Factory, gebunden an Engine oder Connection."""
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)


engine = make_engine()
SessionLocal = make_session_factory(engine)
