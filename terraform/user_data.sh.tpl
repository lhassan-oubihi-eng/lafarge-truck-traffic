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
# Docker Hub login (avoids anonymous pull rate limits: 100 pulls/6h per IP)
# =============================================================================
if [ -n "${dockerhub_username}" ] && [ -n "${dockerhub_password}" ]; then
  echo "${dockerhub_password}" | docker login --username "${dockerhub_username}" --password-stdin || echo "[WARN] Docker Hub login failed"
fi

# =============================================================================
# Docker Compose: install if missing
# =============================================================================
if ! docker compose version &>/dev/null && ! command -v docker-compose &>/dev/null; then
  ARCH=$(uname -m)
  echo "[INFO] Downloading docker-compose binary from GitHub..."
  curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$${ARCH}" -o /usr/local/bin/docker-compose || echo "[ERROR] docker-compose download failed (rate limited or network issue)"
  if [ -f /usr/local/bin/docker-compose ] && [ -s /usr/local/bin/docker-compose ]; then
    chmod +x /usr/local/bin/docker-compose
    mkdir -p /usr/libexec/docker/cli-plugins
    ln -sf /usr/local/bin/docker-compose /usr/libexec/docker/cli-plugins/docker-compose || true
  fi
fi

# =============================================================================
# Docker Compose: orchestre l'application, MySQL et WordPress
# =============================================================================
cat > /opt/docker-compose.yml <<'COMPOSE'
version: "3.9"

services:
  mysql-db:
    image: mysql:8.0
    container_name: mysql-db
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${db_root_password}
      MYSQL_DATABASE: wp
      MYSQL_USER: wp_user
      MYSQL_PASSWORD: ${db_password}
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  wordpress:
    image: wordpress:latest
    container_name: wordpress
    restart: unless-stopped
    ports:
      - "8080:80"
    environment:
      WORDPRESS_DB_HOST: mysql-db
      WORDPRESS_DB_USER: wp_user
      WORDPRESS_DB_PASSWORD: ${db_password}
      WORDPRESS_DB_NAME: wp
    depends_on:
      mysql-db:
        condition: service_healthy

  truck-traffic-app:
    image: ${app_docker_image}
    container_name: truck-traffic-app
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=mysql-db
      - DB_PORT=3306
      - DB_NAME=wp
      - DB_USER=wp_user
      - DB_PASSWORD=${db_password}
    depends_on:
      - mysql-db

volumes:
  mysql_data:
COMPOSE

# =============================================================================
# Pull Docker images (with retries) then start containers
# =============================================================================
MAX_RETRIES=3
RETRY_DELAY=15

ATTEMPT=1
while [ $ATTEMPT -le $MAX_RETRIES ]; do
  if docker compose -f /opt/docker-compose.yml pull; then
    echo "[INFO] Docker images pulled successfully (attempt $ATTEMPT)"
    break
  fi
  echo "[WARN] docker compose pull failed (attempt $ATTEMPT/$MAX_RETRIES), retrying in $RETRY_DELAY seconds..."
  sleep $RETRY_DELAY
  ATTEMPT=$((ATTEMPT + 1))
done

ATTEMPT=1
while [ $ATTEMPT -le $MAX_RETRIES ]; do
  if docker compose -f /opt/docker-compose.yml up -d; then
    echo "[INFO] Docker containers started successfully (attempt $ATTEMPT)"
    break
  fi
  echo "[WARN] docker compose up failed (attempt $ATTEMPT/$MAX_RETRIES), retrying in $RETRY_DELAY seconds..."
  sleep $RETRY_DELAY
  ATTEMPT=$((ATTEMPT + 1))
done

# =============================================================================
# Diagnostic collection
# =============================================================================
sleep 8
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
  echo "=== Docker Compose Version ==="
  docker compose version 2>/dev/null || docker-compose --version 2>/dev/null || echo "Docker Compose not available"
  echo ""
  echo "=== Container Status ==="
  docker ps -a 2>/dev/null || echo "Cannot list containers"
  echo ""
  echo "=== Docker Compose Logs ==="
  docker compose -f /opt/docker-compose.yml logs --tail=50 2>/dev/null || echo "Cannot get logs"
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
  echo "=== Failed Systemd Services ==="
  systemctl --failed --no-legend 2>/dev/null || echo "No failed services"
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
