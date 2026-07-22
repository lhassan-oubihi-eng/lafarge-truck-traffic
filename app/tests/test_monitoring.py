import json
from unittest.mock import patch, MagicMock

from app.services.monitoring import (
    LocalMonitoringService,
    AWSMonitoringService,
    create_monitoring_service,
    LATENCY_HISTORY,
)


# ==============================================================================
# LocalMonitoringService tests
# ==============================================================================


@patch("app.services.monitoring.LocalMonitoringService._read_cpu_stat")
def test_get_system_status_returns_expected_structure(mock_cpu):
    mock_cpu.return_value = (50_000_000, 100.0)
    svc = LocalMonitoringService()
    svc._last_cpu_time = 0
    svc._last_cpu_time_monotonic = 0.0

    status = svc.get_system_status()
    assert isinstance(status, dict)
    assert "cpu_usage_percent" in status
    assert "memory_usage_percent" in status
    assert "active_instances" in status
    assert "s3_storage_mb" in status
    assert "api_latency_p95_seconds" in status
    assert "overall_status" in status
    assert "environment" in status
    assert status["environment"] == "local"
    assert "node_label" in status
    assert "node_subtitle" in status
    assert status["overall_status"] in ("healthy", "degraded", "critical")
    assert isinstance(status["cpu_usage_percent"], float)
    assert isinstance(status["active_instances"], int)


def test_get_traffic_history_returns_24_entries():
    svc = LocalMonitoringService()
    history = svc.get_traffic_history(hours=24)
    assert len(history) == 24
    for entry in history:
        assert "timestamp" in entry
        assert "entries" in entry
        assert "hour" in entry
        assert isinstance(entry["entries"], int)
        assert entry["entries"] >= 0


@patch("app.services.monitoring.LocalMonitoringService._read_cpu_stat")
def test_get_cpu_usage_returns_zero_when_no_data(mock_cpu):
    mock_cpu.return_value = (0, 0.0)
    svc = LocalMonitoringService()
    cpu = svc.get_cpu_usage()
    assert cpu == 0.0


@patch("app.services.monitoring.LocalMonitoringService._read_cpu_stat")
def test_get_cpu_usage_calculates_percentage(mock_cpu):
    mock_cpu.return_value = (500_000, 1.0)
    svc = LocalMonitoringService()
    svc._last_cpu_time = 0
    svc._last_cpu_time_monotonic = 0.0
    cpu = svc.get_cpu_usage()
    assert cpu == 50.0  # (500k usec / 1M) / 1.0s * 100 = 50%


@patch("builtins.open", side_effect=FileNotFoundError)
def test_get_memory_usage_returns_zero_when_no_cgroup(mock_open):
    svc = LocalMonitoringService()
    mem = svc.get_memory_usage()
    assert mem == 0.0


@patch("app.services.monitoring.socket.socket")
def test_get_active_instances_returns_zero_when_no_socket(mock_socket):
    mock_socket.return_value.connect.side_effect = FileNotFoundError
    svc = LocalMonitoringService()
    instances = svc.get_active_instances()
    assert instances == 0
    assert isinstance(instances, int)


@patch("app.services.monitoring.socket")
def test_get_active_instances_parses_docker_response(mock_socket_mod):
    mock_socket_mod.AF_UNIX = 1
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n",
        json.dumps([{"Id": "abc"}, {"Id": "def"}]).encode(),
        b"",
    ]
    mock_socket_mod.socket.return_value = mock_sock
    svc = LocalMonitoringService()
    instances = svc.get_active_instances()
    assert instances == 2


@patch("app.services.monitoring.socket")
def test_get_active_instances_with_many_containers(mock_socket_mod):
    mock_socket_mod.AF_UNIX = 1
    mock_sock = MagicMock()
    containers = [{"Id": f"id{i}"} for i in range(8)]
    mock_sock.recv.side_effect = [
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n",
        json.dumps(containers).encode(),
        b"",
    ]
    mock_socket_mod.socket.return_value = mock_sock
    svc = LocalMonitoringService()
    assert svc.get_active_instances() == 8


def test_get_s3_storage_usage_mb_returns_zero_when_no_s3():
    svc = LocalMonitoringService()
    mb = svc.get_s3_storage_usage_mb()
    assert isinstance(mb, float)
    assert mb >= 0


def test_get_api_latency_p95_returns_zero_when_no_data():
    LATENCY_HISTORY.clear()
    svc = LocalMonitoringService()
    latency = svc.get_api_latency_p95()
    assert latency == 0.0


def test_observe_latency_and_p95():
    LATENCY_HISTORY.clear()
    svc = LocalMonitoringService()
    for _ in range(100):
        svc.observe_latency(0.1)
    assert svc.get_api_latency_p95() == 0.1


def test_local_node_labels():
    svc = LocalMonitoringService()
    status = svc.get_system_status()
    assert status["node_label"] == "containers"
    assert status["node_subtitle"] == "Running containers"


# ==============================================================================
# AWSMonitoringService tests
# ==============================================================================


def test_aws_get_system_status_returns_expected_structure():
    svc = AWSMonitoringService()
    status = svc.get_system_status()
    assert isinstance(status, dict)
    assert "cpu_usage_percent" in status
    assert "memory_usage_percent" in status
    assert "active_instances" in status
    assert "s3_storage_mb" in status
    assert "api_latency_p95_seconds" in status
    assert "overall_status" in status
    assert "environment" in status
    assert status["environment"] == "aws"
    assert "node_label" in status
    assert "node_subtitle" in status


def test_aws_get_traffic_history_returns_24_entries():
    svc = AWSMonitoringService()
    history = svc.get_traffic_history(hours=24)
    assert len(history) == 24
    for entry in history:
        assert "timestamp" in entry
        assert "entries" in entry
        assert "hour" in entry
        assert isinstance(entry["entries"], int)
        assert entry["entries"] >= 0


def test_aws_cpu_usage_returns_zero_on_failure():
    svc = AWSMonitoringService()
    cpu = svc.get_cpu_usage()
    assert cpu == 0.0


def test_aws_memory_usage_returns_zero_on_failure():
    svc = AWSMonitoringService()
    mem = svc.get_memory_usage()
    assert mem == 0.0


@patch("boto3.client")
def test_aws_active_instances_returns_zero_on_failure(mock_boto):
    mock_boto.side_effect = Exception("AWS unavailable")
    svc = AWSMonitoringService()
    instances = svc.get_active_instances()
    assert instances == 0


@patch("boto3.client")
def test_aws_s3_storage_returns_zero_on_failure(mock_boto):
    mock_boto.side_effect = Exception("AWS unavailable")
    svc = AWSMonitoringService()
    mb = svc.get_s3_storage_usage_mb()
    assert mb == 0.0


def test_aws_api_latency_returns_zero_when_no_alb():
    svc = AWSMonitoringService()
    latency = svc.get_api_latency_p95()
    assert latency == 0.0


def test_aws_node_labels():
    svc = AWSMonitoringService()
    status = svc.get_system_status()
    assert status["node_label"] == "instances"
    assert status["node_subtitle"] == "EC2 serving traffic"


# ==============================================================================
# Auto-detection tests
# ==============================================================================


@patch.dict("os.environ", {"AWS_ENDPOINT_URL": "http://localstack:4566"})
def test_create_monitoring_service_local():
    svc = create_monitoring_service()
    assert isinstance(svc, LocalMonitoringService)


@patch.dict("os.environ", {}, clear=True)
def test_create_monitoring_service_aws():
    svc = create_monitoring_service()
    assert isinstance(svc, AWSMonitoringService)
