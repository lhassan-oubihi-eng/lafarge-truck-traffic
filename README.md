# 🚚 Lafarge Truck Traffic Management System

A high-availability, fully automated, and secured DevOps-driven system designed to streamline and monitor truck traffic for Lafarge industrial sites.

## 🌟 Key Features
- **FastAPI Backend**: Real-time API tracking with integrated endpoints.
- **100% Test Coverage**: Fully verified with pytest and pytest-cov.
- **Security First**: Dependency locking with hashes and SonarCloud analysis (0 issues, 0 vulnerabilities).
- **Multi-Stage Docker**: Secure, lightweight, and production-ready containerization.
- **Infrastructure as Code**: AWS ECS, Application Load Balancers, and Security Groups provisioned via Terraform.
- **Hybrid CI/CD**: Dual-pipeline support via GitHub Actions (`deploy.yml`) and Jenkins (`Jenkinsfile`).
- **Observability**: Real-time system monitoring with Prometheus and Grafana.

## 🛠️ Technology Stack
- **Backend**: Python 3.12, FastAPI, Uvicorn
- **CI/CD**: GitHub Actions, Jenkins, SonarCloud
- **IaC**: Terraform
- **Containerization**: Docker, Docker Compose
- **Monitoring**: Prometheus, Grafana
- **Automation**: Makefile

---

## 🚀 How to Run the Project

### 1. Local Development (Python)
Lock your dependencies and run the server locally:
```bash
# Install secured dependencies
pip install -r requirements.txt --require-hashes

# Run the API with Uvicorn
uvicorn app.main:app --reload
```
