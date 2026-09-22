import pytest

from app.constants import EMPLOYEE_COLOR_PALETTE


def test_create_and_list(client, make_employee):
    created = make_employee(name="Alice", positions=("Cashier", "Food"))
    assert created["positions"] == ["Cashier", "Food"]
    assert created["availability"] == "Open"
    assert created["removed_shifts"] == 0

    listed = client.get("/api/employees").get_json()
    assert [employee["name"] for employee in listed] == ["Alice"]
    assert client.get(f"/api/employees/{created['id']}").get_json()["name"] == "Alice"


def test_filter_by_position(client, make_employee):
    make_employee(name="Alice", positions=("Cashier",))
    make_employee(name="Bob", positions=("Food",))
    names = [employee["name"] for employee in client.get("/api/employees?position=Food").get_json()]
    assert names == ["Bob"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": " ", "employment_type": "Full-Time", "positions": ["Cashier"]}, "Name is required"),
        ({"name": "A", "employment_type": "Casual", "positions": ["Cashier"]}, "Employment type"),
        ({"name": "A", "employment_type": "Full-Time", "positions": []}, "At least one position"),
        ({"name": "A", "employment_type": "Full-Time", "positions": ["Pilot"]}, "Unknown position: Pilot"),
        ({"name": "A", "employment_type": "Full-Time", "positions": ["Cashier"], "color": "#zzzzzz"}, "hex value"),
    ],
)
def test_validation_errors(client, payload, message):
    response = client.post("/api/employees", json=payload)
    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_non_json_body_rejected(client):
    response = client.post("/api/employees", data="not json", content_type="text/plain")
    assert response.status_code == 400


def test_not_found(client):
    assert client.get("/api/employees/999").status_code == 404
    assert client.delete("/api/employees/999").status_code == 404
    response = client.put("/api/employees/999", json={"name": "X", "employment_type": "Full-Time", "positions": ["Cashier"]})
    assert response.status_code == 404


class TestAvailability:
    @pytest.mark.parametrize(
        "junk",
        ["whenever lol", "[1,2]", {"Funday": "09:00-12:00"}, {"Monday": "13:00-09:00"}, {"Monday": 42}, {"Monday": "9-5"}],
    )
    def test_junk_rejected(self, client, junk):
        response = client.post(
            "/api/employees",
            json={"name": "A", "employment_type": "Full-Time", "positions": ["Cashier"], "availability": junk},
        )
        assert response.status_code == 400, response.get_json()

    def test_canonical_form(self, make_employee):
        employee = make_employee(
            availability='{"Monday": "9:00-13:00", "Tuesday": "open", "Wednesday": null, "Sunday": "closed", "Friday": [{"start": "10:00", "end": "12:00"}, "14:00-18:00"]}'
        )
        assert employee["availability"] == {
            "Monday": ["09:00-13:00"],
            "Friday": ["10:00-12:00", "14:00-18:00"],
            "Sunday": "Unavailable",
        }

    @pytest.mark.parametrize("value", [None, "", "Open", "open", {"Monday": "Open"}, {}])
    def test_open_forms_collapse(self, make_employee, value):
        assert make_employee(availability=value)["availability"] == "Open"


class TestColor:
    def test_auto_assigned_from_palette(self, make_employee):
        first = make_employee(name="A")
        second = make_employee(name="B")
        assert first["color"] == EMPLOYEE_COLOR_PALETTE[0]
        assert second["color"] == EMPLOYEE_COLOR_PALETTE[1]

    def test_auto_assignment_skips_used(self, make_employee):
        make_employee(name="A", color=EMPLOYEE_COLOR_PALETTE[0])
        assert make_employee(name="B")["color"] == EMPLOYEE_COLOR_PALETTE[1]

    def test_normalised_to_uppercase(self, make_employee):
        assert make_employee(color="#abcdef")["color"] == "#ABCDEF"

    def test_duplicate_is_clean_409(self, client, make_employee):
        make_employee(name="A", color="#ABCDEF")
        response = client.post(
            "/api/employees",
            json={"name": "B", "employment_type": "Full-Time", "positions": ["Cashier"], "color": "#ABCDEF"},
        )
        assert response.status_code == 409
        assert "already used" in response.get_json()["error"]
        # The failed flush must not poison later requests.
        assert client.get("/api/employees").status_code == 200
        assert len(client.get("/api/employees").get_json()) == 1


class TestUpdateAndDelete:
    def test_update(self, client, make_employee):
        employee = make_employee(name="Alice")
        response = client.put(
            f"/api/employees/{employee['id']}",
            json={"name": "Alicia", "employment_type": "Part-Time", "positions": ["Cashier", "Food"]},
        )
        assert response.status_code == 200
        assert response.get_json()["name"] == "Alicia"
        assert response.get_json()["positions"] == ["Cashier", "Food"]

    def test_update_keeps_color_when_omitted(self, client, make_employee):
        employee = make_employee(color="#123456")
        response = client.put(
            f"/api/employees/{employee['id']}",
            json={"name": "Alice", "employment_type": "Full-Time", "positions": ["Cashier"]},
        )
        assert response.get_json()["color"] == "#123456"

    def test_removing_position_with_shifts_requires_confirmation(self, client, make_employee, make_shift):
        employee = make_employee(positions=("Cashier", "Food"))
        make_shift(employee["id"], position="Cashier")
        payload = {"name": "Alice", "employment_type": "Full-Time", "positions": ["Food"]}

        refused = client.put(f"/api/employees/{employee['id']}", json=payload)
        assert refused.status_code == 409
        assert refused.get_json()["code"] == "orphaned_shifts"
        assert refused.get_json()["shift_count"] == 1
        assert len(client.get("/api/shifts").get_json()) == 1

        confirmed = client.put(f"/api/employees/{employee['id']}", json={**payload, "remove_orphaned_shifts": True})
        assert confirmed.status_code == 200
        assert confirmed.get_json()["removed_shifts"] == 1
        assert client.get("/api/shifts").get_json() == []

    def test_delete_cascades_to_shifts(self, client, make_employee, make_shift):
        employee = make_employee()
        make_shift(employee["id"])
        assert client.delete(f"/api/employees/{employee['id']}").status_code == 200
        assert client.get("/api/employees").get_json() == []
        assert client.get("/api/shifts").get_json() == []
