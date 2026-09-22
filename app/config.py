import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    # DATABASE_URL wins (Render/Railway/etc.); otherwise a SQLite file, relocatable via DATABASE_PATH.
    DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{os.getenv('DATABASE_PATH', BASE_DIR / 'schedule.db')}"
    JSON_SORT_KEYS = False


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    DATABASE_URL = "sqlite://"  # in-memory; see db.init_engine for the shared-pool handling


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def config_from_env() -> type[Config]:
    return CONFIGS.get(os.getenv("FLASK_ENV", "production"), ProductionConfig)
