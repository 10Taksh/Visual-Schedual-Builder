"""Shifts: validation, conflict detection, break rules, copying, and the master-schedule rollup."""

from datetime import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.constants import DAYS_OF_WEEK, MINIMUM_SHIFT_MINUTES
from app.models import Employee, Position, Shift
from app.services.availability import availability_intervals, covers
from app.services.employees import get_employee
from app.services.errors import ApiError, ConflictError, NotFoundError
from app.services.positions import list_positions
from app.services.settings import BreakRule, get_break_rule, get_operating_hours
from app.services.times import format_time, format_time_12, minutes_since_midnight, parse_time


def shift_minutes(shift: Shift) -> int:
    return minutes_since_midnight(shift.end_time) - minutes_since_midnight(shift.start_time)


def shift_to_dict(shift: Shift, rule: BreakRule) -> dict:
    duration_minutes = shift_minutes(shift)
    # Derived from the current rule rather than the stored flag, so changing the
    # rule applies to the whole template week at once.
    break_minutes = rule.minutes_for(duration_minutes)
    return {
        "id": shift.id,
        "employee_id": shift.employee_id,
        "employee_name": shift.employee.name,
        "employee_color": shift.employee.color,
        "position": shift.position,
        "day_of_week": shift.day_of_week,
        "start_time": format_time(shift.start_time),
        "end_time": format_time(shift.end_time),
        "start_time_display": format_time_12(shift.start_time),
        "end_time_display": format_time_12(shift.end_time),
        "duration_minutes": duration_minutes,
        "break_deduction": break_minutes > 0,
        "break_minutes": break_minutes,
        "paid_minutes": duration_minutes - break_minutes,
    }


def serialize_shifts(session: Session, shifts: list[Shift]) -> list[dict]:
    rule = get_break_rule(session)
    return [shift_to_dict(shift, rule) for shift in shifts]


def list_shifts(session: Session, position_name: str | None = None, day: str | None = None) -> list[Shift]:
    query = select(Shift).join(Shift.employee).order_by(Shift.day_of_week, Shift.start_time, Employee.name)
    if position_name:
        query = query.where(Shift.position == position_name)
    if day:
        query = query.where(Shift.day_of_week == day)
    return list(session.scalars(query))


def find_conflict(
    session: Session,
    employee: Employee,
    day: str,
    start: time,
    end: time,
    exclude_shift_id: int | None = None,
) -> str | None:
    """Reason the shift cannot be saved, or None when it fits."""
    start_minutes, end_minutes = minutes_since_midnight(start), minutes_since_midnight(end)

    store_window = get_operating_hours(session).get(day)
    if store_window is None:
        return f"The store is closed on {day}."
    store_open, store_close = parse_time(store_window["open"]), parse_time(store_window["close"])
    if store_open is not None and store_close is not None:
        if start_minutes < minutes_since_midnight(store_open) or end_minutes > minutes_since_midnight(store_close):
            return f"Shift must be within store hours ({format_time_12(store_open)}–{format_time_12(store_close)})."

    if not covers(availability_intervals(employee.availability, day), start_minutes, end_minutes):
        return f"{employee.name} is unavailable during this time."

    others = select(Shift).where(Shift.employee_id == employee.id, Shift.day_of_week == day)
    if exclude_shift_id is not None:
        others = others.where(Shift.id != exclude_shift_id)
    for existing in session.scalars(others):
        if start_minutes < minutes_since_midnight(existing.end_time) and end_minutes > minutes_since_midnight(existing.start_time):
            return (
                f"{employee.name} is already scheduled as {existing.position} "
                f"{format_time_12(existing.start_time)}–{format_time_12(existing.end_time)}."
            )
    return None


def _position_names(session: Session) -> set[str]:
    return {item.name for item in list_positions(session)}


