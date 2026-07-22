import json
from unittest.mock import patch, MagicMock

from botocore.exceptions import ClientError


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_s3_service_init_with_credentials(mock_boto):
    from app.services.s3_service import S3Service

    svc = S3Service()
    assert svc is not None


@patch.dict("os.environ", {"AWS_ENDPOINT_URL": "http://localstack:4566"}, clear=True)
@patch("boto3.client")
def test_s3_service_init_without_credentials(mock_boto):
    from app.services.s3_service import S3Service

    svc = S3Service()
    assert svc is not None


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_ensure_bucket_exists_creates_when_not_found(mock_boto):
    mock_s3 = MagicMock()
    error_response = {"Error": {"Code": "404", "Message": "Not Found"}}
    mock_s3.head_bucket.side_effect = ClientError(error_response, "HeadBucket")
    mock_s3.create_bucket.return_value = {}
    mock_boto.return_value = mock_s3
    from app.services.s3_service import S3Service

    svc = S3Service()
    assert svc._bucket == "truck-traffic-logs"


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_ensure_bucket_exists_logs_general_error(mock_boto):
    mock_s3 = MagicMock()
    mock_s3.head_bucket.side_effect = Exception("Network error")
    mock_boto.return_value = mock_s3
    from app.services.s3_service import S3Service

    svc = S3Service()
    assert svc is not None


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_upload_json_error_handling(mock_boto):
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = Exception("Upload failed")
    mock_boto.return_value = mock_s3
    from app.services.s3_service import S3Service

    svc = S3Service()
    svc.upload_json("test.json", json.dumps({"test": True}))


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_list_truck_logs_skips_non_json(mock_boto):
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "traffic_logs/2026/data.txt"},
            {"Key": "traffic_logs/2026/log.json"},
        ]
    }
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps({"event": "truck_entry"}).encode())
    }
    mock_boto.return_value = mock_s3
    from app.services.s3_service import S3Service

    svc = S3Service()
    results = svc.list_truck_logs()
    assert len(results) == 1


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_list_truck_logs_handles_parse_error(mock_boto):
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {
        "Contents": [{"Key": "traffic_logs/2026/bad.json"}]
    }
    mock_s3.get_object.side_effect = Exception("Parse error")
    mock_boto.return_value = mock_s3
    from app.services.s3_service import S3Service

    svc = S3Service()
    results = svc.list_truck_logs()
    assert results == []


@patch.dict(
    "os.environ",
    {
        "AWS_ENDPOINT_URL": "http://localstack:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",  # pragma: allowlist secret
    },
)
@patch("boto3.client")
def test_list_truck_logs_handles_list_error(mock_boto):
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.side_effect = Exception("List failed")
    mock_boto.return_value = mock_s3
    from app.services.s3_service import S3Service

    svc = S3Service()
    results = svc.list_truck_logs()
    assert results == []
