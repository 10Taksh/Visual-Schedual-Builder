import json
from datetime import datetime, time

from flask import Flask, abort, jsonify, render_template, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import engine, session_scope
from models import Base, Employee, Position, Shift, StoreSettings


POSITION_NAMES = ("Cashier", "Merchandiser", "Cosmetics", "Food", "Management")
EMPLOYMENT_TYPES = ("Full-Time", "Part-Time")
DAYS_OF_WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_OPERATING_HOURS = {day: {"open": "09:00", "close": "21:00"} for day in DAYS_OF_WEEK}


def employee_to_dict(employee: Employee) -> dict:
    return {
        "id": employee.id,
        "name": employee.name,
        "employment_type": employee.employment_type,
        "availability": employee.availability,
        "color": employee.color,
        "positions": [position.name for position in employee.positions],
    }


def parse_availability(value: object) -> dict | str:
    if value is None or value == "" or value == "Open":
        return "Open"
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, (dict, list, str)):
            return parsed
    raise ValueError("availability must be Open, text, or valid JSON")


def validate_employee_payload(payload: object, positions_by_name: dict[str, Position]) -> tuple[dict | None, str | None]:
    if not isinstance(payload, dict):
        return None, "Request body must be a JSON object"

    name = str(payload.get("name", "")).strip()
    employment_type = payload.get("employment_type")
    position_names = payload.get("positions", [])
    if not name:
        return None, "Name is required"
    if employment_type not in EMPLOYMENT_TYPES:
        return None, "Employment type must be Full-Time or Part-Time"
    if not isinstance(position_names, list) or not position_names:
        return None, "At least one position is required"
    if any(position not in positions_by_name for position in position_names):
        return None, "One or more positions are invalid"

    try:
        availability = parse_availability(payload.get("availability"))
    except ValueError as error:
        return None, str(error)

    color = str(payload.get("color", "")).strip() or None
    if color is not None and (len(color) != 7 or not color.startswith("#")):
        return None, "Color must be a 6-digit hex value"

    return {
        "name": name,
        "employment_type": employment_type,
        "availability": availability,
        "color": color,
        "positions": [positions_by_name[position] for position in dict.fromkeys(position_names)],
    }, None


