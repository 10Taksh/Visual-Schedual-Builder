import pytest

from app import create_app
from app.config import TestingConfig


@pytest.fixture
def app():
    # Each test gets a fresh in-memory database via create_app -> init_engine -> bootstrap.
    return create_app(TestingConfig)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_employee(client):
    """Create an employee through the API and return its JSON."""

    def _make(name="Alice", positions=("Cashier",), employment_type="Full-Time", **extra):
        response = client.post(
            "/api/employees",
            json={"name": name, "employment_type": employment_type, "positions": list(positions), **extra},
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()

    return _make


@pytest.fixture
def make_shift(client):
    def _make(employee_id, position="Cashier", day="Monday", start="09:00", end="17:00", expect=201):
        response = client.post(
            "/api/shifts",
            json={"employee_id": employee_id, "position": position, "day_of_week": day, "start_time": start, "end_time": end},
        )
        assert response.status_code == expect, response.get_json()
        return response.get_json()

    return _make
