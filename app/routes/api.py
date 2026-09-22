"""JSON API. Routes stay thin: parse the request, call a service, serialise the result.

Validation and conflict errors are raised by the services as ApiError and
turned into JSON by the app-level error handler.
"""

from flask import Blueprint, jsonify, request

from app.db import session_scope
from app.services import employees as employee_service
from app.services import scheduling as shift_service
from app.services import settings as settings_service
from app.services.positions import list_positions, position_to_dict

api = Blueprint("api", __name__, url_prefix="/api")


# --- positions ---------------------------------------------------------------

@api.get("/positions")
def get_positions():
    with session_scope() as session:
        return jsonify([position_to_dict(position) for position in list_positions(session)])


# --- store settings ----------------------------------------------------------

@api.get("/settings")
def get_settings():
    with session_scope() as session:
        return jsonify(settings_service.settings_to_dict(session))


@api.put("/settings")
def update_settings():
    with session_scope() as session:
        return jsonify(settings_service.update_settings(session, request.get_json(silent=True)))


# --- employees ---------------------------------------------------------------

@api.get("/employees")
def list_employees():
    with session_scope() as session:
        employees = employee_service.list_employees(session, request.args.get("position"))
        return jsonify([employee_service.employee_to_dict(employee) for employee in employees])


@api.get("/employees/<int:employee_id>")
def get_employee(employee_id: int):
    with session_scope() as session:
        return jsonify(employee_service.employee_to_dict(employee_service.get_employee(session, employee_id)))


@api.post("/employees")
def create_employee():
    with session_scope() as session:
        return jsonify(employee_service.save_employee(session, request.get_json(silent=True))), 201


@api.put("/employees/<int:employee_id>")
def update_employee(employee_id: int):
    with session_scope() as session:
        return jsonify(employee_service.save_employee(session, request.get_json(silent=True), employee_id))


@api.delete("/employees/<int:employee_id>")
def delete_employee(employee_id: int):
    with session_scope() as session:
        employee_service.delete_employee(session, employee_id)
    return jsonify(message="Employee deleted")


# --- shifts ------------------------------------------------------------------

@api.get("/shifts")
def list_shifts():
    with session_scope() as session:
        shifts = shift_service.list_shifts(session, request.args.get("position"), request.args.get("day"))
        return jsonify(shift_service.serialize_shifts(session, shifts))


@api.post("/shifts")
def create_shift():
    with session_scope() as session:
        return jsonify(shift_service.save_shift(session, request.get_json(silent=True))), 201


@api.put("/shifts/<int:shift_id>")
def update_shift(shift_id: int):
    with session_scope() as session:
        return jsonify(shift_service.save_shift(session, request.get_json(silent=True), shift_id))


@api.delete("/shifts/<int:shift_id>")
def delete_shift(shift_id: int):
    with session_scope() as session:
        shift_service.delete_shift(session, shift_id)
    return jsonify(message="Shift deleted")


@api.delete("/shifts")
def clear_shifts():
    """Delete every shift, or only those matching ?position= and/or ?day=."""
    with session_scope() as session:
        count = shift_service.clear_shifts(session, request.args.get("position"), request.args.get("day"))
    return jsonify(message="Shifts cleared", deleted_count=count)


@api.post("/shifts/copy")
def copy_shifts():
    """Copy a day's shifts to other days; conflicting copies are skipped and reported."""
    with session_scope() as session:
        return jsonify(shift_service.copy_shifts(session, request.get_json(silent=True)))
