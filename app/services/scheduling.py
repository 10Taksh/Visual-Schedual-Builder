"""Shifts: validation, conflict detection, break rules, and the master-schedule rollup."""

from datetime import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.constants import (
    BREAK_DURATION_MINUTES,
    BREAK_THRESHOLD_MINUTES,
    DAYS_OF_WEEK,
    MINIMUM_SHIFT_MINUTES,
)
from app.models import Employee, Position, Shift
from app.services.availability import availability_intervals, covers
from app.services.employees import get_employee
from app.services.errors import ApiError, ConflictError, NotFoundError
from app.services.positions import list_positions
from app.services.settings import get_operating_hours
from app.services.times import format_time, format_time_12, minutes_since_midnight, parse_time


def break_minutes_for(duration_minutes: int) -> int:
    return BREAK_DURATION_MINUTES if duration_minutes >= BREAK_THRESHOLD_MINUTES else 0


def shift_to_dict(shift: Shift) -> dict:
    duration_minutes = minutes_since_midnight(shift.end_time) - minutes_since_midnight(shift.start_time)
    break_minutes = BREAK_DURATION_MINUTES if shift.break_deduction else 0
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
        "break_deduction": shift.break_deduction,
        "break_minutes": break_minutes,
        "paid_minutes": duration_minutes - break_minutes,
    }


def list_shifts(session: Session, position_name: str | None = None) -> list[Shift]:
    query = select(Shift).join(Shift.employee).order_by(Shift.day_of_week, Shift.start_time)
    if position_name:
        query = query.where(Shift.position == position_name)
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

    if position not in {item.name for item in list_positions(session)}:
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

    shift.employee_id = employee.id
    shift.position = position
    shift.day_of_week = day
    shift.start_time = start
    shift.end_time = end
    shift.break_deduction = break_minutes_for(duration) > 0
    session.add(shift)
    session.flush()
    return shift_to_dict(shift)


def delete_shift(session: Session, shift_id: int) -> None:
    shift = session.get(Shift, shift_id)
    if shift is None:
        raise NotFoundError("Shift not found")
    session.delete(shift)


def clear_shifts(session: Session) -> int:
    count = session.scalar(select(func.count()).select_from(Shift)) or 0
    session.execute(delete(Shift))
    return count


def build_master_schedule(session: Session) -> dict:
    """Rows grouped by position, each row one employee with their shifts per day."""
    positions: list[Position] = list_positions(session)
    fallback = positions[-1] if positions else None
    by_name = {position.name: position for position in positions}
    grouped: dict[str, dict[int, dict]] = {position.name: {} for position in positions}
    totals: dict[int, dict] = {}

    shifts = session.scalars(
        select(Shift).join(Shift.employee).order_by(Employee.name, Shift.position, Shift.day_of_week, Shift.start_time)
    )
    for shift in shifts:
        data = shift_to_dict(shift)
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

    return {
        "rows": rows,
        "total_scheduled_minutes": sum(row["scheduled_minutes"] for row in rows),
        "total_paid_minutes": sum(row["paid_minutes"] for row in rows),
    }
