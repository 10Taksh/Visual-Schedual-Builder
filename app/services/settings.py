"""Store-wide settings. Today that is operating hours, stored as one JSON row."""

from sqlalchemy.orm import Session

from app.constants import DAYS_OF_WEEK, DEFAULT_OPERATING_HOURS
from app.models import StoreSettings
from app.services.errors import ApiError
from app.services.times import format_time, parse_time

SETTINGS_ROW_ID = 1


def get_operating_hours(session: Session) -> dict:
    settings = session.get(StoreSettings, SETTINGS_ROW_ID)
    return settings.operating_hours if settings else dict(DEFAULT_OPERATING_HOURS)


def validate_operating_hours(value: object) -> dict:
    """Return ``{day: {"open": "HH:MM", "close": "HH:MM"} | None}`` for every day, or raise ApiError."""
    if not isinstance(value, dict):
        raise ApiError("Operating hours must be an object with one entry per day")
    result: dict[str, dict | None] = {}
    for day in DAYS_OF_WEEK:
        day_value = value.get(day)
        if day_value in (None, "closed", "Closed"):
            result[day] = None
            continue
        if not isinstance(day_value, dict):
            raise ApiError(f"Operating hours for {day} are invalid")
        opening, closing = parse_time(day_value.get("open")), parse_time(day_value.get("close"))
        if opening is None or closing is None or closing <= opening:
            raise ApiError(f"Operating hours for {day} must have a valid open and close time")
        result[day] = {"open": format_time(opening), "close": format_time(closing)}
    return result


def update_operating_hours(session: Session, value: object) -> dict:
    hours = validate_operating_hours(value)
    settings = session.get(StoreSettings, SETTINGS_ROW_ID)
    if settings is None:
        session.add(StoreSettings(id=SETTINGS_ROW_ID, operating_hours=hours))
    else:
        settings.operating_hours = hours
    session.flush()
    return hours
