# Visual Schedule Builder

A small Flask app for building a recurring weekly staff schedule: manage employees and their
availability, set store operating hours, place shifts on a drag-and-drop timeline per
position, and review everything on one master schedule.

## Run it locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
$env:FLASK_ENV = "development"
python wsgi.py
```

Open <http://127.0.0.1:5000>. A SQLite database (`schedule.db`) is created in the project
folder on first start and seeded with the default positions and store hours.

Run the tests with:

```powershell
python -m pytest
```

## How it works

- **Employees** (`/employees`) — add people, their employment type, the positions they can
  work, a per-day availability editor (Open / Unavailable / Custom hours), and a schedule
  color. Store operating hours live on the same page.
- **Schedule** (`/schedule/<position>`) — one time-axis board per position: each day is a
  vertical timeline spanning store hours, and shifts are blocks positioned by time so gaps
  and overlaps are visible at a glance. Select a person in the roster, then click or drag on
  a day to place a shift; drag a block to move it (across days too), drag its edges to
  resize, or click it to type exact times. A coverage strip on each day shows headcount.
  Every change is checked against store hours, the person's availability, and their other
  shifts before it is saved. On phones the board shows one day at a time.
- **Master** (`/master`) — every saved shift, grouped by position, with paid and scheduled
  totals, sticky headers, and a print stylesheet. Shifts of five hours or more have a
  30-minute unpaid break deducted.

The schedule is a **recurring weekly template** — shifts are keyed by weekday, not by date.

### Availability format

Availability is `Open`, or a JSON object listing only the restricted days:

```json
{"Monday": "09:00-13:00", "Friday": ["10:00-12:00", "14:00-18:00"], "Sunday": "Unavailable"}
```

Days that are not listed are open. Anything the server cannot interpret is rejected with a
message rather than stored.

## Project layout

```
app/
  __init__.py        create_app() — config, engine, bootstrap, blueprints, error handlers
  config.py          Development / Production / Testing settings
  constants.py       days, break rules, color palette, default positions
  db.py              engine + session_scope (SQLite FK pragma, Postgres URL normalisation)
  models.py          Employee, Position, Shift, StoreSettings
  bootstrap.py       create tables, patch older schemas, seed defaults, normalise stored data
  services/          all business logic — framework-free, exercised directly by tests
    availability.py  canonical availability form + interval lookups
    employees.py     validation, color assignment, orphaned-shift protection
    scheduling.py    conflict detection, break rule, master-schedule rollup
    settings.py      operating hours
    positions.py     position lookup and URL slugs
    errors.py        ApiError → JSON error responses
  routes/
    pages.py         HTML pages
    api.py           JSON API under /api
  templates/         base.html + one template per page
  static/css/        tokens.css (design tokens), base.css, one file per page
  static/js/         lib/{api,dom,time,toast,dialog,availability-editor}.js, one module per page
tests/               pytest suite (in-memory SQLite)
wsgi.py              entry point: `gunicorn wsgi:app` or `python wsgi.py`
```

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/positions` | `[{id, name, label, slug, color, sort_order}]` |
| GET / PUT | `/api/settings` | operating hours, `{Monday: {open, close} \| null, ...}` |
| GET | `/api/employees?position=Cashier` | optional position filter |
| GET / POST | `/api/employees`, `/api/employees/<id>` | |
| PUT / DELETE | `/api/employees/<id>` | PUT returns 409 `code: orphaned_shifts` if a removed position still has shifts; resend with `remove_orphaned_shifts: true` |
| GET | `/api/shifts?position=Cashier` | optional position filter |
| POST | `/api/shifts` | `{employee_id, position, day_of_week, start_time, end_time}` — 409 on conflict |
| PUT / DELETE | `/api/shifts/<id>` | |
| DELETE | `/api/shifts` | clears every shift |

Times are `HH:MM` (24-hour) in the API; responses also include `*_display` fields in 12-hour
form. Errors are `{"error": "..."}` with a 400/404/409 status.

## Deploy

The repo includes a `render.yaml` for [Render](https://render.com) with a free Postgres
database. Any host that runs `gunicorn wsgi:app --bind 0.0.0.0:$PORT` works.

Environment variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. `postgres://` and `postgresql://` are both accepted and routed to the psycopg 3 driver. Falls back to SQLite when unset. |
| `DATABASE_PATH` | Where to put the SQLite file when `DATABASE_URL` is unset. |
| `SECRET_KEY` | Set to a random value in production. |
| `FLASK_ENV` | `development` enables debug mode; anything else is production. |

The app patches its own schema on startup (adds columns introduced after the first release),
so upgrading an existing database needs no manual migration.
