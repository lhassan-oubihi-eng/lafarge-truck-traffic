# 🚚 Lafarge Truck Traffic Management
*Infrastructure as Code (IaC) | CI/CD | High Availability*

Plateforme de gestion du trafic des camions, déployée de manière hautement disponible et automatisée sur **AWS**, avec un mode local pour le développement et la validation.

---

## 🏗️ Architecture du Projet
L'application est conteneurisée et déployée sur un **Auto Scaling Group (ASG)** derrière un **Application Load Balancer (ALB)**.

```mermaid
graph LR
    A[Internet] --> B(ALB)
    B --> C[EC2 Instance 1]
    B --> D[EC2 Instance 2]
    C & D --> E[(ASG - Multi AZ)]
```

---

## 📂 Organisation des fichiers

```text
.
.
├── app/                        # Code source de l'application
│   ├── app.py                  # Application principale
│   ├── Dockerfile              # Configuration Docker de l'app
│   ├── requirements.txt        # Dépendances Python
│   └── tests/                  # Tests unitaires
│       ├── __pycache__/        # Cache Python
│       └── test_app.py         # Fichier de tests pytest
├── terraform/                  # Infrastructure as Code (AWS)
│   ├── bootstrap/              # Configuration backend (S3/DynamoDB)
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   ├── terraform.tfstate
│   │   ├── terraform.tfstate.backup
│   │   └── variables.tf
│   ├── main.tf                 # Définition de l'infra (ALB, ASG, EC2)
│   ├── outputs.tf              # Sorties Terraform
│   ├── tfplan                  # Plan d'exécution Terraform
│   └── variables.tf            # Variables d'infrastructure
├── monitoring/                 # Stack de monitoring
│   ├── alertmanager.yml        # Configuration alertes
│   ├── alert_rules.yml         # Règles d'alerte
│   ├── docker-compose.yml      # Stack monitoring (Prometheus/Grafana)
│   ├── prometheus.local.yml    # Config Prometheus mode local
│   └── prometheus.yml          # Config Prometheus mode prod
├── jenkins-config/             # Configuration legacy Jenkins
│   └── Dockerfile
├── .github/workflows/          # Pipelines CI/CD (GitHub Actions)
├── docker-compose.local.yml    # Stack locale complète
├── Jenkinsfile                 # Pipeline CI/CD legacy
├── Makefile                    # Commandes de développement
├── README.md                   # Documentation du projet
├── nul                         # Fichier système
└── Jenkinsfile                 # Pipeline CI/CD

```

---

## ⚡ Workflow CI/CD (GitHub Actions)

Le déploiement est **100% automatisé**. Chaque `push` sur la branche `main` exécute :

| Étape | Action | Statut |
| --- | --- | --- |
| **Build** | Création image Docker | ✅ |
| **Push** | Publication Docker Hub | ✅ |
| **Terraform** | Mise à jour infra AWS | ✅ |
| **Refresh** | Déploiement sur ASG | ✅ |
| **Notify** | Alerte Discord | 🔔 |

---

## 🛠️ Guide d'utilisation avec `make`

Pour simplifier votre quotidien, nous utilisons un `Makefile`. Voici les commandes disponibles :

### 🖥️ Développement Local

* `make local-up` : Lance la stack complète (App + Monitoring).
* `make local-down` : Arrête la stack sans supprimer les données.
* `make local-clean` : Arrête tout et supprime les volumes (Reset complet).
* `make app-test` : Simulation d'entrée de camion pour valider les métriques.
* `make test` : Exécute les tests unitaires avec `pytest`.

### 🏗️ Infrastructure & AWS

* `make tf-init` : Initialise Terraform avec le backend S3.
* `make tf-plan` : Prévisualise les changements sur AWS.
* `make tf-apply` : Applique les changements d'infrastructure.
* `make aws-refresh` : Force l'Auto Scaling Group à déployer la dernière image Docker.

*(Tapez `make help` dans votre terminal pour voir la liste complète des commandes).*

---

## 🔑 Configuration (Secrets GitHub)

Pour activer le déploiement automatique, configurez ces variables dans **Settings > Secrets > Actions** :

* `AWS_ACCESS_KEY_ID` & `AWS_SECRET_ACCESS_KEY`
* `DOCKERHUB_USERNAME` & `DOCKERHUB_TOKEN`
* `DISCORD_WEBHOOK`

---

