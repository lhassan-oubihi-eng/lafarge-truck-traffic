# ==============================================================================
# ARCHIVE - Cleanup old S3 logs
# ==============================================================================

s3-archive-dry: ## Dry-run: show old S3 logs that would be archived
	python scripts/archive_old_logs.py --days 7

s3-archive-apply: ## Actually delete old S3 logs (older than 7 days)
	python scripts/archive_old_logs.py --days 7 --apply

# ==============================================================================
# DOCKER - Build et publication de l'image applicative
# ==============================================================================

.DEFAULT_GOAL := help

# --- Configuration système (Cross-platform: Linux / Windows / Git Bash) ---
ifeq ($(OS),Windows_NT)
    RM_CMD = powershell -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
    TOUCH_CMD = powershell -Command "New-Item -ItemType File -Force"
    CD_CMD = cd /d
else
    RM_CMD = rm -rf
    TOUCH_CMD = touch
    CD_CMD = cd
endif

# --- Variables ---
APP_DIR             := app
TERRAFORM_DIR       := terraform
BOOTSTRAP_DIR       := terraform/bootstrap
LOCAL_COMPOSE_FILE  := docker-compose.local.yml
DOCKER_IMAGE        := lhassan1/truck-traffic-app

# GIT_HASH: short commit hash, fallback to 'unknown' if git unavailable
GIT_HASH := $(shell git rev-parse --short HEAD 2>nul || git rev-parse --short HEAD 2>/dev/null || echo unknown)
# Docker tag: use BUILD_NUMBER (Jenkins) if set, else GIT_HASH, else 'latest'
DOCKER_TAG          := $(or $(BUILD_NUMBER),$(GIT_HASH),latest)

.PHONY: help local-setup local-up local-down local-restart local-logs local-ps \
        local-clean get-jenkins-password app-test test \
        bootstrap-init bootstrap-plan bootstrap-apply bootstrap-destroy \
        tf-init tf-fmt tf-validate tf-plan tf-apply tf-apply-force tf-destroy tf-output \
        docker-build docker-push docker-build-hash docker-push-hash aws-refresh clean

## --- AIDE ---
## --- AIDE ---
help: ## Affiche l'aide
	@python -c "print('================================================================\n Lafarge Truck Traffic Management - Commandes disponibles\n================================================================')"
	@python -c "import re; m = [re.match(r'^([a-zA-Z_-]+):.*?\x23\x23 (.*)', l) for l in open('Makefile', encoding='utf-8')]; print('\n'.join(['{:<25} {}'.format(x.group(1), x.group(2)) for x in m if x]))"
# ==============================================================================
# MODE LOCAL
# ==============================================================================
local-setup: .installed ## Nettoie et lance la stack complète
	@docker compose -f $(LOCAL_COMPOSE_FILE) build
	@docker compose -f $(LOCAL_COMPOSE_FILE) up -d

local-up: .installed ## Lance la stack locale
	@docker compose -f $(LOCAL_COMPOSE_FILE) up -d --build

get-jenkins-password: ## Récupère le mot de passe Jenkins
	@echo "Récupération du mot de passe..."
	@docker exec jenkins-local cat /var/jenkins_home/secrets/initialAdminPassword || echo "Erreur: Jenkins n'est pas encore prêt."

local-down: ## Arrête la stack locale
	@docker compose -f $(LOCAL_COMPOSE_FILE) down

local-restart: local-down local-up ## Redémarre la stack locale

local-logs: ## Affiche les logs
	@docker compose -f $(LOCAL_COMPOSE_FILE) logs -f

local-ps: ## Liste les conteneurs
	@docker compose -f $(LOCAL_COMPOSE_FILE) ps

local-clean: ## Arrête et nettoie les volumes
	@docker compose -f $(LOCAL_COMPOSE_FILE) down -v --remove-orphans
	$(RM_CMD) .installed

app-test: ## Test API local
	@curl -X POST "http://localhost:8080/api/trucks/enter?plate=MK-1234-A" ; echo ""

test: ## Exécute les tests pytest
	@echo "Running unit tests..."
	python -m pytest app/tests/ -v

# ==============================================================================
# BOOTSTRAP & TERRAFORM
# ==============================================================================
bootstrap-init: ## Init Bootstrap
	$(CD_CMD) $(BOOTSTRAP_DIR) && terraform init

bootstrap-apply: ## Applique Bootstrap
	$(CD_CMD) $(BOOTSTRAP_DIR) && terraform apply

tf-init: ## Init Terraform
	$(CD_CMD) $(TERRAFORM_DIR) && terraform init

tf-validate: ## Validate Terraform
	$(CD_CMD) $(TERRAFORM_DIR) && terraform validate

tf-plan: ## Plan Terraform
	$(CD_CMD) $(TERRAFORM_DIR) && terraform plan -out=tfplan

tf-apply: ## Applique Terraform (requires manual approval)
	$(CD_CMD) $(TERRAFORM_DIR) && terraform apply tfplan

tf-apply-force: ## Applique Terraform avec -auto-approve (CI/CD)
	$(CD_CMD) $(TERRAFORM_DIR) && terraform apply -auto-approve

tf-destroy: ## Détruit l'infrastructure
	$(CD_CMD) $(TERRAFORM_DIR) && terraform destroy

# ==============================================================================
# DOCKER & UTILITAIRES
# ==============================================================================
docker-build: ## Build image with tag 'latest'
	$(CD_CMD) $(APP_DIR) && docker build -t $(DOCKER_IMAGE):latest .

docker-push: docker-build ## Push image with tag 'latest'
	docker push $(DOCKER_IMAGE):latest

docker-build-hash: ## Build image with GIT_HASH / BUILD_NUMBER tag
	$(CD_CMD) $(APP_DIR) && docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

docker-push-hash: docker-build-hash ## Push image with GIT_HASH / BUILD_NUMBER tag
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_IMAGE):latest
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)
	docker push $(DOCKER_IMAGE):latest

aws-refresh: ## Refresh ASG
	aws autoscaling start-instance-refresh --auto-scaling-group-name lafarge-truck-traffic-asg --region eu-west-3

.installed: app/requirements.txt
	pip install -r app/requirements.txt
	$(TOUCH_CMD) .installed

clean: local-clean ## Nettoyage complet
	$(RM_CMD) __pycache__
	$(RM_CMD) $(TERRAFORM_DIR)/tfplan
	@echo "Nettoyage terminé."