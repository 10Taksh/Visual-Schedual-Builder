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

## Deploy online for free

This app is already set up for a standard Python web host. The simplest free
option is Render: connect your GitHub repo, choose the Python service, and use
this start command:

```text
gunicorn app:app --bind 0.0.0.0:$PORT
```

The app also supports a real database URL through the `DATABASE_URL` environment
variable. If you do not set one, it falls back to a local SQLite file named
`schedule.db` in the project folder. SQLite is fine for testing, but on free
hosting it can be reset when the app restarts, so a Postgres add-on is the more
reliable option.

Example free-hosting setup:

```text
pip install -r requirements.txt
export DATABASE_URL=postgresql://user:password@host/dbname
gunicorn app:app --bind 0.0.0.0:$PORT
```

If you use Render, Railway, or another free Python host, the app will start
correctly with Gunicorn and expose the `/health` endpoint for a quick check.

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
