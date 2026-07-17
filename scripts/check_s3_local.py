#!/usr/bin/env python3
"""Quick S3 inspector for LocalStack.

Usage:
    python scripts/check_s3_local.py
    python scripts/check_s3_local.py --bucket truck-traffic-logs
"""

import argparse
import os
import sys
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError


ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
DEFAULT_BUCKET = os.getenv("LOGS_BUCKET_NAME", "truck-traffic-logs")


def list_buckets(s3):
    try:
        resp = s3.list_buckets()
        buckets = [b["Name"] for b in resp.get("Buckets", [])]
        if not buckets:
            print("No buckets found.")
            return []
        print("Buckets:")
        for b in buckets:
            print(f"  - {b}")
        return buckets
    except (ClientError, EndpointConnectionError) as exc:
        print(f"ERROR: Cannot connect to LocalStack at {ENDPOINT_URL}: {exc}")
        sys.exit(1)


def list_objects(s3, bucket, prefix=None, max_keys=50):
    try:
        kwargs = {"Bucket": bucket, "MaxKeys": max_keys}
        if prefix:
            kwargs["Prefix"] = prefix
        resp = s3.list_objects_v2(**kwargs)
        contents = resp.get("Contents", [])
        if not contents:
            print(
                f"\nNo objects in bucket '{bucket}'{f' with prefix {prefix!r}' if prefix else ''}."
            )
            return
        print(f"\nObjects in '{bucket}'{f' (prefix={prefix!r})' if prefix else ''}:")
        for obj in contents:
            size = obj.get("Size", 0)
            print(f"  {obj['Key']}  ({size} bytes)")
    except ClientError as exc:
        print(f"ERROR listing objects in '{bucket}': {exc}")


def main():
    parser = argparse.ArgumentParser(description="Inspect LocalStack S3 buckets")
    parser.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET,
        help=f"Bucket name (default: {DEFAULT_BUCKET})",
    )
    parser.add_argument("--prefix", default=None, help="Filter by prefix")
    parser.add_argument(
        "--list-all", action="store_true", help="List all buckets first"
    )
    args = parser.parse_args()

    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )

    if args.list_all:
        list_buckets(s3)

    list_objects(s3, args.bucket, prefix=args.prefix)


if __name__ == "__main__":
    main()
