# 🚚 Lafarge Truck Traffic Management System

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=lhassan-oubihi-eng_lafarge-truck-traffic&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=lhassan-oubihi-eng_lafarge-truck-traffic)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=lhassan-oubihi-eng_lafarge-truck-traffic&metric=coverage)](https://sonarcloud.io/summary/new_code?id=lhassan-oubihi-eng_lafarge-truck-traffic)

A high-availability, fully automated, and secured DevOps-driven system designed to streamline and monitor truck traffic for Lafarge industrial sites.

---

## 🌟 Key Features

* **FastAPI Backend**: Real-time API tracking with responsive UI/HTML dashboards.
* **100% Test Coverage**: Verified robustly via test suites.
* **Security First**: Dependency locking using secure SHA hashes and dynamic SonarCloud alignment (0 open issues, 0 vulnerabilities).
* **Multi-Stage Docker**: Ultra-lightweight, production-grade containerization.
* **Infrastructure as Code**: AWS cloud architecture (VPC, ALB, ASG, EC2/ECS) provisioned via modular Terraform.
* **Hybrid CI/CD Pipelines**: Seamless automation supporting both **GitHub Actions** (`deploy.yml`) and **Jenkins** (`Jenkinsfile`).
* **Observability**: Live monitoring infrastructure with Prometheus and Grafana dashboards.

---

## 🛠️ Technology Stack

* **Backend**: Python 3.12, FastAPI, Uvicorn
* **CI/CD**: GitHub Actions, Jenkins, SonarCloud
* **Infrastructure**: AWS, Terraform
* **Containerization**: Docker, Docker Compose
* **Monitoring**: Prometheus, Grafana, Alertmanager
* **Automation**: GNU Makefile

---

## 🚀 How to Run the Project (via Makefile)

We use an automated `Makefile` to simplify all development, infrastructure, and deployment tasks.

### 1. Local Stack Orchestration (Without AWS)
To spin up the entire local environment (Application, Monitoring, and Jenkins):
```bash
# Clean previous environments, build and run the local stack
make local-up
```

Once up, you can access the infrastructure services at:

- **Application Dashboard**: http://localhost:8080
- **Prometheus Telemetry**: http://localhost:9090
- **Alertmanager**: http://localhost:9093
- **Grafana Dashboards**: http://localhost:3000 *(Credentials: `admin` / `ChangeMe_Lafarge2026!`)*
- **Jenkins Automation**: http://localhost:8081

> 🔑 **Jenkins Password Shortcut**: To retrieve the initial admin password for Jenkins at any time, simply run:
> 
> Bash
> 
> 
> ```
> make get-jenkins-password
> ```

### 2. Testing & Local Simulation
Bash

```
# Run the pytest suite locally
make test

# Simulate a truck entry event and scrape metrics via curl
make app-test
```

### 3. Local Stack Shutdown
Bash

```
# Stop containers but keep volumes intact
make local-down

# Full reset (Stops containers and wipes out local databases/volumes)
make local-clean
```

## 🌐 API Directory & Endpoints
**Endpoint****Method****Description****Target Consumer**`/``GET`Main responsive traffic controller HTML dashboardOperations Staff`/api/trucks``GET`Collection of active trucks inside the siteClient Application / UI`/metrics``GET`Telemetry endpoint exposing runtime behaviorsPrometheus Scraper`/healthz``GET`Service health-check validation routeAWS Load Balancer
## 🏗️ Infrastructure as Code & AWS Deployment

### 1. Bootstrap State (Run Once)
Before running the primary infrastructure, prepare the remote S3 Bucket and DynamoDB locks:

Bash

```
make bootstrap-init
make bootstrap-plan
make bootstrap-apply
```

### 2. Core AWS Infrastructure (Terraform)
To provision or destroy the production network, security groups, load balancers, and scaling groups:

Bash

```
make tf-init        # Connect to remote backend state
make tf-validate    # Validate files syntax
make tf-plan        # Preview structural modifications
make tf-apply       # Deploy infrastructure to AWS
```

### 3. Application Deployment & Rolling Refresh
When changing code, build/push the docker images and force an AWS Auto Scaling group updates:

Bash

```
make docker-push    # Builds image and pushes to registry
make aws-refresh    # Safely triggers an AWS Instance Refresh
```

## 👥 Project Contributors & Supervision

- **Fait par**: Lhassan OUBIHI & Taha HADDAD
- **Encadrant**: Mr. SAAD FOUTOUHI
- **Academic Year**: 2025-2026

### Executing Git Automation:
After overwriting README.md completely, run these commands in the terminal immediately:

git add README.md

git commit -m "docs: sync README configuration with true Makefile endpoints and fixed text layouts"

git push origin main
