"""HTML pages. Data comes from the services; the API blueprint serves the JS."""

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, url_for

from app.constants import DAYS_OF_WEEK
from app.db import session_scope
from app.services.export import master_schedule_csv, shifts_csv
from app.services.positions import list_positions, position_to_dict, resolve_position
from app.services.scheduling import build_master_schedule

pages = Blueprint("pages", __name__)


@pages.context_processor
def inject_positions() -> dict:
    # Every page's navigation lists the positions; one small query per render.
    with session_scope() as session:
        return {"positions": [position_to_dict(position) for position in list_positions(session)], "days": DAYS_OF_WEEK}


@pages.get("/")
def index():
    return redirect(url_for("pages.employees"))


@pages.get("/health")
def health():
    return jsonify(status="ok", service="visual-schedule-builder")


@pages.get("/employees")
def employees():
    return render_template("employees.html")


@pages.get("/schedule/<slug>")
def schedule(slug: str):
    with session_scope() as session:
        position = resolve_position(session, slug)
        if position is None:
            abort(404)
        positions = [position_to_dict(item) for item in list_positions(session)]
        active = position_to_dict(position)
    index = next(i for i, item in enumerate(positions) if item["id"] == active["id"])
    return render_template(
        "schedule.html",
        active_position=active,
        positions=positions,
        previous_position=positions[(index - 1) % len(positions)],
        next_position=positions[(index + 1) % len(positions)],
    )


@pages.get("/master")
def master():
    with session_scope() as session:
        schedule_data = build_master_schedule(session)
    return render_template("master.html", **schedule_data)


def _csv_response(body: str, filename: str) -> Response:
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@pages.get("/export/master.csv")
def export_master():
    with session_scope() as session:
        return _csv_response(master_schedule_csv(session), "master-schedule.csv")


@pages.get("/export/shifts.csv")
def export_shifts():
    with session_scope() as session:
        return _csv_response(shifts_csv(session), "shifts.csv")
