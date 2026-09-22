import csv
import io


def _copy(client, **payload):
    return client.post("/api/shifts/copy", json={"position": "Cashier", "source_day": "Monday", **payload})


class TestCopyDay:
    def test_copies_every_shift_to_each_target(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice")
        bob = make_employee(name="Bob")
        make_shift(alice["id"], start="09:00", end="13:00")
        make_shift(bob["id"], start="13:00", end="21:00")
        response = _copy(client, target_days=["Tuesday", "Wednesday"])
        assert response.status_code == 200
        body = response.get_json()
        assert len(body["created"]) == 4 and body["skipped"] == [] and body["removed"] == 0
        assert {shift["day_of_week"] for shift in body["created"]} == {"Tuesday", "Wednesday"}
        assert len(client.get("/api/shifts").get_json()) == 6

    def test_subset_by_shift_ids(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice")
        bob = make_employee(name="Bob")
        keep = make_shift(alice["id"], start="09:00", end="13:00")
        make_shift(bob["id"], start="13:00", end="21:00")
        body = _copy(client, target_days=["Friday"], shift_ids=[keep["id"]]).get_json()
        assert [shift["employee_name"] for shift in body["created"]] == ["Alice"]

    def test_skips_conflicts_with_reasons(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice", positions=("Cashier", "Food"), availability={"Wednesday": "Unavailable"})
        make_shift(alice["id"], start="09:00", end="13:00")
        make_shift(alice["id"], position="Food", day="Thursday", start="10:00", end="12:00")  # overlaps a Thursday copy
        settings = client.get("/api/settings").get_json()
        settings["operating_hours"]["Sunday"] = None
        client.put("/api/settings", json=settings)

        body = _copy(client, target_days=["Tuesday", "Wednesday", "Thursday", "Sunday"]).get_json()
        assert [shift["day_of_week"] for shift in body["created"]] == ["Tuesday"]
        reasons = {item["day_of_week"]: item["reason"] for item in body["skipped"]}
        assert "unavailable" in reasons["Wednesday"]
        assert "already scheduled as Food" in reasons["Thursday"]
        assert "closed on Sunday" in reasons["Sunday"]

    def test_replace_clears_target_first(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice")
        make_shift(alice["id"], start="09:00", end="13:00")
        make_shift(alice["id"], day="Tuesday", start="14:00", end="18:00")
        without_replace = _copy(client, target_days=["Tuesday"]).get_json()
        assert len(without_replace["created"]) == 1 and without_replace["removed"] == 0
        assert len(client.get("/api/shifts?day=Tuesday").get_json()) == 2

        with_replace = _copy(client, target_days=["Tuesday"], replace=True).get_json()
        assert with_replace["removed"] == 2 and len(with_replace["created"]) == 1
        tuesday = client.get("/api/shifts?day=Tuesday").get_json()
        assert [(s["start_time"], s["end_time"]) for s in tuesday] == [("09:00", "13:00")]

    def test_copy_is_scoped_to_position(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice", positions=("Cashier", "Food"))
        make_shift(alice["id"], position="Food", start="09:00", end="13:00")
        response = _copy(client, target_days=["Tuesday"])  # Cashier has nothing on Monday
        assert response.status_code == 400
        assert "no shifts to copy" in response.get_json()["error"]

    def test_validation(self, client, make_employee, make_shift):
        alice = make_employee()
        make_shift(alice["id"])
        assert _copy(client, target_days=[]).status_code == 400
        assert _copy(client, target_days=["Monday"]).status_code == 400  # same as source
        assert _copy(client, target_days=["Funday"]).status_code == 400
        assert _copy(client, target_days=["Tuesday"], shift_ids="1").status_code == 400
        assert client.post("/api/shifts/copy", json={"position": "Pilot", "source_day": "Monday", "target_days": ["Tuesday"]}).status_code == 400


class TestClearFilters:
    def test_clear_by_position_and_day(self, client, make_employee, make_shift):
        alice = make_employee(positions=("Cashier", "Food"))
        make_shift(alice["id"], position="Cashier", day="Monday")
        make_shift(alice["id"], position="Cashier", day="Tuesday")
        make_shift(alice["id"], position="Food", day="Monday", start="18:00", end="21:00")
        assert client.delete("/api/shifts?position=Cashier&day=Monday").get_json()["deleted_count"] == 1
        remaining = client.get("/api/shifts").get_json()
        assert sorted((s["position"], s["day_of_week"]) for s in remaining) == [("Cashier", "Tuesday"), ("Food", "Monday")]
        assert client.delete("/api/shifts?position=Cashier").get_json()["deleted_count"] == 1
        assert client.delete("/api/shifts?day=Funday").status_code == 400


class TestExports:
    def test_master_csv(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice", positions=("Cashier", "Food"))
        make_shift(alice["id"], position="Cashier", day="Monday", start="09:00", end="17:00")
        make_shift(alice["id"], position="Food", day="Tuesday", start="09:00", end="13:00")
        response = client.get("/export/master.csv")
        assert response.status_code == 200
        assert response.mimetype == "text/csv"
        assert "master-schedule.csv" in response.headers["Content-Disposition"]
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        assert rows[0][:3] == ["Employee", "Position", "Monday"]
        assert rows[1][0] == "Alice" and rows[1][1] == "Cashier" and rows[1][2] == "9:00 AM–5:00 PM (7h 30m)"
        assert rows[1][-2:] == ["8.00", "7.50"]
        assert rows[2][1] == "Food" and rows[2][3] == "9:00 AM–1:00 PM (4h)"
        assert rows[-1][0] == "Total" and rows[-1][-2:] == ["12.00", "11.50"]

    def test_shifts_csv(self, client, make_employee, make_shift):
        alice = make_employee(name="Alice")
        make_shift(alice["id"], day="Tuesday", start="09:00", end="15:00")
        make_shift(alice["id"], day="Monday", start="12:00", end="14:00")
        rows = list(csv.reader(io.StringIO(client.get("/export/shifts.csv").get_data(as_text=True))))
        assert rows[0] == ["Day", "Employee", "Position", "Start", "End", "Duration minutes", "Break minutes", "Paid minutes"]
        assert rows[1] == ["Monday", "Alice", "Cashier", "12:00", "14:00", "120", "0", "120"]  # sorted by weekday
        assert rows[2] == ["Tuesday", "Alice", "Cashier", "09:00", "15:00", "360", "30", "330"]

    def test_empty_exports(self, client):
        assert client.get("/export/master.csv").get_data(as_text=True).count("\n") == 2  # header + total
        assert client.get("/export/shifts.csv").get_data(as_text=True).count("\n") == 1


class TestMasterCoverage:
    def test_coverage_buckets(self, app, client, make_employee, make_shift):
        from app.db import session_scope
        from app.services.scheduling import build_master_schedule

        alice = make_employee(name="Alice", positions=("Cashier", "Food"))
        bob = make_employee(name="Bob")
        make_shift(alice["id"], position="Cashier", start="09:00", end="13:00")
        make_shift(bob["id"], position="Cashier", start="11:00", end="15:00")
        make_shift(alice["id"], position="Food", day="Tuesday", start="09:00", end="10:00")
        with session_scope() as session:
            data = build_master_schedule(session)
        monday = data["coverage"]["Monday"]
        assert monday["shift_count"] == 2 and monday["scheduled_minutes"] == 480
        assert monday["buckets"] == [1, 1, 2, 2, 1, 1, 0, 0, 0, 0, 0, 0]  # 9-21 in hour buckets
        assert data["coverage"]["Tuesday"]["buckets"][0] == 1
        assert data["coverage"]["Wednesday"]["shift_count"] == 0
        assert data["max_headcount"] == 2
        html = client.get("/master").get_data(as_text=True)
        assert 'class="coverage-row"' in html
