# Lafarge — Truck Traffic Management (IaaS Production)

Plateforme de gestion du trafic des camions, déployée de manière hautement
disponible, automatisée et monitorée sur AWS — avec un mode 100% local pour
valider le fonctionnement avant tout déploiement cloud.

## Architecture cible (AWS)

```
Internet
   │
   ▼
[ALB : 80 HTTP]  (2 AZ)
   │
   ├──▶ [EC2 - Subnet public AZ1] ── docker: truck-traffic-app:8000→80
   └──▶ [EC2 - Subnet public AZ2] ── docker: truck-traffic-app:8000→80
              (Auto Scaling Group, min=2 / max=4, target-tracking CPU 60%)

[Instance monitoring séparée]
   docker-compose: Prometheus + Alertmanager + Grafana
   Prometheus ──scrape──▶ ALB (métriques app) + EC2 via ec2_sd (node_exporter)
   Prometheus ──alertes──▶ Alertmanager ──webhook──▶ Slack

[State Terraform]
   S3 (versionné + chiffré) + verrouillage DynamoDB
```

## Arborescence

```
lafarge-truck-traffic/
├── app/
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── terraform/
│   ├── bootstrap/          # Backend S3 + DynamoDB (à lancer une seule fois)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── main.tf              # Infra AWS (VPC, ALB HTTP:80, ASG...)
│   ├── variables.tf
│   └── outputs.tf
├── monitoring/
│   ├── docker-compose.yml   # Stack monitoring AWS (instance dédiée)
│   ├── prometheus.yml       # Scraping via ALB + découverte EC2
│   ├── prometheus.local.yml # Scraping en mode local
│   ├── alertmanager.yml
│   └── alert_rules.yml
├── docker-compose.local.yml # Stack complète locale (app + monitoring)
├── Jenkinsfile
└── README.md
```

---

## MODE 1 — Test local (sans AWS)

But : valider que l'application et toute la chaîne d'observabilité
fonctionnent avant tout déploiement cloud.

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Accès :
| Service       | URL                              |
|---------------|-----------------------------------|
| Dashboard     | http://localhost:8080             |
| Métriques app | http://localhost:8080/metrics     |
| Prometheus    | http://localhost:9090             |
| Alertmanager  | http://localhost:9093             |
| Grafana       | http://localhost:3000 (admin / ChangeMe_Lafarge2026!) |

Test rapide :
```bash
# Simuler l'entrée d'un camion
curl -X POST "http://localhost:8080/api/trucks/enter?plate=MK-1234-A"

# Vérifier que la métrique apparaît
curl http://localhost:8080/metrics | grep trucks_processed_total

# Vérifier que Prometheus la collecte bien
curl 'http://localhost:9090/api/v1/query?query=trucks_processed_total'
```

Arrêt complet (avec suppression des volumes) :
```bash
docker compose -f docker-compose.local.yml down -v
```

---

## MODE 2 — Déploiement AWS (production)

### 1. Prérequis
- Compte AWS avec droits IAM (VPC, EC2, ELBv2, ASG, IAM, S3, DynamoDB)
- Terraform >= 1.5
- Docker + compte registre (Docker Hub ou ECR)
- Jenkins avec plugins : Docker Pipeline, AWS Credentials, Pipeline AWS Steps
- Une paire de clés EC2 existante (`key_pair_name` dans `variables.tf`)

### 2. Bootstrap du backend Terraform (UNE SEULE FOIS)
```bash
cd terraform/bootstrap
terraform init
terraform apply
```
⚠️ Le nom du bucket S3 (`state_bucket_name`, par défaut
`lafarge-truck-traffic-tfstate-eu-west3`) doit être **globalement unique sur
AWS**. Si le apply échoue avec `BucketAlreadyExists`, changez cette valeur
dans `terraform/bootstrap/variables.tf` **et** reportez la même valeur dans
le bloc `backend "s3"` de `terraform/main.tf` (ces deux fichiers doivent
rester synchronisés, un bloc `backend` ne pouvant pas lire une variable).

### 3. Build et publication de l'image applicative
```bash
cd app
docker build -t lafargeholcim/truck-traffic-app:latest .
docker push lafargeholcim/truck-traffic-app:latest
```

### 4. Déploiement de l'infrastructure principale
```bash
cd terraform
terraform init      # se connecte au backend S3 créé à l'étape 2
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

Récupérer le DNS du Load Balancer :
```bash
terraform output -raw alb_dns_name
```
L'application est alors accessible en HTTP simple sur `http://<alb_dns_name>/`.

### 5. Mise à jour du monitoring avec l'ALB réel
Remplacer la valeur du target dans `monitoring/prometheus.yml` (job
`truck-traffic-app`) par la sortie `alb_dns_name` ci-dessus, puis lancer la
stack sur une instance dédiée :
```bash
cd monitoring
docker compose up -d
```

### 6. Configuration du webhook Slack (production)
Remplacer `api_url` dans `monitoring/alertmanager.yml` par le véritable
webhook Slack, à stocker comme secret plutôt qu'en clair dans le dépôt Git.

### 7. Automatisation via Jenkins
Pipeline pointant sur le `Jenkinsfile` à la racine, credentials
`dockerhub-credentials` et `aws-credentials` configurés. Chaque build :
build image → push → `terraform plan/apply` (via le backend S3) → rolling
update de l'ASG → smoke test `/healthz`.

---

## Points d'attention pour une mise en production plus poussée
- Le Load Balancer reste en HTTP:80 pour simplifier la démo (choix validé) :
  pour une vraie prod, ajouter un listener 443 + certificat ACM + redirection 80→443.
- Restreindre `admin_cidr_ssh` à un VPN/bastion réel, ne jamais l'ouvrir en `0.0.0.0/0`.
- Déplacer `GF_SECURITY_ADMIN_PASSWORD` et le webhook Slack vers un gestionnaire
  de secrets (AWS Secrets Manager / Jenkins Credentials).
- Ajouter des subnets privés + NAT Gateway si les instances ne doivent pas être
  exposées avec une IP publique directe (actuellement en subnets publics pour
  simplifier le HA de niveau démo).
Testing Jenkins automation
Pipeline test #2
Pipeline test #2
Pipeline test #3
Pipeline test #4
Pipeline test #5
Pipeline test #6
