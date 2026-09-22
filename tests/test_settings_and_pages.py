from app.constants import DAYS_OF_WEEK, DEFAULT_OPERATING_HOURS, DEFAULT_POSITIONS


class TestSettings:
    def test_defaults(self, client):
        assert client.get("/api/settings").get_json() == {
            "operating_hours": DEFAULT_OPERATING_HOURS,
            "break_threshold_minutes": 300,
            "break_duration_minutes": 30,
        }

    def test_update_and_close_a_day(self, client):
        hours = {day: {"open": "8:30", "close": "18:00"} for day in DAYS_OF_WEEK}
        hours["Sunday"] = None
        response = client.put("/api/settings", json={"operating_hours": hours})
        assert response.status_code == 200
        saved = response.get_json()["operating_hours"]
        assert saved["Monday"] == {"open": "08:30", "close": "18:00"}  # times normalised
        assert saved["Sunday"] is None
        assert client.get("/api/settings").get_json()["operating_hours"] == saved

    def test_legacy_bare_hours_payload_still_accepted(self, client):
        hours = dict(DEFAULT_OPERATING_HOURS)
        hours["Monday"] = None
        response = client.put("/api/settings", json=hours)
        assert response.status_code == 200
        assert response.get_json()["operating_hours"]["Monday"] is None
        assert response.get_json()["break_threshold_minutes"] == 300  # untouched

    def test_validation(self, client):
        assert client.put("/api/settings", json=[]).status_code == 400
        bad = dict(DEFAULT_OPERATING_HOURS)
        bad["Monday"] = {"open": "10:00", "close": "09:00"}
        response = client.put("/api/settings", json={"operating_hours": bad})
        assert response.status_code == 400
        assert "Monday" in response.get_json()["error"]

    def test_break_rule_update_and_validation(self, client):
        ok = client.put("/api/settings", json={"break_threshold_minutes": 360, "break_duration_minutes": 45})
        assert ok.status_code == 200
        assert (ok.get_json()["break_threshold_minutes"], ok.get_json()["break_duration_minutes"]) == (360, 45)
        assert client.put("/api/settings", json={"break_duration_minutes": 400}).status_code == 400  # >= threshold
        assert client.put("/api/settings", json={"break_threshold_minutes": "five"}).status_code == 400
        assert client.put("/api/settings", json={"break_threshold_minutes": -1}).status_code == 400
        assert client.put("/api/settings", json={"break_threshold_minutes": 0}).status_code == 200  # disables breaks

    def test_break_rule_applies_to_existing_shifts(self, client, make_employee, make_shift):
        employee = make_employee()
        shift = make_shift(employee["id"], start="09:00", end="15:00")  # 6h
        assert shift["paid_minutes"] == 330
        client.put("/api/settings", json={"break_threshold_minutes": 420, "break_duration_minutes": 60})
        refreshed = client.get("/api/shifts").get_json()[0]
        assert refreshed["break_deduction"] is False and refreshed["paid_minutes"] == 360
        client.put("/api/settings", json={"break_threshold_minutes": 300, "break_duration_minutes": 60})
        assert client.get("/api/shifts").get_json()[0]["paid_minutes"] == 300


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
        # Grouped by position (Cashier first), then by name: Alice/Cashier, Alice/Food, Bob/Food.
        assert html.index("Alice") < html.index("Bob")
        assert html.count("<strong>Alice</strong>") == 2 and html.count("<strong>Bob</strong>") == 1
        assert html.index('scope="rowgroup"') < html.index("<strong>Alice</strong>")
        assert "<strong>11.5h</strong>" in html and "2 positions" in html  # Alice's weekly total
        assert "17<small>h</small> 0<small>m</small>" in html  # paid: 7.5 + 4 + 5.5
        assert "18<small>h</small> 0<small>m</small>" in html  # scheduled

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