def save_shift(session: Session, payload: object, shift_id: int | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object")
    try:
        employee_id = int(payload.get("employee_id"))
    except (TypeError, ValueError):
        raise ApiError("Employee is required") from None
    position = payload.get("position")
    day = payload.get("day_of_week")
    start, end = parse_time(payload.get("start_time")), parse_time(payload.get("end_time"))

    if position not in _position_names(session):
        raise ApiError("Position is invalid")
    if day not in DAYS_OF_WEEK:
        raise ApiError("Day of week is invalid")
    if start is None or end is None or end <= start:
        raise ApiError("Shift must have valid start and end times")
    duration = minutes_since_midnight(end) - minutes_since_midnight(start)
    if duration < MINIMUM_SHIFT_MINUTES:
        raise ApiError(f"Shifts must be at least {MINIMUM_SHIFT_MINUTES} minutes")

    employee = get_employee(session, employee_id)
    if position not in {item.name for item in employee.positions}:
        raise ApiError(f"{employee.name} is not assigned to {position}")

    shift = session.get(Shift, shift_id) if shift_id is not None else Shift()
    if shift is None:
        raise NotFoundError("Shift not found")

    conflict = find_conflict(session, employee, day, start, end, exclude_shift_id=shift_id)
    if conflict:
        raise ConflictError(conflict)

    rule = get_break_rule(session)
    shift.employee_id = employee.id
    shift.position = position
    shift.day_of_week = day
    shift.start_time = start
    shift.end_time = end
    shift.break_deduction = rule.minutes_for(duration) > 0
    session.add(shift)
    session.flush()
    return shift_to_dict(shift, rule)


def delete_shift(session: Session, shift_id: int) -> None:
    shift = session.get(Shift, shift_id)
    if shift is None:
        raise NotFoundError("Shift not found")
    session.delete(shift)


def clear_shifts(session: Session, position_name: str | None = None, day: str | None = None) -> int:
    """Delete shifts, optionally limited to one position and/or one day. Returns the count."""
    if position_name and position_name not in _position_names(session):
        raise ApiError("Position is invalid")
    if day and day not in DAYS_OF_WEEK:
        raise ApiError("Day of week is invalid")
    criteria = []
    if position_name:
        criteria.append(Shift.position == position_name)
    if day:
        criteria.append(Shift.day_of_week == day)
    count = session.scalar(select(func.count()).select_from(Shift).where(*criteria)) or 0
    session.execute(delete(Shift).where(*criteria))
    return count


def copy_shifts(session: Session, payload: object) -> dict:
    """Copy one day's shifts (or a chosen subset) onto other days of the same position.

    Payload: ``{position, source_day, target_days: [...], shift_ids?: [...], replace?: bool}``.
    Copies that would conflict on the target day are skipped and reported, not failed.
    """
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object")
    position = payload.get("position")
    source_day = payload.get("source_day")
    target_days = payload.get("target_days")
    shift_ids = payload.get("shift_ids")
    replace = payload.get("replace") is True

    if position not in _position_names(session):
        raise ApiError("Position is invalid")
    if source_day not in DAYS_OF_WEEK:
        raise ApiError("Source day is invalid")
    if not isinstance(target_days, list) or not target_days:
        raise ApiError("Choose at least one day to copy to")
    if any(day not in DAYS_OF_WEEK for day in target_days) or source_day in target_days:
        raise ApiError("Target days must be other days of the week")
    if shift_ids is not None and (not isinstance(shift_ids, list) or not all(isinstance(item, int) for item in shift_ids)):
        raise ApiError("shift_ids must be a list of ids")

    sources = list_shifts(session, position, source_day)
    if shift_ids is not None:
        sources = [shift for shift in sources if shift.id in shift_ids]
    if not sources:
        raise ApiError(f"There are no shifts to copy from {source_day}")

    rule = get_break_rule(session)
    created: list[dict] = []
    skipped: list[dict] = []
    removed = 0
    for day in dict.fromkeys(target_days):
        if replace:
            removed += clear_shifts(session, position, day)
            session.flush()
        for source in sources:
            conflict = find_conflict(session, source.employee, day, source.start_time, source.end_time)
            if conflict:
                skipped.append({"employee_name": source.employee.name, "day_of_week": day, "reason": conflict})
                continue
            shift = Shift(
                employee_id=source.employee_id,
                position=position,
                day_of_week=day,
                start_time=source.start_time,
                end_time=source.end_time,
                break_deduction=rule.minutes_for(shift_minutes(source)) > 0,
            )
            session.add(shift)
            session.flush()  # later copies must see this one in their overlap check
            created.append(shift_to_dict(shift, rule))
    return {"created": created, "skipped": skipped, "removed": removed}


def _coverage_for_day(shifts: list[Shift], window: dict | None) -> dict:
    """Headcount per hour across the store day, plus totals — every position combined."""
    if window is None:
        return {"closed": True, "shift_count": 0, "scheduled_minutes": 0, "paid_minutes": 0, "buckets": []}
    open_minutes = minutes_since_midnight(parse_time(window["open"]))
    close_minutes = minutes_since_midnight(parse_time(window["close"]))
    buckets = [0] * max(1, -(-(close_minutes - open_minutes) // 60))
    for shift in shifts:
        start = minutes_since_midnight(shift.start_time)
        end = minutes_since_midnight(shift.end_time)
        for index, bucket_start in enumerate(range(open_minutes, close_minutes, 60)):
            if start < min(bucket_start + 60, close_minutes) and end > bucket_start:
                buckets[index] += 1
    return {"closed": False, "shift_count": len(shifts), "buckets": buckets, "open": window["open"], "close": window["close"]}


def build_master_schedule(session: Session) -> dict:
    """Rows grouped by position, each row one employee with their shifts per day, plus daily coverage."""
    positions: list[Position] = list_positions(session)
    rule = get_break_rule(session)
    hours = get_operating_hours(session)
    fallback = positions[-1] if positions else None
    by_name = {position.name: position for position in positions}
    grouped: dict[str, dict[int, dict]] = {position.name: {} for position in positions}
    totals: dict[int, dict] = {}
    shifts_by_day: dict[str, list[Shift]] = {day: [] for day in DAYS_OF_WEEK}
    day_minutes: dict[str, dict] = {day: {"scheduled": 0, "paid": 0} for day in DAYS_OF_WEEK}

    shifts = session.scalars(
        select(Shift).join(Shift.employee).order_by(Employee.name, Shift.position, Shift.day_of_week, Shift.start_time)
    )
    for shift in shifts:
        data = shift_to_dict(shift, rule)
        position = by_name.get(shift.position, fallback)
        if position is None:
            continue
        row = grouped[position.name].get(shift.employee_id)
        if row is None:
            row = grouped[position.name][shift.employee_id] = {
                "employee_id": shift.employee_id,
                "employee_name": shift.employee.name,
                "employee_color": shift.employee.color,
                "shifts_by_day": {day: [] for day in DAYS_OF_WEEK},
                "scheduled_minutes": 0,
                "paid_minutes": 0,
            }
        row["shifts_by_day"][shift.day_of_week].append(data)
        row["scheduled_minutes"] += data["duration_minutes"]
        row["paid_minutes"] += data["paid_minutes"]
        total = totals.setdefault(shift.employee_id, {"scheduled_minutes": 0, "paid_minutes": 0, "positions": set()})
        total["scheduled_minutes"] += data["duration_minutes"]
        total["paid_minutes"] += data["paid_minutes"]
        total["positions"].add(position.name)
        shifts_by_day[shift.day_of_week].append(shift)
        day_minutes[shift.day_of_week]["scheduled"] += data["duration_minutes"]
        day_minutes[shift.day_of_week]["paid"] += data["paid_minutes"]

    rows = []
    for position in positions:
        for row in grouped[position.name].values():
            total = totals[row["employee_id"]]
            row["row_number"] = len(rows) + 1
            row["department"] = position.name
            row["department_label"] = position.display_label
            row["department_color"] = position.color
            row["all_position_scheduled_minutes"] = total["scheduled_minutes"]
            row["all_position_paid_minutes"] = total["paid_minutes"]
            row["all_position_paid_hours"] = round(total["paid_minutes"] / 60, 2)
            row["position_count"] = len(total["positions"])
            rows.append(row)

    coverage = {}
    for day in DAYS_OF_WEEK:
        coverage[day] = _coverage_for_day(shifts_by_day[day], hours.get(day))
        coverage[day]["scheduled_minutes"] = day_minutes[day]["scheduled"]
        coverage[day]["paid_minutes"] = day_minutes[day]["paid"]
    max_headcount = max((max(item["buckets"]) for item in coverage.values() if item["buckets"]), default=0)

    return {
        "rows": rows,
        "coverage": coverage,
        "max_headcount": max_headcount,
        "total_scheduled_minutes": sum(row["scheduled_minutes"] for row in rows),
        "total_paid_minutes": sum(row["paid_minutes"] for row in rows),
    }
