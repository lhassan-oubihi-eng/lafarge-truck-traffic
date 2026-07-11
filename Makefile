# ==============================================================================
# Makefile - Lafarge Truck Traffic Management
# Raccourcis pour le développement local, le bootstrap AWS et les opérations
# Terraform/Docker courantes.
#
# Utilisation : make <cible>       (ex : make local-up)
#               make help          pour lister toutes les cibles disponibles
# ==============================================================================

.DEFAULT_GOAL := help

# Empêche make de confondre ces noms de cibles avec des fichiers du même nom
.PHONY: help local-up local-down local-restart local-logs local-clean local-ps \
        bootstrap-init bootstrap-plan bootstrap-apply bootstrap-destroy \
        tf-init tf-fmt tf-validate tf-plan tf-apply tf-destroy tf-output \
        docker-build docker-push app-test clean aws-refresh
# --------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------
APP_DIR             := app
TERRAFORM_DIR        := terraform
BOOTSTRAP_DIR         := terraform/bootstrap
LOCAL_COMPOSE_FILE     := docker-compose.local.yml
DOCKER_IMAGE            := lhassan1/truck-traffic-app
DOCKER_TAG               := latest

help: ## Affiche cette aide
	@echo "Lafarge Truck Traffic Management - Commandes disponibles"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ==============================================================================
# MODE LOCAL - Test sur poste de développement (sans AWS)
# ==============================================================================
# هاد الـ target كيجمع كلشي
local-setup:
	@echo "Cleaning old environment..."
	@make local-clean
	@echo "Building custom Jenkins image..."
	@docker compose -f docker-compose.local.yml build
	@echo "Starting the stack..."
	@docker compose -f docker-compose.local.yml up -d
	@echo "Jenkins is ready! Use 'make get-jenkins-password' to get the password."

local-up: ## Lance la stack complète en local
	docker compose -f $(LOCAL_COMPOSE_FILE) up -d --build
	@echo ""
	@echo "Application  : http://localhost:8080"
	@echo "Prometheus   : http://localhost:9090"
	@echo "Alertmanager : http://localhost:9093"
	@echo "Grafana      : http://localhost:3000 (admin / ChangeMe_Lafarge2026!)"
	@echo "Jenkins      : http://localhost:8081"
	@echo ""
	@echo "--- Jenkins Initial Password ---"
	@sleep 5
	@docker exec jenkins-local cat /var/jenkins_home/secrets/initialAdminPassword || echo "Jenkins is not ready yet, run 'make get-jenkins-password' later."

# زيد هاد الـ target الجديد باش يلا تعطل Jenkins تقدر تجبد الباسورد بوحدو فـ أي وقت
get-jenkins-password:
	@docker exec jenkins-local cat /var/jenkins_home/secrets/initialAdminPassword

local-down: ## Arrête la stack locale (conserve les volumes)
	docker compose -f $(LOCAL_COMPOSE_FILE) down

local-restart: local-down local-up ## Redémarre la stack locale

local-logs: ## Affiche les logs de la stack locale en continu
	docker compose -f $(LOCAL_COMPOSE_FILE) logs -f

local-ps: ## Liste l'état des conteneurs de la stack locale
	docker compose -f $(LOCAL_COMPOSE_FILE) ps

local-clean: ## Arrête la stack locale ET supprime les volumes (reset complet)
	docker compose -f $(LOCAL_COMPOSE_FILE) down -v --remove-orphans

app-test: ## Envoie une requête de test à l'application locale (simulation d'entrée camion)
	curl -X POST "http://localhost:8080/api/trucks/enter?plate=MK-1234-A" ; echo ""
	curl -s http://localhost:8080/metrics | grep trucks_processed_total
# نزيدو هاد الـ target للـ Makefile
test: ## Exécute les tests unitaires avec pytest
	@echo "Running unit tests..."
	python3 -m pytest app/tests/

# ==============================================================================
# BOOTSTRAP - Création du backend S3 + DynamoDB (à lancer UNE SEULE FOIS)
# ==============================================================================

bootstrap-init: ## Initialise le module bootstrap (state local)
	cd $(BOOTSTRAP_DIR) && terraform init

bootstrap-plan: ## Prévisualise la création du bucket S3 + table DynamoDB
	cd $(BOOTSTRAP_DIR) && terraform plan

bootstrap-apply: ## Crée réellement le bucket S3 + table DynamoDB (backend distant)
	cd $(BOOTSTRAP_DIR) && terraform apply

bootstrap-destroy: ## Supprime le bucket S3 + table DynamoDB (ATTENTION : destructif)
	@echo "ATTENTION : cette action supprime le backend Terraform distant."
	@echo "Assurez-vous qu'aucun state actif n'y est stocké avant de continuer."
	cd $(BOOTSTRAP_DIR) && terraform destroy

# ==============================================================================
# TERRAFORM - Infrastructure principale AWS (VPC, ALB, ASG...)
# ==============================================================================

tf-init: ## Initialise Terraform (connexion au backend S3 distant)
	cd $(TERRAFORM_DIR) && terraform init

tf-fmt: ## Formate tous les fichiers .tf selon les conventions HashiCorp
	cd $(TERRAFORM_DIR) && terraform fmt -recursive

tf-validate: ## Valide la syntaxe et la cohérence de la configuration Terraform
	cd $(TERRAFORM_DIR) && terraform validate

tf-plan: ## Prévisualise les changements d'infrastructure à appliquer
	cd $(TERRAFORM_DIR) && terraform plan -out=tfplan

tf-apply: ## Applique le plan généré par 'make tf-plan'
	cd $(TERRAFORM_DIR) && terraform apply tfplan

tf-destroy: ## Détruit l'intégralité de l'infrastructure AWS (ATTENTION : destructif)
	@echo "ATTENTION : cette action va détruire toute l'infrastructure AWS déployée."
	cd $(TERRAFORM_DIR) && terraform destroy

tf-output: ## Affiche les sorties Terraform (dont le DNS de l'ALB)
	cd $(TERRAFORM_DIR) && terraform output

# ==============================================================================
# DOCKER - Build et publication de l'image applicative
# ==============================================================================

docker-build: ## Construit l'image Docker de l'application
	cd $(APP_DIR) && docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

docker-push: docker-build ## Construit puis publie l'image Docker sur le registre et refresh ASG
	docker push lhassan1/truck-traffic-app:latest
	$(MAKE) aws-refresh

aws-refresh: ## Force l'Auto Scaling Group à charger la nouvelle image
	@echo "🔄 Lancement de l'Instance Refresh pour l'ASG..."
	aws autoscaling start-instance-refresh --auto-scaling-group-name lafarge-truck-traffic-asg --region eu-west-3 --output json || echo "⚠️ Un refresh est déjà en cours, tout est OK."

# ==============================================================================
# NETTOYAGE
# ==============================================================================

clean: local-clean ## Nettoie la stack locale et les fichiers temporaires Terraform
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -f $(TERRAFORM_DIR)/tfplan $(BOOTSTRAP_DIR)/tfplan
	@echo "Nettoyage terminé."
