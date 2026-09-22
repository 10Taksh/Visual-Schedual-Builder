from app.constants import DAYS_OF_WEEK, DEFAULT_OPERATING_HOURS, DEFAULT_POSITIONS


class TestSettings:
    def test_defaults(self, client):
        assert client.get("/api/settings").get_json() == DEFAULT_OPERATING_HOURS

    def test_update_and_close_a_day(self, client):
        hours = {day: {"open": "8:30", "close": "18:00"} for day in DAYS_OF_WEEK}
        hours["Sunday"] = None
        response = client.put("/api/settings", json=hours)
        assert response.status_code == 200
        saved = response.get_json()
        assert saved["Monday"] == {"open": "08:30", "close": "18:00"}  # times normalised
        assert saved["Sunday"] is None
        assert client.get("/api/settings").get_json() == saved

    def test_validation(self, client):
        assert client.put("/api/settings", json=[]).status_code == 400
        bad = dict(DEFAULT_OPERATING_HOURS)
        bad["Monday"] = {"open": "10:00", "close": "09:00"}
        response = client.put("/api/settings", json=bad)
        assert response.status_code == 400
        assert "Monday" in response.get_json()["error"]


class TestPositions:
    def test_seeded_in_order(self, client):
        positions = client.get("/api/positions").get_json()
        assert [position["name"] for position in positions] == [item["name"] for item in DEFAULT_POSITIONS]
        assert positions[-1]["label"] == "Management + Supervisor"
        assert positions[0]["slug"] == "cashier"
        assert all(position["color"].startswith("#") for position in positions)


class TestPages:
    def test_root_redirects_to_employees(self, client):
        response = client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/employees")

    def test_health(self, client):
        assert client.get("/health").get_json()["status"] == "ok"

    def test_employees_page(self, client):
        html = client.get("/employees").get_data(as_text=True)
        assert "Employee directory" in html
        assert 'window.APP_META' in html
        assert 'value="Cashier"' in html  # position checkboxes rendered server-side

    def test_schedule_pages(self, client):
        for slug in ("cashier", "management", "supervisor", "Cashier"):
            assert client.get(f"/schedule/{slug}").status_code == 200, slug
        html = client.get("/schedule/management").get_data(as_text=True)
        assert "Management + Supervisor" in html
        assert 'data-position="Management"' in html

    def test_unknown_schedule_is_404(self, client):
        assert client.get("/schedule/pilot").status_code == 404

    def test_master_page_without_shifts(self, client):
        response = client.get("/master")
        assert response.status_code == 200
        assert "No saved shifts yet" in response.get_data(as_text=True)

    def test_master_page_with_shifts(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice", positions=("Cashier", "Food"))
        bob = make_employee(name="Bob", positions=("Food",))
        make_shift(alice["id"], position="Cashier", day="Monday", start="09:00", end="17:00")  # 8h, 7.5 paid
        make_shift(alice["id"], position="Food", day="Tuesday", start="09:00", end="13:00")  # 4h
        make_shift(bob["id"], position="Food", day="Monday", start="12:00", end="18:00")  # 6h, 5.5 paid
        html = client.get("/master").get_data(as_text=True)
        assert "1. Alice" in html and "2. Alice" in html and "3. Bob" in html  # grouped by position, then name
        assert "11.5h paid across 2 positions" in html
        assert "17h 0m paid" in html  # 7.5 + 4 + 5.5
        assert "18h 0m scheduled" in html

    def test_api_404_is_json(self, client):
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.get_json()["error"]

    def test_master_service_totals(self, app, make_employee, make_shift):
        from app.db import session_scope
        from app.services.scheduling import build_master_schedule

        employee = make_employee()
        make_shift(employee["id"], start="09:00", end="14:00")
        with session_scope() as session:
            data = build_master_schedule(session)
        assert data["total_scheduled_minutes"] == 300
        assert data["total_paid_minutes"] == 270
        assert data["rows"][0]["department_color"] == DEFAULT_POSITIONS[0]["color"]
