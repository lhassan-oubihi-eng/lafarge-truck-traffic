from app.services.monitoring import MonitoringService


def test_get_system_status_returns_expected_structure():
    svc = MonitoringService()
    status = svc.get_system_status()
    assert isinstance(status, dict)
    assert "cpu_usage_percent" in status
    assert "memory_usage_percent" in status
    assert "active_instances" in status
    assert "s3_storage_mb" in status
    assert "api_latency_p95_seconds" in status
    assert "overall_status" in status
    assert status["overall_status"] in ("healthy", "degraded", "critical")
    assert isinstance(status["cpu_usage_percent"], float)
    assert isinstance(status["active_instances"], int)


def test_get_traffic_history_returns_24_entries():
    svc = MonitoringService()
    history = svc.get_traffic_history(hours=24)
    assert len(history) == 24
    for entry in history:
        assert "timestamp" in entry
        assert "entries" in entry
        assert "hour" in entry
        assert isinstance(entry["entries"], int)
        assert entry["entries"] >= 0


def test_get_cpu_usage_in_range():
    svc = MonitoringService()
    for _ in range(50):
        cpu = svc.get_cpu_usage()
        assert 0.0 <= cpu <= 100.0


def test_get_memory_usage_in_range():
    svc = MonitoringService()
    for _ in range(50):
        mem = svc.get_memory_usage()
        assert 0.0 <= mem <= 100.0


def test_get_active_instances_returns_positive_int():
    svc = MonitoringService()
    for _ in range(20):
        instances = svc.get_active_instances()
        assert isinstance(instances, int)
        assert 1 <= instances <= 10


def test_get_s3_storage_usage_mb_returns_positive_float():
    svc = MonitoringService()
    for _ in range(20):
        mb = svc.get_s3_storage_usage_mb()
        assert isinstance(mb, float)
        assert mb >= 0


def test_get_api_latency_p95_returns_positive_float():
    svc = MonitoringService()
    for _ in range(20):
        latency = svc.get_api_latency_p95()
        assert isinstance(latency, float)
        assert latency >= 0.01
