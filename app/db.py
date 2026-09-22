"""Engine and session management.

The engine is created once per process by ``init_engine`` (called from
``create_app``) so tests can point the same code at an in-memory database.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None

_IN_MEMORY_URLS = ("sqlite://", "sqlite:///:memory:")


def normalize_database_url(url: str) -> str:
    """Map hosting-provider URLs onto the installed psycopg 3 driver.

    Render, Heroku and friends hand out ``postgres://`` or ``postgresql://``,
    both of which SQLAlchemy routes to psycopg2. Only psycopg 3 is installed.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def init_engine(url: str) -> Engine:
    global engine, SessionLocal
    url = normalize_database_url(url)
    kwargs: dict = {}
    if url.startswith("sqlite"):
        # timeout: wait for a writer to finish instead of failing with "database is locked"
        # when several gunicorn threads save at once.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if url in _IN_MEMORY_URLS:
            # Every connection must see the same in-memory database.
            kwargs["poolclass"] = StaticPool
        else:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["pool_pre_ping"] = True

    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    # SQLite ignores ON DELETE CASCADE unless this pragma is set per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Commit on success, roll back on any exception, always close."""
    if SessionLocal is None:
        raise RuntimeError("init_engine() must run before opening a session")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
