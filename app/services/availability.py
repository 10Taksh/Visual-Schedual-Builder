"""Employee availability: validation, canonical storage form, and lookups.

Canonical form is the string ``"Open"``, or a dict holding only the
restricted days::

    {"Monday": "Unavailable", "Sunday": ["09:00-13:00", "17:00-21:00"]}

Reading is deliberately lenient (older rows may hold ``{"Monday": "09:00-17:00"}``);
writing always goes through ``normalize_availability`` so nothing ambiguous is stored.
"""

import json
import re

from app.constants import DAYS_OF_WEEK
from app.services.times import format_time, minutes_since_midnight, parse_time

TIME_RANGE_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$")
OPEN_WORDS = {"", "open"}
UNAVAILABLE_WORDS = {"unavailable", "closed", "none", "off"}

Interval = tuple[int, int]  # minutes since midnight, [start, end)


def _is_open_word(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in OPEN_WORDS)


def _is_unavailable_word(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in UNAVAILABLE_WORDS


def normalize_time_range(value: object) -> str:
    """Return a canonical ``HH:MM-HH:MM`` string or raise ValueError."""
    if isinstance(value, dict):
        start_value, end_value = value.get("start"), value.get("end")
    elif isinstance(value, str):
        match = TIME_RANGE_RE.match(value)
        if match is None:
            raise ValueError(f"'{value}' is not a time range like 09:00-17:00")
        start_value, end_value = match.groups()
    else:
        raise ValueError("Availability ranges must be strings like 09:00-17:00")
    start, end = parse_time(start_value), parse_time(end_value)
    if start is None or end is None or end <= start:
        raise ValueError(f"'{start_value}-{end_value}' is not a valid time range")
    return f"{format_time(start)}-{format_time(end)}"


def normalize_availability(value: object) -> dict | str:
    """Validate availability and return its canonical form, raising ValueError on junk."""
    if _is_open_word(value):
        return "Open"
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError('Availability must be "Open" or JSON such as {"Monday": "09:00-17:00"}') from None
        if _is_open_word(value):
            return "Open"
    if not isinstance(value, dict):
        raise ValueError('Availability must be "Open" or an object keyed by day name')

    result: dict[str, str | list[str]] = {}
    for day, day_value in value.items():
        if day not in DAYS_OF_WEEK:
            raise ValueError(f"'{day}' is not a day of the week")
        if _is_open_word(day_value):
            continue
        if _is_unavailable_word(day_value):
            result[day] = "Unavailable"
            continue
        ranges = day_value if isinstance(day_value, list) else [day_value]
        if not ranges:
            result[day] = "Unavailable"
            continue
        result[day] = [normalize_time_range(item) for item in ranges]
    return result or "Open"


def availability_intervals(availability: object, day: str) -> list[Interval] | None:
    """Intervals the employee can work on ``day``.

    ``None`` means fully open; ``[]`` means unavailable all day.
    """
    if not isinstance(availability, dict):
        return None
    value = availability.get(day)
    if _is_open_word(value):
        return None
    if _is_unavailable_word(value):
        return []
    intervals: list[Interval] = []
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, dict):
            start_value, end_value = item.get("start"), item.get("end")
        elif isinstance(item, str) and (match := TIME_RANGE_RE.match(item)):
            start_value, end_value = match.groups()
        else:
            continue
        start, end = parse_time(start_value), parse_time(end_value)
        if start is not None and end is not None and end > start:
            intervals.append((minutes_since_midnight(start), minutes_since_midnight(end)))
    return intervals


def covers(intervals: list[Interval] | None, start_minutes: int, end_minutes: int) -> bool:
    """True when the whole [start, end) window falls inside one allowed interval."""
    if intervals is None:
        return True
    return any(start_minutes >= window_start and end_minutes <= window_end for window_start, window_end in intervals)
