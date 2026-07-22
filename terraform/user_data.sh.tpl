#!/bin/bash
set -x

# =============================================================================
# Bootstrap: system update & Docker installation
# =============================================================================
dnf update -y || echo "[WARN] dnf update failed"
dnf install -y docker || {
  echo "[WARN] docker install failed, retrying once..."
  sleep 5; dnf install -y docker || echo "[ERROR] docker install failed after retry"
}
systemctl enable docker || echo "[WARN] systemctl enable docker failed"
systemctl start docker || {
  echo "[WARN] docker start failed, retrying once..."
  sleep 5; systemctl start docker || echo "[ERROR] docker start failed after retry"
}
usermod -aG docker ec2-user || true

# =============================================================================
# CloudWatch Agent (for memory metrics: mem_used_percent in CWAgent namespace)
# =============================================================================
dnf install -y amazon-cloudwatch-agent 2>/dev/null || {
  echo "[WARN] amazon-cloudwatch-agent install failed, trying download..."
  CW_AGENT_URL="https://s3.${aws_region}.amazonaws.com/amazoncloudwatch-agent-${aws_region}/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm"
  curl -fsSL -o /tmp/amazon-cloudwatch-agent.rpm "$CW_AGENT_URL" && \
    rpm -Uvh /tmp/amazon-cloudwatch-agent.rpm || echo "[WARN] CloudWatch agent download+install failed"
}

mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWCONFIG'
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "metrics": {
    "namespace": "CWAgent",
    "metrics_collected": {
      "mem": {
        "measurement": ["mem_used_percent"]
      },
      "disk": {
        "measurement": ["disk_used_percent"],
        "resources": ["/"]
      },
      "cpu": {
        "measurement": ["cpu_usage_active"],
        "totalcpu": true
      }
    },
    "append_dimensions": {
      "AutoScalingGroupName": "$${aws:AutoScalingGroupName}",
      "ImageId": "$${aws:ImageId}",
      "InstanceId": "$${aws:InstanceId}",
      "InstanceType": "$${aws:InstanceType}"
    }
  }
}
CWCONFIG

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
  -s || echo "[WARN] CloudWatch agent config fetch failed"
systemctl enable amazon-cloudwatch-agent 2>/dev/null || true
systemctl start amazon-cloudwatch-agent 2>/dev/null || true
echo "[INFO] CloudWatch agent configured"

# =============================================================================
# Docker Hub login (avoids anonymous pull rate limits: 100 pulls/6h per IP)
# =============================================================================
if [ -n "${dockerhub_username}" ] && [ -n "${dockerhub_password}" ]; then
  echo "${dockerhub_password}" | docker login --username "${dockerhub_username}" --password-stdin || echo "[WARN] Docker Hub login failed"
fi

# =============================================================================
# Network: create shared bridge for inter-container communication
# =============================================================================
docker network create app_network 2>/dev/null || true

# =============================================================================
# Pull images (with retries)
# =============================================================================
MAX_RETRIES=3
RETRY_DELAY=15

pull_with_retry() {
  local IMAGE=$1
  local ATTEMPT=1
  while [ $ATTEMPT -le $MAX_RETRIES ]; do
    if docker pull $IMAGE; then
      echo "[INFO] Pulled $IMAGE successfully (attempt $ATTEMPT)"
      return 0
    fi
    echo "[WARN] docker pull $IMAGE failed (attempt $ATTEMPT/$MAX_RETRIES), retrying in $RETRY_DELAY seconds..."
    sleep $RETRY_DELAY
    ATTEMPT=$((ATTEMPT + 1))
  done
  echo "[ERROR] Failed to pull $IMAGE after $MAX_RETRIES attempts"
  return 1
}

pull_with_retry mysql:8.0
pull_with_retry wordpress:latest
pull_with_retry ${app_docker_image}

# =============================================================================
# Container: MySQL
# =============================================================================
docker rm -f mysql-db 2>/dev/null || true
docker run -d \
  --name mysql-db \
  --network app_network \
  --restart unless-stopped \
  -e MYSQL_ROOT_PASSWORD=${db_root_password} \
  -e MYSQL_DATABASE=wp \
  -e MYSQL_USER=wp_user \
  -e MYSQL_PASSWORD=${db_password} \
  -v mysql_data:/var/lib/mysql \
  mysql:8.0

