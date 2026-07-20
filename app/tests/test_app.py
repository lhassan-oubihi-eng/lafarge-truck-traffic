import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import runpy

from app.app import (
    APP_VERSION,
    TRUCKS_REGISTRY,
    app,
    get_secret_safely,
    load_runtime_secrets,
    _seed_mock_data,
)

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
    with patch("app.app._get_s3_service") as mock_s3:
        mock_s3.return_value.list_truck_logs.return_value = []
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


def test_get_secret_safely_returns_empty_on_boto_error():
    from botocore.exceptions import ClientError

    with patch("app.app.boto3.session.Session") as mock_session_cls:
        mock_client = mock_session_cls.return_value.client.return_value
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException"}}, "get_secret_value"
        )
        result = get_secret_safely("test-secret")
        assert result == {}


def test_seed_mock_data_noop_when_registry_not_empty():
    TRUCKS_REGISTRY.clear()
    client.post("/api/trucks/enter", params={"plate": "TEST-001"})
    assert len(TRUCKS_REGISTRY) == 1
    _seed_mock_data(count=12)
    assert len(TRUCKS_REGISTRY) == 1


def test_api_metrics_s3_error_falls_back_to_registry():
    with patch("app.app._get_s3_service") as mock_s3:
        mock_s3.return_value.list_truck_logs.side_effect = Exception("S3 down")
        TRUCKS_REGISTRY.clear()
        client.post("/api/trucks/enter", params={"plate": "FALLBACK-001"})
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["business"]["total_trucks"] >= 1


def test_truck_exit_resolves_plate_from_s3_entry_log():
    with patch("app.app._get_s3_service") as mock_s3:
        mock_instance = mock_s3.return_value
        mock_instance.list_truck_logs.return_value = [
            {
                "event": "truck_entry",
                "truck_id": "s3-truck-001",
                "license_plate": "S3-0001",
                "event_time": "2026-07-20T12:00:00",
                "gate_id": "GATE-A",
                "status": "APPROVED",
            }
        ]
        TRUCKS_REGISTRY.clear()
        response = client.post("/api/trucks/exit", params={"truck_id": "s3-truck-001"})
        assert response.status_code == 200
        assert response.json()["message"] == "Sortie du camion enregistrée"


def test_load_runtime_secrets_raises_on_missing_env():
    original = os.environ.pop("DB_HOST", None)
    try:
        load_runtime_secrets.cache_clear()
        with patch("app.app.get_secret_safely", return_value={}):
            with pytest.raises(RuntimeError, match="DB_HOST"):
                load_runtime_secrets()
    finally:
        if original is not None:
            os.environ["DB_HOST"] = original


def test_get_secret_safely_returns_secret_data():
    with patch("app.app.boto3.session.Session") as mock_session_cls:
        mock_client = mock_session_cls.return_value.client.return_value
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"DB_HOST": "localhost", "DB_PORT": "5432"}'
        }
        result = get_secret_safely("test-secret")
        assert result == {"DB_HOST": "localhost", "DB_PORT": "5432"}


def test_load_runtime_secrets_success():
    load_runtime_secrets.cache_clear()
    with (
        patch("app.app.get_secret_safely", return_value={}),
        patch.dict(
            os.environ,
            {
                "DB_HOST": "localhost",
                "DB_PORT": "5432",
                "DB_NAME": "testdb",
                "DB_USER": "testuser",
                "DB_PASSWORD": "testpass",  # pragma: allowlist secret
                "AWS_ACCESS_KEY_ID": "",
                "AWS_SECRET_ACCESS_KEY": "",
            },
        ),
    ):
        result = load_runtime_secrets()
        assert result["DB_HOST"] == "localhost"
        assert result["DB_PORT"] == "5432"
        assert result["DB_NAME"] == "testdb"
        assert os.environ["DB_HOST"] == "localhost"


def test_seed_mock_data_populates_registry():
    TRUCKS_REGISTRY.clear()
    _seed_mock_data(count=5)
    assert len(TRUCKS_REGISTRY) == 5
    for truck_id, truck in TRUCKS_REGISTRY.items():
        assert truck["status"] == "on_site"
        assert truck["exit_time"] is None


def test_api_metrics_with_s3_logs_computes_counts():
    with patch("app.app._get_s3_service") as mock_s3:
        mock_instance = mock_s3.return_value
        mock_instance.list_truck_logs.return_value = [
            {
                "event": "truck_entry",
                "truck_id": "t1",
                "license_plate": "PL-1",
                "event_time": "2026-07-20T10:00:00",
                "gate_id": "GATE-A",
                "status": "APPROVED",
            },
            {
                "event": "truck_entry",
                "truck_id": "t2",
                "license_plate": "PL-2",
                "event_time": "2026-07-20T11:00:00",
                "gate_id": "GATE-A",
                "status": "APPROVED",
            },
            {
                "event": "truck_exit",
                "truck_id": "t1",
                "license_plate": "PL-1",
                "event_time": "2026-07-20T12:00:00",
                "gate_id": "GATE-A",
                "status": "COMPLETED",
            },
        ]
        TRUCKS_REGISTRY.clear()
        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["business"]["total_trucks"] == 3
        assert data["business"]["trucks_on_site"] == 1
        assert data["business"]["entries_today"] == 2
        assert data["business"]["exits_today"] == 1
