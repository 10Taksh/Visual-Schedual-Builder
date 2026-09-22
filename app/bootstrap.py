"""Startup tasks: create tables, patch older schemas, seed defaults, tidy stored data."""

import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine

from app.constants import BREAK_DURATION_MINUTES, BREAK_THRESHOLD_MINUTES, DEFAULT_OPERATING_HOURS, DEFAULT_POSITIONS
from app.db import session_scope
from app.models import Base, Employee, Position, StoreSettings
from app.services.availability import normalize_availability
from app.services.settings import SETTINGS_ROW_ID

log = logging.getLogger(__name__)

# Columns added after the first release. ``create_all`` never alters existing
# tables, so databases created before these existed are patched by hand.
_ADDED_COLUMNS = {
    "positions": {
        "label": "VARCHAR(60)",
        "color": "VARCHAR(7) NOT NULL DEFAULT '#53685D'",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
    },
    "store_settings": {
        "break_threshold_minutes": f"INTEGER NOT NULL DEFAULT {BREAK_THRESHOLD_MINUTES}",
        "break_duration_minutes": f"INTEGER NOT NULL DEFAULT {BREAK_DURATION_MINUTES}",
    },
}


def ensure_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    log.info("Added column %s.%s", table, name)


def seed_defaults() -> None:
    with session_scope() as session:
        existing = {position.name: position for position in session.scalars(select(Position))}
        for defaults in DEFAULT_POSITIONS:
            position = existing.get(defaults["name"])
            if position is None:
                session.add(Position(**defaults))
            elif position.sort_order == 0:
                # Row predates the metadata columns; fill them in once.
                position.label, position.color, position.sort_order = defaults["label"], defaults["color"], defaults["sort_order"]
        if session.get(StoreSettings, SETTINGS_ROW_ID) is None:
            session.add(StoreSettings(id=SETTINGS_ROW_ID, operating_hours=dict(DEFAULT_OPERATING_HOURS)))


def normalize_stored_availability() -> None:
    """Rewrite availability saved before validation existed into canonical form."""
    with session_scope() as session:
        for employee in session.scalars(select(Employee)):
            try:
                canonical = normalize_availability(employee.availability)
            except ValueError:
                log.warning("Employee %s had unreadable availability %r; treating as Open", employee.id, employee.availability)
                canonical = "Open"
            if canonical != employee.availability:
                employee.availability = canonical


def bootstrap(engine: Engine) -> None:
    ensure_schema(engine)
    seed_defaults()
    normalize_stored_availability()
