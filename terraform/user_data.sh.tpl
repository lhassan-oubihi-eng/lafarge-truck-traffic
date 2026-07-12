#!/bin/bash
set -e

# تحديث النظام وتثبيت Docker
dnf update -y
dnf install -y docker
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

# تشغيل التطبيق الأساسي (Truck Traffic)
docker run -d \
  --name truck-traffic-app \
  --restart unless-stopped \
  -p 80:8000 \
  ${app_docker_image}

# تشغيل قاعدة بيانات MySQL
docker run -d \
  --name mysql-db \
  -e MYSQL_ROOT_PASSWORD=${db_root_password} \
  -e MYSQL_DATABASE=wp \
  -e MYSQL_USER=wp_user \
  -e MYSQL_PASSWORD=${db_password} \
  -v mysql_data:/var/lib/mysql \
  mysql:8.0

# تشغيل WordPress وربطه بـ MySQL
docker run -d \
  --name wordpress \
  --link mysql-db:mysql \
  -p 8080:80 \
  -e WORDPRESS_DB_HOST=mysql \
  -e WORDPRESS_DB_USER=wp_user \
  -e WORDPRESS_DB_PASSWORD=${db_password} \
  -e WORDPRESS_DB_NAME=wp \
  wordpress:latest

# تثبيت Node Exporter للمراقبة (Monitoring)
NODE_EXPORTER_VERSION="1.8.2"
curl -sSL -o /tmp/node_exporter.tar.gz \
  "https://github.com/prometheus/node_exporter/releases/download/v$${NODE_EXPORTER_VERSION}/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
tar -xzf /tmp/node_exporter.tar.gz -C /tmp
mv /tmp/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/node_exporter

# إنشاء خدمة Node Exporter
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
