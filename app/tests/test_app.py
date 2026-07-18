from fastapi.testclient import TestClient
from unittest.mock import patch
import runpy

from app.app import APP_VERSION, TRUCKS_REGISTRY, app

client = TestClient(app)


def setup_function():
    TRUCKS_REGISTRY.clear()


def test_healthz_returns_ok():
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "timestamp" in response.json()


def test_metrics_endpoint_returns_prometheus_text():
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text


def test_dashboard_shows_empty_state_and_version():
    response = client.get("/")

    assert response.status_code == 200
    assert "No trucks recorded yet" in response.text
    assert f"v{APP_VERSION}" in response.text


def test_list_trucks_returns_empty_list():
    response = client.get("/api/trucks")

    assert response.status_code == 200
    assert response.json() == []


def test_truck_enter_and_exit_flow():
    enter_response = client.post("/api/trucks/enter", params={"plate": "ABC-123"})

    assert enter_response.status_code == 200
    assert enter_response.json()["message"] == "Camion enregistré"

    truck_id = enter_response.json()["truck_id"]
    assert truck_id in TRUCKS_REGISTRY
    assert TRUCKS_REGISTRY[truck_id]["status"] == "on_site"

    exit_response = client.post("/api/trucks/exit", params={"truck_id": truck_id})
    assert exit_response.status_code == 200
    assert exit_response.json()["message"] == "Sortie du camion enregistrée"
    assert TRUCKS_REGISTRY[truck_id]["status"] == "exited"
    assert TRUCKS_REGISTRY[truck_id]["exit_time"] is not None


def test_running_app_module_as_main_invokes_uvicorn():
    with (
        patch("uvicorn.run") as mock_run,
        patch(
            "prometheus_client.registry.REGISTRY.register",
            side_effect=lambda collector: None,
        ),
    ):
        runpy.run_module("app.app", run_name="__main__")

    mock_run.assert_called_once_with(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


def test_truck_exit_not_found_returns_404():
    response = client.post("/api/trucks/exit", params={"truck_id": "missing"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Camion introuvable"


def test_dashboard_returns_html_template():
    response = client.get("/")
    assert response.status_code == 200
    assert "Lafarge" in response.text
    assert "Control Center" in response.text
    assert "chart.js" in response.text
    assert "/api/metrics" in response.text


def test_api_metrics_returns_truck_data():
    enter_response = client.post("/api/trucks/enter", params={"plate": "ZZZ-999"})
    assert enter_response.status_code == 200
    truck_id = enter_response.json()["truck_id"]

    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["business"]["total_trucks"] >= 1
    assert data["business"]["trucks_on_site"] >= 1
    assert any(m["license_plate"] == "ZZZ-999" for m in data["recent_movements"])
    assert "platform" in data
    assert "traffic_history" in data


def test_truck_exit_already_exited_returns_409():
    enter_response = client.post("/api/trucks/enter", params={"plate": "XYZ-789"})
    truck_id = enter_response.json()["truck_id"]

    first_exit = client.post("/api/trucks/exit", params={"truck_id": truck_id})
    assert first_exit.status_code == 200

    second_exit = client.post("/api/trucks/exit", params={"truck_id": truck_id})
    assert second_exit.status_code == 409
    assert second_exit.json()["detail"] == "Camion déjà sorti"
