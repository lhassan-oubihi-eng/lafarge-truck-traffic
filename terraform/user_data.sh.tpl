#!/bin/bash
set -x

dnf update -y || true
dnf install -y docker || true
systemctl enable docker || true
systemctl start docker || true

sleep 5

# Just run the app container — no MySQL, no WordPress
docker pull ${app_docker_image}
docker rm -f truck-traffic-app 2>/dev/null || true
docker run -d --name truck-traffic-app -p 8000:8000 ${app_docker_image}

sleep 5

INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "unknown")
DIAG_FILE=/tmp/bootstrap-diagnostic.txt
{
  echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "Instance ID: $INSTANCE_ID"
  docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
  docker logs truck-traffic-app 2>&1 | tail -30
  curl -s -o /dev/null -w "Health check: HTTP %%{http_code}\n" http://localhost:8000/healthz || echo "Health check failed"
  df -h / | tail -1
  free -m | grep Mem
} > $DIAG_FILE 2>&1

aws s3 cp $DIAG_FILE "s3://truck-traffic-logs/bootstrap-$INSTANCE_ID.txt" --region eu-west-3 2>/dev/null || echo "[INFO] S3 diagnostic upload skipped"
