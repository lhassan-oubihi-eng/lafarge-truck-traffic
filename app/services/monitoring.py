"""
Monitoring Service for Lafarge Truck Traffic.
Provides system health metrics from real sources:
- Local: Docker cgroup stats + LocalStack S3 + Docker API
- AWS: CloudWatch + EC2 + S3 + ALB metrics
"""

import json
import os
import random
import socket
import time
import logging
import collections
from datetime import datetime, timezone, timedelta

from prometheus_client import Gauge

logger = logging.getLogger(__name__)


SYSTEM_CPU_USAGE = Gauge(
    "system_cpu_usage_percent",
    "CPU usage percentage across active instances",
)

SYSTEM_MEMORY_USAGE = Gauge(
    "system_memory_usage_percent",
    "Memory usage percentage across active instances",
)

SYSTEM_ACTIVE_INSTANCES = Gauge(
    "system_active_instances",
    "Number of healthy instances currently serving traffic",
)

S3_STORAGE_USAGE_BYTES = Gauge(
    "s3_storage_usage_bytes",
    "Total bytes stored in the truck traffic logs S3 bucket",
)

API_LATENCY_P95_SECONDS = Gauge(
    "api_latency_p95_seconds",
    "P95 request latency in seconds measured across all endpoints",
)

LATENCY_HISTORY = collections.deque(maxlen=200)


# ==============================================================================
# BASE MONITORING SERVICE
# ==============================================================================


class BaseMonitoringService:
    """Shared logic for monitoring services (traffic history + system status)."""

    @property
    def _env_config(self) -> dict:
        raise NotImplementedError

    def get_traffic_history(self, hours: int = 24) -> list[dict]:
        now = datetime.now(timezone.utc)
        data = []
        # NOSONAR: demo traffic data only, not security-sensitive
        base_count = random.randint(5, 12)
        for i in range(hours):
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
            data.append({"timestamp": timestamp, "entries": count, "hour": hour})
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
            **self._env_config,
        }


# ==============================================================================
# LOCAL MONITORING SERVICE
# ==============================================================================


class LocalMonitoringService(BaseMonitoringService):
    """Metrics sourced from the local Docker environment and LocalStack."""

    @property
    def _env_config(self) -> dict:
        return {
            "environment": "local",
            "node_label": "containers",
            "node_subtitle": "Running containers",
        }

    def __init__(self):
        usage, now = self._read_cpu_stat()
        self._last_cpu_time = usage
        self._last_cpu_time_monotonic = now

    def _read_cpu_stat(self):
        try:
            with open("/sys/fs/cgroup/cpu.stat") as f:
                for line in f:
                    if line.startswith("usage_usec"):
                        return int(line.split()[1]), time.monotonic()
        except OSError:
            pass
        return 0, time.monotonic()

    def get_cpu_usage(self) -> float:
        usage, now = self._read_cpu_stat()
        delta_usage = usage - self._last_cpu_time
        delta_time = now - self._last_cpu_time_monotonic
        self._last_cpu_time = usage
        self._last_cpu_time_monotonic = now
        if delta_time <= 0 or delta_usage <= 0:
            return 0.0
        cpu_pct = (delta_usage / 1_000_000) / delta_time * 100
        return round(min(cpu_pct, 100.0), 1)

    def _get_host_total_memory_mb(self) -> int:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            pass
        return 8192

    def get_memory_usage(self) -> float:
        try:
            with open("/sys/fs/cgroup/memory.current") as f:
                current = int(f.read().strip())
            limit_bytes = 0
            try:
                with open("/sys/fs/cgroup/memory.max") as f:
                    val = f.read().strip()
                    if val != "max":
                        limit_bytes = int(val)
            except (ValueError, OSError):
                pass
            if limit_bytes <= 0:
                limit_bytes = self._get_host_total_memory_mb() * 1024 * 1024
            return round(current / limit_bytes * 100, 1)
        except OSError:
            return 0.0

    def get_active_instances(self) -> int:
        if not hasattr(socket, "AF_UNIX"):
            logger.debug("AF_UNIX not supported on this platform")
            return 0
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect("/var/run/docker.sock")
            sock.sendall(
                b"GET /containers/json?all=false HTTP/1.0\r\nHost: localhost\r\n\r\n"
            )
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            sock.close()
            body = response.split(b"\r\n\r\n", 1)[1]
            containers = json.loads(body.decode())
            return len(containers)
        except (OSError, socket.error, json.JSONDecodeError, IndexError):
            logger.debug("Docker socket unavailable; returning 0")
            return 0

    def get_s3_storage_usage_mb(self) -> float:
        try:
            from services.s3_service import s3_service
        except ModuleNotFoundError:
            try:
                from app.services.s3_service import s3_service
            except ModuleNotFoundError:
                return 0.0
        try:
            logs = s3_service.list_truck_logs()
            total_bytes = sum(len(json.dumps(log)) for log in logs)
            return round(total_bytes / 1024 / 1024, 4)
        except Exception:
            return 0.0

    def observe_latency(self, duration: float):
        LATENCY_HISTORY.append(duration)

    def get_api_latency_p95(self) -> float:
        if not LATENCY_HISTORY:
            return 0.0
        sorted_lat = sorted(LATENCY_HISTORY)
        idx = int(len(sorted_lat) * 0.95)
        return round(sorted_lat[min(idx, len(sorted_lat) - 1)], 3)


