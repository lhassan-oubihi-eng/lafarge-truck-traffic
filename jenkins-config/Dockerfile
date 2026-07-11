FROM jenkins/jenkins:lts

USER root

# تثبيت git و Docker CLI
RUN apt-get update && apt-get install -y \
    git \
    curl \
    lsb-release \
    gnupg \
    apt-transport-https \
    ca-certificates && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

USER jenkins