echo "[INFO] Waiting for MySQL to be healthy..."
for i in $(seq 1 30); do
  if docker exec mysql-db mysqladmin ping -h localhost --silent 2>/dev/null; then
    echo "[INFO] MySQL is healthy"
    break
  fi
  echo "Waiting for MySQL... ($i/30)"
  sleep 3
done

# =============================================================================
# Container: WordPress
# =============================================================================
docker rm -f wordpress 2>/dev/null || true
docker run -d \
  --name wordpress \
  --network app_network \
  --restart unless-stopped \
  -p 8080:80 \
  -e WORDPRESS_DB_HOST=mysql-db \
  -e WORDPRESS_DB_USER=wp_user \
  -e WORDPRESS_DB_PASSWORD=${db_password} \
  -e WORDPRESS_DB_NAME=wp \
  wordpress:latest

# =============================================================================
# Container: Truck Traffic App
# =============================================================================
docker rm -f truck-traffic-app 2>/dev/null || true
docker run -d \
  --name truck-traffic-app \
  --network app_network \
  --restart unless-stopped \
  -p 8000:8000 \
  -e DB_HOST=mysql-db \
  -e DB_PORT=3306 \
  -e DB_NAME=wp \
  -e DB_USER=wp_user \
  -e DB_PASSWORD=${db_password} \
  -e AWS_REGION=${aws_region} \
  -e ALB_ARN_SUFFIX=${alb_arn_suffix} \
  -e ALB_DNS=${alb_dns_name} \
  -e ASG_NAME=${asg_name} \
  -e LOGS_BUCKET_NAME=${logs_bucket_name} \
  ${app_docker_image}

# =============================================================================
# Diagnostic collection & upload to S3
# =============================================================================
sleep 5
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "unknown")
DIAG_FILE=/tmp/bootstrap-diagnostic.txt

{
  echo "========== Bootstrap Diagnostic =========="
  echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "Instance ID: $INSTANCE_ID"
  echo ""
  echo "=== Docker Version ==="
  docker version --format '{{.Server.Version}}' 2>/dev/null || echo "Docker not available"
  echo ""
  echo "=== Container Status ==="
  docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "Cannot list containers"
  echo ""
  echo "=== Container Logs (mysql-db) ==="
  docker logs mysql-db 2>&1 | tail -20
  echo ""
  echo "=== Container Logs (truck-traffic-app) ==="
  docker logs truck-traffic-app 2>&1 | tail -20
  echo ""
  echo "=== App Health Check (port 8000) ==="
  curl -s -o /dev/null -w "HTTP %%{http_code}\n" http://localhost:8000/healthz || echo "Health check failed"
  echo ""
  echo "=== Disk Usage ==="
  df -h /
  echo ""
  echo "=== Memory ==="
  free -m
  echo ""
  echo "=== Docker Info ==="
  docker info --format '{{.ContainersRunning}} running, {{.Containers}} total, {{.Images}} images' 2>/dev/null || echo "Docker info not available"
  echo ""
  echo "=== Network Check ==="
  docker network inspect app_network 2>/dev/null | grep -E '"Name|Containers' || echo "Network not found"
} > $DIAG_FILE 2>&1

aws s3 cp $DIAG_FILE "s3://truck-traffic-logs/bootstrap-$INSTANCE_ID.txt" --region eu-west-3 2>/dev/null || echo "[INFO] S3 diagnostic upload skipped"

# =============================================================================
# Node Exporter : monitoring Prometheus
# =============================================================================
NODE_EXPORTER_VERSION="1.8.2"
curl -fsSL -o /tmp/node_exporter.tar.gz \
  "https://github.com/prometheus/node_exporter/releases/download/v$${NODE_EXPORTER_VERSION}/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz" || echo "[WARN] Node Exporter download failed"

if [ -f /tmp/node_exporter.tar.gz ] && [ -s /tmp/node_exporter.tar.gz ]; then
  tar -xzf /tmp/node_exporter.tar.gz -C /tmp
  mv /tmp/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/node_exporter || true

  cat > /etc/systemd/system/node_exporter.service <<'UNIT'
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
ExecStart=/usr/local/bin/node_exporter --web.listen-address=:9100
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable node_exporter || true
  systemctl start node_exporter || true
  echo "[INFO] Node Exporter installed successfully"
else
  echo "[WARN] Node Exporter skipped (download failed or empty)"
fi
