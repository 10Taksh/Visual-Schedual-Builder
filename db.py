from collections.abc import Generator
from contextlib import contextmanager
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


BASE_DIR = Path(__file__).resolve().parent

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    engine_url = DATABASE_URL
else:
    DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "schedule.db"))
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine_url = f"sqlite:///{DATABASE_PATH}"

engine_kwargs = {}
if engine_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(engine_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
