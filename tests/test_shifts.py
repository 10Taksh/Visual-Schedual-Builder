import pytest


def test_create_shift(make_employee, make_shift):
    employee = make_employee()
    shift = make_shift(employee["id"], start="09:00", end="17:00")
    assert shift["employee_name"] == "Alice"
    assert shift["start_time_display"] == "9:00 AM"
    assert shift["end_time_display"] == "5:00 PM"
    assert shift["duration_minutes"] == 480


@pytest.mark.parametrize(
    ("start", "end", "break_deduction", "paid"),
    [
        ("09:00", "13:00", False, 240),  # 4h: no break
        ("09:00", "13:45", False, 285),  # 4h45: still under the threshold
        ("09:00", "14:00", True, 270),   # exactly 5h: break kicks in
        ("09:00", "17:00", True, 450),
    ],
)
def test_break_rule(make_employee, make_shift, start, end, break_deduction, paid):
    employee = make_employee()
    shift = make_shift(employee["id"], start=start, end=end)
    assert shift["break_deduction"] is break_deduction
    assert shift["paid_minutes"] == paid


class TestValidation:
    def test_requires_employee(self, client):
        response = client.post("/api/shifts", json={"position": "Cashier", "day_of_week": "Monday", "start_time": "09:00", "end_time": "10:00"})
        assert response.status_code == 400
        assert "Employee" in response.get_json()["error"]

    def test_unknown_employee(self, make_shift):
        assert make_shift(999, expect=404)["error"] == "Employee not found"

    def test_invalid_position_and_day(self, make_employee, make_shift):
        employee = make_employee()
        assert "Position" in make_shift(employee["id"], position="Supervisor", expect=400)["error"]
        assert "Day" in make_shift(employee["id"], day="Funday", expect=400)["error"]

    def test_end_before_start(self, make_employee, make_shift):
        employee = make_employee()
        assert "valid start and end" in make_shift(employee["id"], start="12:00", end="10:00", expect=400)["error"]

    def test_too_short(self, make_employee, make_shift):
        employee = make_employee()
        assert "at least 30 minutes" in make_shift(employee["id"], start="10:00", end="10:15", expect=400)["error"]

    def test_employee_not_in_position(self, make_employee, make_shift):
        employee = make_employee(positions=("Cashier",))
        assert "not assigned to Food" in make_shift(employee["id"], position="Food", expect=400)["error"]


class TestConflicts:
    def test_outside_store_hours(self, make_employee, make_shift):
        employee = make_employee()
        error = make_shift(employee["id"], start="08:00", end="12:00", expect=409)["error"]
        assert "store hours" in error

    def test_store_closed(self, client, make_employee, make_shift):
        settings = client.get("/api/settings").get_json()
        settings["operating_hours"]["Sunday"] = None
        assert client.put("/api/settings", json=settings).status_code == 200
        employee = make_employee()
        assert "closed on Sunday" in make_shift(employee["id"], day="Sunday", expect=409)["error"]

    def test_outside_availability(self, make_employee, make_shift):
        employee = make_employee(availability={"Monday": "09:00-13:00", "Sunday": "Unavailable"})
        make_shift(employee["id"], day="Monday", start="09:00", end="13:00")
        assert "unavailable" in make_shift(employee["id"], day="Monday", start="13:00", end="15:00", expect=409)["error"]
        assert "unavailable" in make_shift(employee["id"], day="Sunday", start="09:00", end="12:00", expect=409)["error"]
        make_shift(employee["id"], day="Tuesday", start="09:00", end="21:00")  # unspecified day is open

    def test_overlap_across_positions(self, make_employee, make_shift):
        employee = make_employee(positions=("Cashier", "Food"))
        make_shift(employee["id"], position="Cashier", start="09:00", end="13:00")
        error = make_shift(employee["id"], position="Food", start="12:00", end="15:00", expect=409)["error"]
        assert "already scheduled as Cashier" in error
        make_shift(employee["id"], position="Food", start="13:00", end="15:00")  # touching is fine

    def test_update_excludes_itself_from_overlap(self, client, make_employee, make_shift):
        employee = make_employee()
        shift = make_shift(employee["id"], start="09:00", end="13:00")
        response = client.put(
            f"/api/shifts/{shift['id']}",
            json={"employee_id": employee["id"], "position": "Cashier", "day_of_week": "Monday", "start_time": "10:00", "end_time": "14:00"},
        )
        assert response.status_code == 200
        assert response.get_json()["start_time"] == "10:00"


class TestListDelete:
    def test_filter_by_position(self, client, make_employee, make_shift):
        employee = make_employee(positions=("Cashier", "Food"))
        make_shift(employee["id"], position="Cashier", day="Monday")
        make_shift(employee["id"], position="Food", day="Tuesday")
        assert [s["position"] for s in client.get("/api/shifts?position=Food").get_json()] == ["Food"]
        assert len(client.get("/api/shifts").get_json()) == 2

    def test_delete(self, client, make_employee, make_shift):
        employee = make_employee()
        shift = make_shift(employee["id"])
        assert client.delete(f"/api/shifts/{shift['id']}").status_code == 200
        assert client.delete(f"/api/shifts/{shift['id']}").status_code == 404
        assert client.put(f"/api/shifts/{shift['id']}", json={"employee_id": employee["id"], "position": "Cashier", "day_of_week": "Monday", "start_time": "09:00", "end_time": "10:00"}).status_code == 404

    def test_clear(self, client, make_employee, make_shift):
        employee = make_employee()
        make_shift(employee["id"], day="Monday")
        make_shift(employee["id"], day="Tuesday")
        response = client.delete("/api/shifts")
        assert response.get_json()["deleted_count"] == 2
        assert client.get("/api/shifts").get_json() == []
        assert client.get("/api/employees").status_code == 200  # employees untouched
