"""
Monitoring Service for Lafarge Truck Traffic.
Aggregates system health metrics (CPU, Memory, Instances, S3 usage, API latency)
and exposes them for the dashboard and Prometheus scraping.
"""

import os
import random
import secrets
import logging
from datetime import datetime, timezone, timedelta

from prometheus_client import Gauge

logger = logging.getLogger(__name__)


SYSTEM_CPU_USAGE = Gauge(
    "system_cpu_usage_percent",
    "Simulated CPU usage percentage across active instances",
)

SYSTEM_MEMORY_USAGE = Gauge(
    "system_memory_usage_percent",
    "Simulated memory usage percentage across active instances",
)

SYSTEM_ACTIVE_INSTANCES = Gauge(
    "system_active_instances",
    "Number of healthy EC2 instances currently serving traffic",
)

S3_STORAGE_USAGE_BYTES = Gauge(
    "s3_storage_usage_bytes",
    "Total bytes stored in the truck traffic logs S3 bucket",
)

API_LATENCY_P95_SECONDS = Gauge(
    "api_latency_p95_seconds",
    "P95 request latency in seconds measured across all endpoints",
)


class MonitoringService:
    """Aggregates simulated platform health metrics.

    In production, these values would be sourced from:
        - CPU/Memory : CloudWatch or Node Exporter
        - Instances  : AWS EC2 DescribeInstances / ASG
        - S3         : CloudWatch S3 metrics or s3 list-objects
        - Latency    : Prometheus histogram quantile
    """

    def __init__(self):
        self._cpu_base = random.uniform(30, 55)
        self._memory_base = random.uniform(40, 60)
        self._latency_base = random.uniform(0.08, 0.25)

    def get_cpu_usage(self) -> float:
        value = self._cpu_base + random.uniform(-5, 5)
        value = max(0.0, min(100.0, value))
        return round(value, 1)

    def get_memory_usage(self) -> float:
        value = self._memory_base + random.uniform(-3, 3)
        value = max(0.0, min(100.0, value))
        return round(value, 1)

    def get_active_instances(self) -> int:
        return secrets.SystemRandom().choice([2, 2, 3, 3, 3, 4])

    def get_s3_storage_usage_mb(self) -> float:
        base_mb = 128.0
        variation = random.uniform(-5, 10)
        return round(max(0, base_mb + variation), 1)

    def get_api_latency_p95(self) -> float:
        value = self._latency_base + random.uniform(-0.03, 0.05)
        return round(max(0.01, value), 3)

    def get_traffic_history(self, hours: int = 24) -> list[dict]:
        now = datetime.now(timezone.utc)
        data = []
        base_count = secrets.SystemRandom().randint(5, 12)
        for i in range(hours):
            # Simulate diurnal pattern: more traffic during day (8-18)
            hour = (now - timedelta(hours=hours - 1 - i)).hour
            if 8 <= hour <= 12:
                multiplier = random.uniform(1.5, 2.5)
            elif 13 <= hour <= 18:
                multiplier = random.uniform(1.2, 2.0)
            elif 19 <= hour <= 22:
                multiplier = random.uniform(0.8, 1.2)
            else:
                multiplier = random.uniform(0.2, 0.6)
            count = int(base_count * multiplier * random.uniform(0.8, 1.2))
            timestamp = (now - timedelta(hours=hours - 1 - i)).isoformat()
            data.append(
                {
                    "timestamp": timestamp,
                    "entries": count,
                    "hour": hour,
                }
            )
        return data

    def get_system_status(self) -> dict:
        cpu = self.get_cpu_usage()
        memory = self.get_memory_usage()
        instances = self.get_active_instances()
        s3_mb = self.get_s3_storage_usage_mb()
        latency = self.get_api_latency_p95()

        SYSTEM_CPU_USAGE.set(cpu)
        SYSTEM_MEMORY_USAGE.set(memory)
        SYSTEM_ACTIVE_INSTANCES.set(instances)
        S3_STORAGE_USAGE_BYTES.set(s3_mb * 1024 * 1024)
        API_LATENCY_P95_SECONDS.set(latency)

        status = "healthy"
        if cpu > 85 or memory > 85:
            status = "degraded"
        if cpu > 95 or memory > 95:
            status = "critical"

        return {
            "cpu_usage_percent": cpu,
            "memory_usage_percent": memory,
            "active_instances": instances,
            "s3_storage_mb": s3_mb,
            "api_latency_p95_seconds": latency,
            "overall_status": status,
        }


monitoring_service = MonitoringService()
