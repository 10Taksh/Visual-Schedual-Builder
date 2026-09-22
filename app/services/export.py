"""CSV exports of the schedule."""

import csv
import io

from sqlalchemy.orm import Session

from app.constants import DAYS_OF_WEEK
from app.services.scheduling import build_master_schedule, list_shifts, serialize_shifts
from app.services.times import format_duration


def _csv(rows: list[list[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def master_schedule_csv(session: Session) -> str:
    """One row per employee-and-position, one column per day: the grid managers post on the wall."""
    data = build_master_schedule(session)
    rows: list[list[object]] = [["Employee", "Position", *DAYS_OF_WEEK, "Scheduled hours", "Paid hours"]]
    for row in data["rows"]:
        cells = []
        for day in DAYS_OF_WEEK:
            cells.append(" / ".join(
                f"{shift['start_time_display']}–{shift['end_time_display']} ({format_duration(shift['paid_minutes'])})"
                for shift in row["shifts_by_day"][day]
            ))
        rows.append([
            row["employee_name"],
            row["department_label"],
            *cells,
            f"{row['scheduled_minutes'] / 60:.2f}",
            f"{row['paid_minutes'] / 60:.2f}",
        ])
    rows.append([
        "Total", "", *["" for _ in DAYS_OF_WEEK],
        f"{data['total_scheduled_minutes'] / 60:.2f}",
        f"{data['total_paid_minutes'] / 60:.2f}",
    ])
    return _csv(rows)


def shifts_csv(session: Session) -> str:
    """One row per shift: the long format that spreadsheets and payroll tools prefer."""
    rows: list[list[object]] = [["Day", "Employee", "Position", "Start", "End", "Duration minutes", "Break minutes", "Paid minutes"]]
    day_order = {day: index for index, day in enumerate(DAYS_OF_WEEK)}
    shifts = sorted(serialize_shifts(session, list_shifts(session)), key=lambda s: (day_order[s["day_of_week"]], s["start_time"], s["employee_name"]))
    for shift in shifts:
        rows.append([
            shift["day_of_week"], shift["employee_name"], shift["position"],
            shift["start_time"], shift["end_time"],
            shift["duration_minutes"], shift["break_minutes"], shift["paid_minutes"],
        ])
    return _csv(rows)
