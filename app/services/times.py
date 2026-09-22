"""Clock-time helpers. The API speaks ``HH:MM``; displays use 12-hour."""

from datetime import datetime, time


def parse_time(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


def format_time(value: time) -> str:
    return value.strftime("%H:%M")


def format_time_12(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def minutes_since_midnight(value: time) -> int:
    return value.hour * 60 + value.minute


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(int(minutes), 60)
    return f"{hours}h {remainder}m" if remainder else f"{hours}h"
