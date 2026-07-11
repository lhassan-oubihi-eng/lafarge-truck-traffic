FROM jenkins/jenkins:lts

USER root

# تثبيت الحزم الأساسية + Python + Trivy
RUN apt-get update && apt-get install -y \
    make \
    git curl lsb-release gnupg apt-transport-https ca-certificates \
    awscli \
    python3 python3-pip \
    && curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

# إضافة Docker و Terraform (اللي عندك ديجا)
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list && \
    curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" > /etc/apt/sources.list.d/hashicorp.list && \
    apt-get update && apt-get install -y docker-ce-cli terraform && \
    rm -rf /var/lib/apt/lists/*

# تثبيت pytest
RUN pip3 install pytest --break-system-packages

USER jenkins