def parse_time(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def minutes_since_midnight(value: time) -> int:
    return value.hour * 60 + value.minute


def format_time(value: time) -> str:
    return value.strftime("%H:%M")


def format_time_12(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def settings_to_dict(settings: StoreSettings) -> dict:
    return settings.operating_hours


def validate_operating_hours(value: object) -> tuple[dict | None, str | None]:
    if not isinstance(value, dict):
        return None, "Operating hours must be an object with one entry per day"
    result = {}
    for day in DAYS_OF_WEEK:
        day_value = value.get(day)
        if day_value in (None, "closed", "Closed"):
            result[day] = None
            continue
        if not isinstance(day_value, dict):
            return None, f"Operating hours for {day} are invalid"
        opening, closing = parse_time(day_value.get("open")), parse_time(day_value.get("close"))
        if opening is None or closing is None or closing <= opening:
            return None, f"Operating hours for {day} must have a valid open and close time"
        result[day] = {"open": format_time(opening), "close": format_time(closing)}
    return result, None


def shift_to_dict(shift: Shift) -> dict:
    start_minutes = minutes_since_midnight(shift.start_time)
    end_minutes = minutes_since_midnight(shift.end_time)
    duration_minutes = end_minutes - start_minutes
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
        "paid_minutes": duration_minutes - (30 if shift.break_deduction else 0),
    }


def availability_intervals(availability: object, day: str) -> list[tuple[int, int]] | None:
    if availability in (None, "", "Open"):
        return None
    if not isinstance(availability, dict):
        return None
    value = availability.get(day, "Open")
    if value in (None, "", "Open"):
        return None
    if isinstance(value, str):
        if value.lower() in ("closed", "unavailable", "none"):
            return []
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    intervals = []
    for item in values:
        if isinstance(item, dict):
            start_value, end_value = item.get("start"), item.get("end")
        elif isinstance(item, str) and "-" in item:
            start_value, end_value = (part.strip() for part in item.split("-", 1))
        else:
            continue
        start, end = parse_time(start_value), parse_time(end_value)
        if start is not None and end is not None and end > start:
            intervals.append((minutes_since_midnight(start), minutes_since_midnight(end)))
    return intervals


def shift_request_error(session, employee: Employee, position: str, day: str, start: time, end: time, shift_id: int | None) -> str | None:
    start_minutes, end_minutes = minutes_since_midnight(start), minutes_since_midnight(end)
    settings = session.scalar(select(StoreSettings).where(StoreSettings.id == 1))
    store_window = (settings.operating_hours if settings else DEFAULT_OPERATING_HOURS).get(day)
    if store_window is None:
        return f"Conflict: The store is closed on {day}."
    store_open = parse_time(store_window["open"])
    store_close = parse_time(store_window["close"])
    if store_open is not None and store_close is not None:
        if start_minutes < minutes_since_midnight(store_open) or end_minutes > minutes_since_midnight(store_close):
            return f"Conflict: Shift must be within store hours ({format_time(store_open)}–{format_time(store_close)})."
    allowed = availability_intervals(employee.availability, day)
    if allowed is not None and not any(start_minutes >= window_start and end_minutes <= window_end for window_start, window_end in allowed):
        return f"Conflict: {employee.name} is unavailable during this time."

    existing_query = select(Shift).where(
        Shift.employee_id == employee.id,
        Shift.day_of_week == day,
    )
    if shift_id is not None:
        existing_query = existing_query.where(Shift.id != shift_id)
    for existing in session.scalars(existing_query).all():
        existing_start = minutes_since_midnight(existing.start_time)
        existing_end = minutes_since_midnight(existing.end_time)
        if start_minutes < existing_end and end_minutes > existing_start:
            return f"Conflict: {employee.name} is already scheduled as a {existing.position} at this time."
    return None


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> tuple[dict, int]:
        return jsonify(
            service="visual-schedule-builder",
            status="ok",
            health_url="/health",
        ), 200

    @app.get("/health")
    def health() -> tuple[dict, int]:
        return jsonify(status="ok", service="visual-schedule-builder"), 200

    @app.get("/employees")
    def employees_page():
        return render_template("employees.html")

    @app.get("/api/settings")
    def get_settings():
        with session_scope() as session:
            settings = session.scalar(select(StoreSettings).where(StoreSettings.id == 1))
            return jsonify(settings_to_dict(settings) if settings else DEFAULT_OPERATING_HOURS)

    @app.put("/api/settings")
    def update_settings():
        hours, error = validate_operating_hours(request.get_json(silent=True))
        if error:
            return jsonify(error=error), 400
        with session_scope() as session:
            settings = session.scalar(select(StoreSettings).where(StoreSettings.id == 1))
            if settings is None:
                settings = StoreSettings(id=1, operating_hours=hours)
                session.add(settings)
            else:
                settings.operating_hours = hours
            session.flush()
            return jsonify(settings_to_dict(settings))

    @app.get("/schedule/<position>")
    def schedule_page(position: str):
        position_name = position.replace("-", " ").title()
        if position_name == "Supervisor":
            position_name = "Management"
        if position_name not in POSITION_NAMES:
            abort(404)
        position_index = POSITION_NAMES.index(position_name)
        previous_position = POSITION_NAMES[(position_index - 1) % len(POSITION_NAMES)]
        next_position = POSITION_NAMES[(position_index + 1) % len(POSITION_NAMES)]
        return render_template(
            "schedule.html",
            active_position=position_name,
            display_position="Management + Supervisor" if position_name == "Management" else position_name,
            positions=POSITION_NAMES,
            previous_position=previous_position,
            next_position=next_position,
        )

    @app.get("/master")
    def master_schedule_page():
        with session_scope() as session:
            shifts = session.scalars(
                select(Shift).join(Shift.employee).order_by(Employee.name, Shift.position, Shift.day_of_week, Shift.start_time)
            ).all()
            position_order = ("Cashier", "Merchandiser", "Food", "Supervisor", "Cosmetics", "Management")
            department_colors = {
                "Cashier": "#4B9CD3",
                "Merchandiser": "#7A9E52",
                "Food": "#E07A5F",
                "Supervisor": "#8B6FB3",
                "Cosmetics": "#C875A5",
                "Management": "#53685D",
            }
            grouped = {
                position: {}
                for position in position_order
            }
            employee_totals = {}
            for shift in shifts:
                position = shift.position if shift.position in grouped else "Management"
                employee_rows = grouped[position]
                if shift.employee_id not in employee_rows:
                    employee_rows[shift.employee_id] = {
                        "employee_id": shift.employee_id,
                        "row_number": len(employee_rows) + 1,
                        "employee_name": shift.employee.name,
                        "employee_color": shift.employee.color,
                        "shifts_by_day": {day: [] for day in DAYS_OF_WEEK},
                        "scheduled_minutes": 0,
                        "paid_minutes": 0,
                    }
                employee_rows[shift.employee_id]["shifts_by_day"][shift.day_of_week].append(shift_to_dict(shift))
                shift_data = shift_to_dict(shift)
                employee_rows[shift.employee_id]["scheduled_minutes"] += shift_data["duration_minutes"]
                employee_rows[shift.employee_id]["paid_minutes"] += shift_data["paid_minutes"]
                employee_total = employee_totals.setdefault(
                    shift.employee_id,
                    {"scheduled_minutes": 0, "paid_minutes": 0, "positions": set()},
                )
                employee_total["scheduled_minutes"] += shift_data["duration_minutes"]
                employee_total["paid_minutes"] += shift_data["paid_minutes"]
                employee_total["positions"].add(position)
            position_groups = [
                {"name": position, "rows": list(grouped[position].values())}
                for position in position_order
                if grouped[position]
            ]
            for group in position_groups:
                group["color"] = department_colors[group["name"]]
            master_rows = []
            row_number = 1
            for group in position_groups:
                for row in group["rows"]:
                    row["row_number"] = row_number
                    row["department"] = group["name"]
                    row["department_color"] = group["color"]
                    total = employee_totals[row["employee_id"]]
                    row["all_position_paid_minutes"] = total["paid_minutes"]
                    row["all_position_scheduled_minutes"] = total["scheduled_minutes"]
                    row["position_count"] = len(total["positions"])
                    row["all_position_paid_hours"] = round(total["paid_minutes"] / 60, 2)
                    master_rows.append(row)
                    row_number += 1
                    total_scheduled_minutes = sum(row["scheduled_minutes"] for row in master_rows)
                    total_paid_minutes = sum(row["paid_minutes"] for row in master_rows)
        return render_template(
            "master.html",
            days=DAYS_OF_WEEK,
            position_groups=position_groups,
            master_rows=master_rows,
            total_scheduled_minutes=total_scheduled_minutes,
            total_paid_minutes=total_paid_minutes,
        )

    @app.get("/api/positions")
    def list_positions():
        with session_scope() as session:
            positions = session.scalars(select(Position).order_by(Position.name)).all()
            return jsonify([position.name for position in positions])

    @app.get("/api/employees")
    def list_employees():
        with session_scope() as session:
            employee_query = select(Employee).order_by(Employee.name)
            position_name = request.args.get("position")
            if position_name:
                employee_query = employee_query.join(Employee.positions).where(Position.name == position_name)
            employees = session.scalars(employee_query).unique().all()
            return jsonify([employee_to_dict(employee) for employee in employees])

    @app.get("/api/employees/<int:employee_id>")
    def get_employee(employee_id: int):
        with session_scope() as session:
            employee = session.get(Employee, employee_id)
            if employee is None:
                return jsonify(error="Employee not found"), 404
            return jsonify(employee_to_dict(employee))

    @app.get("/api/shifts")
    def list_shifts():
        with session_scope() as session:
            shift_query = select(Shift).join(Shift.employee).order_by(Shift.day_of_week, Shift.start_time)
            position_name = request.args.get("position")
            if position_name:
                shift_query = shift_query.where(Shift.position == position_name)
            shifts = session.scalars(shift_query).all()
            return jsonify([shift_to_dict(shift) for shift in shifts])

    @app.post("/api/shifts")
    def create_shift():
        return save_shift()

    @app.put("/api/shifts/<int:shift_id>")
    def update_shift(shift_id: int):
        return save_shift(shift_id)

    @app.delete("/api/shifts/<int:shift_id>")
    def delete_shift(shift_id: int):
        with session_scope() as session:
            shift = session.get(Shift, shift_id)
            if shift is None:
                return jsonify(error="Shift not found"), 404
            session.delete(shift)
        return jsonify(message="Shift deleted"), 200

    @app.delete("/api/shifts")
    def clear_shifts():
        with session_scope() as session:
            shifts = session.scalars(select(Shift)).all()
            count = len(shifts)
            for shift in shifts:
                session.delete(shift)
        return jsonify(message="Schedule cleared", deleted_count=count), 200

    def save_shift(shift_id: int | None = None):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Request body must be a JSON object"), 400
        try:
            employee_id = int(payload.get("employee_id"))
        except (TypeError, ValueError):
            return jsonify(error="Employee is required"), 400
        position = payload.get("position")
        day = payload.get("day_of_week")
        start, end = parse_time(payload.get("start_time")), parse_time(payload.get("end_time"))
        if position not in POSITION_NAMES:
            return jsonify(error="Position is invalid"), 400
        if day not in DAYS_OF_WEEK:
            return jsonify(error="Day of week is invalid"), 400
        if start is None or end is None or end <= start:
            return jsonify(error="Shift must have valid start and end times"), 400

        with session_scope() as session:
            employee = session.get(Employee, employee_id)
            if employee is None:
                return jsonify(error="Employee not found"), 404
            if position not in {item.name for item in employee.positions}:
                return jsonify(error=f"{employee.name} is not assigned to {position}"), 400
            conflict = shift_request_error(session, employee, position, day, start, end, shift_id)
            if conflict:
                return jsonify(error=conflict), 409
            shift = session.get(Shift, shift_id) if shift_id is not None else Shift()
            if shift is None:
                return jsonify(error="Shift not found"), 404
            shift.employee_id = employee.id
            shift.position = position
            shift.day_of_week = day
            shift.start_time = start
            shift.end_time = end
            shift.break_deduction = end.hour * 60 + end.minute - start.hour * 60 - start.minute >= 300
            session.add(shift)
            session.flush()
            result = shift_to_dict(shift)
        return jsonify(result), 200 if shift_id is not None else 201

    @app.post("/api/employees")
    def create_employee():
        return save_employee()

    @app.put("/api/employees/<int:employee_id>")
    def update_employee(employee_id: int):
        return save_employee(employee_id)

    @app.delete("/api/employees/<int:employee_id>")
    def delete_employee(employee_id: int):
        with session_scope() as session:
            employee = session.get(Employee, employee_id)
            if employee is None:
                return jsonify(error="Employee not found"), 404
            session.delete(employee)
        return jsonify(message="Employee deleted"), 200

    def save_employee(employee_id: int | None = None):
        with session_scope() as session:
            positions = session.scalars(select(Position)).all()
            positions_by_name = {position.name: position for position in positions}
            values, error = validate_employee_payload(request.get_json(silent=True), positions_by_name)
            if error:
                return jsonify(error=error), 400

            employee = session.get(Employee, employee_id) if employee_id is not None else Employee()
            if employee is None:
                return jsonify(error="Employee not found"), 404
            employee.name = values["name"]
            employee.employment_type = values["employment_type"]
            employee.availability = values["availability"]
            if values["color"] is not None:
                employee.color = values["color"]
            employee.positions = values["positions"]
            session.add(employee)
            try:
                session.flush()
            except IntegrityError:
                return jsonify(error="That employee color is already in use"), 409
            result = employee_to_dict(employee)
        return jsonify(result), 200 if employee_id is not None else 201

    with app.app_context():
        Base.metadata.create_all(engine)
        with session_scope() as session:
            existing_names = set(session.scalars(select(Position.name)).all())
            session.add_all(
                Position(name=name)
                for name in POSITION_NAMES
                if name not in existing_names
            )
            if session.get(StoreSettings, 1) is None:
                session.add(StoreSettings(id=1, operating_hours=DEFAULT_OPERATING_HOURS))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
