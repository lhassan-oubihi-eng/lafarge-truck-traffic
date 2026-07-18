"""
S3 Service Layer for Lafarge Truck Traffic.

Encapsulates all boto3 S3 interactions with LocalStack.
The bucket is auto-created on first import.
"""

import json
import os
import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration – reads from environment variables set in docker-compose
# ---------------------------------------------------------------------------
ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1"))
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
BUCKET_NAME = os.getenv("LOGS_BUCKET_NAME", "truck-traffic-logs")


class S3Service:
    """Thin wrapper around a boto3 S3 client pre-configured for LocalStack."""

    def __init__(self):
        boto_config = BotoConfig(connect_timeout=5, read_timeout=5)
        client_kwargs = {
            "service_name": "s3",
            "endpoint_url": ENDPOINT_URL,
            "region_name": AWS_REGION,
            "config": boto_config,
        }
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
            client_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
        self.s3 = boto3.client(**client_kwargs)
        self._bucket = BUCKET_NAME
        self._ensure_bucket_exists()

    # ------------------------------------------------------------------
    def _ensure_bucket_exists(self) -> None:
        """Create the target bucket if it does not already exist.

        Silently degrades if LocalStack is unreachable (e.g. during unit
        tests on the host). Background upload tasks will simply log an
        error and continue.
        """
        try:
            self.s3.head_bucket(Bucket=self._bucket)
            logger.info("S3 bucket '%s' already exists.", self._bucket)
        except ClientError:
            try:
                self.s3.create_bucket(Bucket=self._bucket)
                logger.info("S3 bucket '%s' created successfully.", self._bucket)
            except Exception as exc:
                logger.warning(
                    "Failed to auto-create bucket '%s': %s", self._bucket, exc
                )
        except Exception as exc:
            logger.warning(
                "LocalStack unreachable for bucket '%s': %s", self._bucket, exc
            )

    # ------------------------------------------------------------------
    def upload_json(self, key: str, payload: str) -> None:
        """Upload a JSON string to S3.

        Args:
            key:     S3 object key (e.g. ``traffic_logs/2026-07-15/<id>.json``).
            payload: JSON-serialized string to upload.
        """
        try:
            self.s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info("Uploaded %s to s3://%s/%s", key, self._bucket, key)
        except Exception as exc:
            logger.warning(
                "S3 upload skipped for %s (LocalStack might be unavailable): %s",
                key,
                exc,
            )

    # ------------------------------------------------------------------
    def list_truck_logs(self, prefix: str = "traffic_logs/") -> list[dict]:
        """List all truck event JSON files from S3 and parse them.

        Returns a list of dicts with keys:
            - event (str): "truck_entry" or "truck_exit"
            - truck_id (str)
            - license_plate (str)
            - event_time (str)
            - gate_id (str)
            - status (str)
            - exit_time (str, optional)
            - entry_time (str, optional)
        """
        results: list[dict] = []
        try:
            resp = self.s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".json"):
                    continue
                try:
                    raw = self.s3.get_object(Bucket=self._bucket, Key=key)
                    body = raw["Body"].read().decode("utf-8")
                    data = json.loads(body)
                    results.append(data)
                except Exception as exc:
                    logger.warning("Failed to parse S3 object %s: %s", key, exc)
        except Exception as exc:
            logger.warning("Failed to list truck logs from S3: %s", exc)
        return results


# Module-level singleton – reused across all endpoints
s3_service = S3Service()
