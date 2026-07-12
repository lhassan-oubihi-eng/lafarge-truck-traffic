FROM jenkins/jenkins:lts

USER root

# تثبيت الحزم المطلوبة (حيدنا software-properties-common)
RUN apt-get update && apt-get install -y --no-install-recommends \
    make git curl lsb-release gnupg apt-transport-https ca-certificates \
    python3 python3-pip python3-venv awscli zip unzip openjdk-21-jre-headless \
    && curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    # التعديلات الخاصة بـ Terraform
    && curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update && apt-get install -y docker-ce-cli terraform \
    # تثبيت pytest
    && pip3 install pytest --break-system-packages \
    && rm -rf /var/lib/apt/lists/*

# إنشاء الـ Group وإضافة الـ User
RUN groupadd -f docker && usermod -aG docker jenkins

USER jenkins
