#!/usr/bin/env python3
"""
Archive old S3 traffic logs.

Usage:
    # Dry-run: see what would be archived (default)
    python scripts/archive_old_logs.py --days 7

    # Actually delete (can be extended to move to another bucket)
    python scripts/archive_old_logs.py --days 7 --apply

Connects to LocalStack at http://localhost:4566.
"""

import argparse
import sys
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

ENDPOINT_URL = "http://localhost:4566"
REGION = "us-east-1"
BUCKET = "truck-traffic-logs"
PREFIX = "traffic_logs/"


def main():
    parser = argparse.ArgumentParser(description="Archive old S3 truck traffic logs")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Archive logs older than N days (default: 7)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually delete files (default: dry-run)"
    )
    parser.add_argument(
        "--endpoint",
        default=ENDPOINT_URL,
        help=f"LocalStack endpoint (default: {ENDPOINT_URL})",
    )
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"📅 Cutoff date: {cutoff.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"📦 Bucket: {BUCKET}")
    print(f"{'🚀 APPLY MODE' if args.apply else '👁️  DRY-RUN (use --apply to archive)'}")
    print()

    s3 = boto3.client(
        "s3",
        endpoint_url=args.endpoint,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX)
    except (ClientError, EndpointConnectionError) as exc:
        print(f"❌ Cannot connect to LocalStack: {exc}")
        sys.exit(1)

    contents = resp.get("Contents", [])
    if not contents:
        print("✅ No objects to archive.")
        return

    to_delete = []
    for obj in contents:
        key = obj["Key"]
        last_modified = (
            obj["LastModified"].replace(tzinfo=timezone.utc)
            if obj["LastModified"].tzinfo is None
            else obj["LastModified"]
        )
        if last_modified < cutoff:
            to_delete.append(key)

    if not to_delete:
        print("✅ No objects older than {args.days} days found.")
        return

    print(f"🗑️  Found {len(to_delete)} object(s) to archive:")
    for key in to_delete:
        print(f"   - {key}")

    if not args.apply:
        print()
        print("ℹ️  Re-run with --apply to delete these files.")
        return

    # Delete
    delete_dict = {"Objects": [{"Key": k} for k in to_delete]}
    try:
        resp = s3.delete_objects(Bucket=BUCKET, Delete=delete_dict)
        deleted = len(resp.get("Deleted", []))
        errors = len(resp.get("Errors", []))
        print(f"\n✅ Deleted {deleted} object(s). Errors: {errors}")
    except ClientError as exc:
        print(f"❌ Delete failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
