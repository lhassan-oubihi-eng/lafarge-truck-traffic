FROM jenkins/jenkins:lts

USER root

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        apt-transport-https \
        awscli \
        ca-certificates \
        curl \
        gnupg \
        git \
        lsb-release \
        make \
        openjdk-21-jre-headless \
        python3 \
        python3-pip \
        python3-venv \
        unzip \
        zip; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL --proto '=https' --tlsv1.2 https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list; \
    curl -fsSL --proto '=https' --tlsv1.2 https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg; \
    echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" > /etc/apt/sources.list.d/hashicorp.list; \
    curl -fsSL --proto '=https' --tlsv1.2 https://aquasecurity.github.io/trivy-repo/deb/public.key | gpg --dearmor -o /usr/share/keyrings/trivy.gpg; \
    echo "deb [signed-by=/usr/share/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -cs) main" > /etc/apt/sources.list.d/trivy.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-ce-cli terraform trivy; \
    pip3 install --only-binary :all: --no-cache-dir --break-system-packages pytest==8.3.2; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd -f docker; \
    usermod -aG docker jenkins

USER jenkins
