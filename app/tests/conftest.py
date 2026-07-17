"""
pytest configuration and fixtures for the Lafarge Truck Traffic test suite.

Provides a reusable ``s3_client`` fixture that connects to LocalStack,
allowing tests to verify S3 integration without hardcoded endpoints.
"""

import os
import pytest

try:
    import boto3

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


@pytest.fixture(scope="function")
def s3_client():
    """Return a boto3 S3 client pre-configured for LocalStack.

    The endpoint URL is read from the ``AWS_ENDPOINT_URL`` environment
    variable so it works both inside Docker (where it resolves to
    ``http://localstack:4566``) and on the developer's host (where it
    resolves to ``http://localhost:4566``).

    Skips the test if boto3 is not installed (e.g. in minimal test envs).
    """
    if not HAS_BOTO3:
        pytest.skip("boto3 is not installed")

    endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "mock"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "mock"),
    )
    yield client