# ==============================================================================
# AWS MONITORING SERVICE
# ==============================================================================


class AWSMonitoringService(BaseMonitoringService):
    """Metrics sourced from real AWS CloudWatch, EC2, S3, and ALB."""

    @property
    def _env_config(self) -> dict:
        return {
            "environment": "aws",
            "node_label": "instances",
            "node_subtitle": "EC2 serving traffic",
        }

    def __init__(self):
        self._region = os.getenv("AWS_REGION", "eu-west-3")
        self._asg_name = os.getenv("ASG_NAME", "lafarge-truck-traffic-asg")
        self._bucket_name = os.getenv("LOGS_BUCKET_NAME", "truck-traffic-logs")
        self._alb_arn_suffix = os.getenv("ALB_ARN_SUFFIX", "")

    def _get_cw_client(self):
        from botocore.config import Config as BotoConfig
        import boto3

        return boto3.client(
            "cloudwatch",
            region_name=self._region,
            config=BotoConfig(connect_timeout=5, read_timeout=5),
        )

    def get_cpu_usage(self) -> float:
        try:
            cw = self._get_cw_client()
            response = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Statistics=["Average"],
                Period=300,
                StartTime=datetime.now(timezone.utc) - timedelta(minutes=5),
                EndTime=datetime.now(timezone.utc),
            )
            points = response.get("Datapoints", [])
            if points:
                return round(max(p["Average"] for p in points), 1)
            return 0.0
        except Exception:
            return 0.0

    def get_memory_usage(self) -> float:
        try:
            cw = self._get_cw_client()
            response = cw.get_metric_statistics(
                Namespace="CWAgent",
                MetricName="mem_used_percent",
                Statistics=["Average"],
                Period=300,
                StartTime=datetime.now(timezone.utc) - timedelta(minutes=5),
                EndTime=datetime.now(timezone.utc),
            )
            points = response.get("Datapoints", [])
            if points:
                return round(max(p["Average"] for p in points), 1)
        except Exception:
            pass
        return 0.0

    def get_active_instances(self) -> int:
        from botocore.config import Config as BotoConfig
        import boto3

        try:
            asg = boto3.client(
                "autoscaling",
                region_name=self._region,
                config=BotoConfig(connect_timeout=5, read_timeout=5),
            )
            response = asg.describe_auto_scaling_groups(
                AutoScalingGroupNames=[self._asg_name]
            )
            groups = response.get("AutoScalingGroups", [])
            if groups:
                return groups[0].get("DesiredCapacity", 0)
        except Exception:
            pass
        try:
            ec2 = boto3.client(
                "ec2",
                region_name=self._region,
                config=BotoConfig(connect_timeout=5, read_timeout=5),
            )
            response = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            total = 0
            for reservation in response.get("Reservations", []):
                total += len(reservation.get("Instances", []))
            return total
        except Exception:
            return 0

    def get_s3_storage_usage_mb(self) -> float:
        from botocore.config import Config as BotoConfig
        import boto3

        try:
            s3 = boto3.client(
                "s3",
                region_name=self._region,
                config=BotoConfig(connect_timeout=5, read_timeout=5),
            )
            total_bytes = 0
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket_name):
                for obj in page.get("Contents", []):
                    total_bytes += obj.get("Size", 0)
            return round(total_bytes / 1024 / 1024, 2)
        except Exception:
            return 0.0

    def get_api_latency_p95(self) -> float:
        if not self._alb_arn_suffix:
            return 0.0
        try:
            cw = self._get_cw_client()
            response = cw.get_metric_statistics(
                Namespace="AWS/ApplicationELB",
                MetricName="TargetResponseTime",
                Statistics=["p95"],
                Period=300,
                StartTime=datetime.now(timezone.utc) - timedelta(minutes=5),
                EndTime=datetime.now(timezone.utc),
            )
            points = response.get("Datapoints", [])
            if points:
                return round(max(p["p95"] for p in points), 3)
        except Exception:
            pass
        return 0.0


# ==============================================================================
# AUTO-DETECTION
# ==============================================================================


def create_monitoring_service():
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    if endpoint and "localstack" in endpoint.lower():
        logger.info("Detected LocalStack — using LocalMonitoringService")
        return LocalMonitoringService()
    logger.info("Detected AWS environment — using AWSMonitoringService")
    return AWSMonitoringService()


monitoring_service = create_monitoring_service()
