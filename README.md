# Visual Schedule Builder

Step 4 adds role-filtered employee selection and client-side placement to the
reusable weekly schedule grid on top of the employee
management page, CRUD API, Flask foundation, and SQLAlchemy models.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

The development server exposes `GET /health`, `GET /employees`, and creates
`schedule.db` on startup. Open `http://127.0.0.1:5000/employees` to manage the
team.

## Deploy online

This project is a Flask app with SQLite storage, so it can be hosted on most
Python web hosting providers. The basic deployment flow is:

```text
pip install -r requirements.txt
gunicorn app:app
```

The app uses a local SQLite database file named `schedule.db` by default. If
your hosting provider uses a read-only filesystem or restarts the app often,
keep the database in a writable persistent folder or set a writable path in the
hosting environment.

Employee API routes are available at `GET /api/employees`,
`GET /api/employees/<id>`, `POST /api/employees`, `PUT /api/employees/<id>`,
and `DELETE /api/employees/<id>`. Positions are available from
`GET /api/positions`.

Schedule layout pages are available at `/schedule/cashier`,
`/schedule/merchandiser`, `/schedule/cosmetics`, `/schedule/food`, and
`/schedule/management`. Management includes Supervisor in the same view.
Employees can be selected by role and placed into a day as saved shift cards.
Shift sliders save time changes, calculate a 30-minute break at five hours,
and reject unavailable or overlapping employee shifts.

The aggregated master schedule is available at `/master` and shows all saved
positions together from Monday through Sunday.

Store operating hours are configured on `/employees`. They are enforced when
creating or adjusting shifts. Schedule pages and the master view display times
in 12-hour AM/PM format; the API continues to use `HH:MM` values internally.
Shift sliders move in 15-minute increments, including times such as 1:00,
1:15, 1:30, and 1:45.

The initial position names used by later steps are `Cashier`, `Merchandiser`,
`Cosmetics`, `Food`, and `Management`. `Supervisor` can be stored as a shift
position in the combined management view.
