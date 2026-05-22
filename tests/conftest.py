import pytest

from airbi.config import settings
from airbi.db import models  # noqa: F401  -- Modelle registrieren bei Base.metadata
from airbi.db.session import Base, make_engine, make_session_factory


@pytest.fixture(scope="session")
def engine():
    """Engine gegen die Test-DB; Schema einmal pro Testlauf neu aufbauen."""
    eng = make_engine(settings.test_database_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """Session mit Transaktions-Rollback nach jedem Test — keine Testdaten bleiben."""
    connection = engine.connect()
    transaction = connection.begin()
    session = make_session_factory(connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
