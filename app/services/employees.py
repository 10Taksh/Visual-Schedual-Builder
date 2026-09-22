import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import EMPLOYEE_COLOR_PALETTE, EMPLOYMENT_TYPES
from app.models import Employee, Position, generate_employee_color
from app.services.availability import normalize_availability
from app.services.errors import ApiError, ConflictError, NotFoundError
from app.services.positions import positions_by_name

HEX_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$")


def employee_to_dict(employee: Employee) -> dict:
    return {
        "id": employee.id,
        "name": employee.name,
        "employment_type": employee.employment_type,
        "availability": employee.availability,
        "color": employee.color,
        "positions": [position.name for position in employee.positions],
    }


def list_employees(session: Session, position_name: str | None = None) -> list[Employee]:
    query = select(Employee).order_by(Employee.name)
    if position_name:
        query = query.join(Employee.positions).where(Position.name == position_name)
    return list(session.scalars(query).unique())


def get_employee(session: Session, employee_id: int) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found")
    return employee


def next_available_color(session: Session) -> str:
    used = set(session.scalars(select(Employee.color)))
    return next((color for color in EMPLOYEE_COLOR_PALETTE if color not in used), generate_employee_color())


def validate_employee_payload(payload: object, known_positions: dict[str, Position]) -> dict:
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object")

    name = str(payload.get("name", "")).strip()
    employment_type = payload.get("employment_type")
    position_names = payload.get("positions", [])
    if not name:
        raise ApiError("Name is required")
    if employment_type not in EMPLOYMENT_TYPES:
        raise ApiError(f"Employment type must be one of: {', '.join(EMPLOYMENT_TYPES)}")
    if not isinstance(position_names, list) or not position_names:
        raise ApiError("At least one position is required")
    unknown = [position for position in position_names if position not in known_positions]
    if unknown:
        raise ApiError(f"Unknown position: {', '.join(map(str, unknown))}")

    try:
        availability = normalize_availability(payload.get("availability"))
    except ValueError as error:
        raise ApiError(str(error)) from None

    color = str(payload.get("color") or "").strip().upper() or None
    if color is not None and HEX_COLOR_RE.match(color) is None:
        raise ApiError("Color must be a hex value like #3D8BBD")

    return {
        "name": name,
        "employment_type": employment_type,
        "availability": availability,
        "color": color,
        "positions": [known_positions[position] for position in dict.fromkeys(position_names)],
    }


def save_employee(session: Session, payload: object, employee_id: int | None = None) -> dict:
    """Create or update an employee; returns the employee dict plus ``removed_shifts``."""
    values = validate_employee_payload(payload, positions_by_name(session))
    employee = get_employee(session, employee_id) if employee_id is not None else Employee()

    # Shifts in a position the employee no longer holds would otherwise be
    # orphaned: invisible on the employee, still counted on the schedule.
    removed_positions = {item.name for item in employee.positions} - {item.name for item in values["positions"]}
    orphaned_shifts = [shift for shift in employee.shifts if shift.position in removed_positions]
    if orphaned_shifts and payload.get("remove_orphaned_shifts") is not True:
        plural = "s" if len(orphaned_shifts) != 1 else ""
        raise ConflictError(
            f"{employee.name} has {len(orphaned_shifts)} saved shift{plural} as {', '.join(sorted(removed_positions))}.",
            code="orphaned_shifts",
            shift_count=len(orphaned_shifts),
        )
    for shift in orphaned_shifts:
        session.delete(shift)

    employee.name = values["name"]
    employee.employment_type = values["employment_type"]
    employee.availability = values["availability"]
    if values["color"] is not None:
        employee.color = values["color"]
    elif employee_id is None:
        employee.color = next_available_color(session)
    employee.positions = values["positions"]
    session.add(employee)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ConflictError("That color is already used by another employee. Pick a different one.") from None

    result = employee_to_dict(employee)
    result["removed_shifts"] = len(orphaned_shifts)
    return result


def delete_employee(session: Session, employee_id: int) -> None:
    session.delete(get_employee(session, employee_id))
