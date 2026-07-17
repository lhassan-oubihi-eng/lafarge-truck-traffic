"""
LocalStack S3 Verification Script

Tests that boto3 can communicate with LocalStack's S3 mock service.
Run this from the host while the local stack is up (make local-up).

Usage:
    python scripts/test_s3_localstack.py
"""

import boto3
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration – matches docker-compose.local.yml environment
# ---------------------------------------------------------------------------
ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
BUCKET_NAME = os.getenv("LOGS_BUCKET_NAME", "truck-traffic-logs")
SAMPLE_FILE = "test_env_verification.txt"
SAMPLE_CONTENT = (
    f"Lafarge Truck Traffic – LocalStack S3 verification\n"
    f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
    f"Status: SUCCESS\n"
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"[*] Connecting to LocalStack S3 at {ENDPOINT_URL}")
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )

    # 1. Create bucket ------------------------------------------------------
    print(f"[*] Creating bucket '{BUCKET_NAME}' ...")
    try:
        s3.create_bucket(Bucket=BUCKET_NAME)
        print(f"    ✔ Bucket '{BUCKET_NAME}' created.")
    except Exception as e:
        print(f"    ✖ Failed to create bucket: {e}")
        return

    # 2. Upload object ------------------------------------------------------
    print(f"[*] Uploading '{SAMPLE_FILE}' to bucket ...")
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=SAMPLE_FILE,
            Body=SAMPLE_CONTENT.encode("utf-8"),
        )
        print(f"    ✔ File uploaded.")
    except Exception as e:
        print(f"    ✖ Upload failed: {e}")
        return

    # 3. List buckets -------------------------------------------------------
    print("[*] Listing all buckets ...")
    try:
        response = s3.list_buckets()
        buckets = [b["Name"] for b in response["Buckets"]]
        print(f"    ✔ Buckets: {buckets}")
        if BUCKET_NAME in buckets:
            print(f"    ✔ '{BUCKET_NAME}' confirmed in bucket list.")
        else:
            print(f"    ✖ '{BUCKET_NAME}' NOT found in bucket list!")
            return
    except Exception as e:
        print(f"    ✖ Failed to list buckets: {e}")
        return

    # 4. Verify object content ----------------------------------------------
    print("[*] Verifying uploaded file content ...")
    try:
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=SAMPLE_FILE)
        content = obj["Body"].read().decode("utf-8")
        print(f"    ✔ File content:\n{'-'*40}\n{content}{'-'*40}")
    except Exception as e:
        print(f"    ✖ Failed to read object: {e}")
        return

    print("\n[✓] All S3 operations completed successfully!")
    print("[✓] boto3 ↔ LocalStack communication is working correctly.")


if __name__ == "__main__":
    main()
