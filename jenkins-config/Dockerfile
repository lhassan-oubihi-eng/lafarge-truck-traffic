FROM jenkins/jenkins:lts

USER root

# تثبيت الحزم كاملة مع تنظيف الكاش باش تكون الـ Image خفيفة
RUN apt-get update && apt-get install -y --no-install-recommends \
    make git curl lsb-release gnupg apt-transport-https ca-certificates \
    python3 python3-pip python3-venv \
    && curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# إعطاء صلاحيات Docker لـ Jenkins
RUN usermod -aG docker jenkins

USER jenkins
