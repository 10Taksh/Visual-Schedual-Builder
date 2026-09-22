"""Store-wide settings: operating hours and the unpaid-break rule, stored as one row."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.constants import BREAK_DURATION_MINUTES, BREAK_THRESHOLD_MINUTES, DAYS_OF_WEEK, DEFAULT_OPERATING_HOURS
from app.models import StoreSettings
from app.services.errors import ApiError
from app.services.times import format_time, parse_time

SETTINGS_ROW_ID = 1
MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class BreakRule:
    threshold_minutes: int = BREAK_THRESHOLD_MINUTES
    duration_minutes: int = BREAK_DURATION_MINUTES

    def minutes_for(self, shift_minutes: int) -> int:
        """Unpaid break deducted from a shift of the given length."""
        if self.threshold_minutes <= 0 or self.duration_minutes <= 0:
            return 0
        return self.duration_minutes if shift_minutes >= self.threshold_minutes else 0


def get_settings_row(session: Session) -> StoreSettings | None:
    return session.get(StoreSettings, SETTINGS_ROW_ID)


def get_operating_hours(session: Session) -> dict:
    settings = get_settings_row(session)
    return settings.operating_hours if settings else dict(DEFAULT_OPERATING_HOURS)


def get_break_rule(session: Session) -> BreakRule:
    settings = get_settings_row(session)
    if settings is None:
        return BreakRule()
    return BreakRule(settings.break_threshold_minutes, settings.break_duration_minutes)


def settings_to_dict(session: Session) -> dict:
    rule = get_break_rule(session)
    return {
        "operating_hours": get_operating_hours(session),
        "break_threshold_minutes": rule.threshold_minutes,
        "break_duration_minutes": rule.duration_minutes,
    }


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


def _minutes(value: object, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise ApiError(f"{label} must be a whole number of minutes")
    value = int(value)
    if not 0 <= value <= maximum:
        raise ApiError(f"{label} must be between 0 and {maximum} minutes")
    return value


def validate_break_rule(threshold: object, duration: object) -> BreakRule:
    rule = BreakRule(
        _minutes(threshold, "Break threshold", MINUTES_PER_DAY),
        _minutes(duration, "Break duration", 4 * 60),
    )
    if rule.threshold_minutes and rule.duration_minutes >= rule.threshold_minutes:
        raise ApiError("Break duration must be shorter than the shift length that earns it")
    return rule


def update_settings(session: Session, payload: object) -> dict:
    """Update whichever settings the payload carries.

    Accepts ``{"operating_hours": {...}, "break_threshold_minutes": n, "break_duration_minutes": n}``
    with any subset of keys. A bare ``{Monday: ..., Tuesday: ...}`` object (the original API
    shape) is still accepted as operating hours.
    """
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object")
    settings = get_settings_row(session)
    if settings is None:
        settings = StoreSettings(id=SETTINGS_ROW_ID, operating_hours=dict(DEFAULT_OPERATING_HOURS))
        session.add(settings)

    if "operating_hours" in payload:
        settings.operating_hours = validate_operating_hours(payload["operating_hours"])
    elif any(day in payload for day in DAYS_OF_WEEK):
        settings.operating_hours = validate_operating_hours(payload)

    if "break_threshold_minutes" in payload or "break_duration_minutes" in payload:
        rule = validate_break_rule(
            payload.get("break_threshold_minutes", settings.break_threshold_minutes),
            payload.get("break_duration_minutes", settings.break_duration_minutes),
        )
        settings.break_threshold_minutes = rule.threshold_minutes
        settings.break_duration_minutes = rule.duration_minutes

    session.flush()
    return settings_to_dict(session)
