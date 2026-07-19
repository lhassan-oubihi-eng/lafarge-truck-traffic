#!/bin/bash
set -ex

# =============================================================================
# Bootstrap: system update & Docker installation
# =============================================================================
dnf update -y
dnf install -y docker docker-compose-plugin
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

# =============================================================================
# Docker Compose: orchestre l'application, MySQL et WordPress
# Utiliser docker-compose plutôt que des docker run individuels permet :
#   - Un démarrage ordonné via depends_on
#   - Un réseau partagé automatique (pas de --link déprécié)
#   - Une gestion unifiée des redémarrages et des logs
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
      - "80:8000"
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

# Pull de la dernière image Docker puis démarrage des services
docker compose -f /opt/docker-compose.yml pull || true

# Lancement des conteneurs (ne pas bloquer le script si ça échoue)
docker compose -f /opt/docker-compose.yml up -d || echo "⚠️ docker compose up failed (exit $?)"

# Diagnostic : statut des conteneurs
sleep 8
echo "=== Container Status ==="
docker ps -a
echo "=== App Health Check (port 80) ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:80/healthz || echo "⚠️ Health check failed (app not responding)"

# =============================================================================
# Node Exporter : monitoring Prometheus (hors Docker pour accès direct host)
# =============================================================================
NODE_EXPORTER_VERSION="1.8.2"
curl -sSL -o /tmp/node_exporter.tar.gz \
  "https://github.com/prometheus/node_exporter/releases/download/v$${NODE_EXPORTER_VERSION}/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
tar -xzf /tmp/node_exporter.tar.gz -C /tmp
mv /tmp/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/node_exporter

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
systemctl enable node_exporter
systemctl start node_exporter
