# Lafarge — Truck Traffic Management (IaaS Production)

Plateforme de gestion du trafic des camions, déployée de manière hautement disponible et automatisée sur AWS, avec un mode local pour le développement.

## Arborescence du projet
```
.
├── .github/workflows/   # Pipeline CI/CD (GitHub Actions)
├── app/                 # Code source Python + Dockerfile
├── jenkins-config/      # Configuration Jenkins (legacy/optionnel)
├── Makefile             # Raccourcis pour le développement local
├── monitoring/          # Stack Monitoring (Prometheus/Grafana)
├── terraform/           # Infrastructure as Code (AWS)
│   ├── bootstrap/       # Backend S3 + DynamoDB
│   └── main.tf          # Définition ALB, ASG, EC2
└── README.md
```
Workflow d'utilisation (Comment travailler)
1. Développement Local (Test)
Avant de pousser votre code sur le serveur, validez toujours en local :

Lancer la stack : make local-up

Exécuter les tests : make test

Arrêter la stack : make local-clean

2. Automatisation CI/CD (Production AWS)
Nous utilisons GitHub Actions pour le déploiement. Il n'est plus nécessaire d'intervenir manuellement sur AWS.

Le cycle de vie du code :

Code : Vous modifiez le code dans app/ ou l'infrastructure dans terraform/.

Commit & Push : git add . && git commit -m "..." && git push origin main.

CI (GitHub Actions) :

Docker Job : Build de l'image et push sur Docker Hub.

Deploy Job : Exécute terraform apply pour mettre à jour l'infrastructure.

Refresh : Force un instance-refresh sur l'Auto Scaling Group (ASG) pour déployer la nouvelle version sans interruption.

Notification : Un message de statut (Succès/Échec) est envoyé automatiquement sur votre canal Discord.

Prérequis pour le déploiement AWS
Pour que le pipeline fonctionne, les secrets suivants doivent être configurés dans les Settings > Secrets and variables > Actions de votre repo GitHub :

AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY

DOCKERHUB_USERNAME & DOCKERHUB_TOKEN

DISCORD_WEBHOOK

Infrastructure (Terraform)
Bootstrap : Le dossier terraform/bootstrap doit être lancé une seule fois pour créer le bucket S3 (stockage du state) et la table DynamoDB (verrouillage).

Main : L'infrastructure principale (VPC, ALB, ASG) est gérée via le dossier terraform/.
