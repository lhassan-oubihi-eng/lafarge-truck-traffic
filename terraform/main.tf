# ============================================================================
# Fichier principal Terraform - Infrastructure « LaFarge Truck Traffic »
# Configure un VPC public avec ALB, ASG d'instances EC2 et politique
# de scaling automatique sur AWS (région eu-west-3 / Paris).
# ============================================================================

# --------------------------------------------------------------------------
# Bloc terraform : version minimale, fournisseurs requis et backend distant
# --------------------------------------------------------------------------
terraform {
  # Impose Terraform >= 1.5 pour disposer des fonctions "moved" / "import"
  # et du support natif du backend S3 avec validation du state.
  required_version = ">= 1.5.0"

  # Déclare le fournisseur AWS avec un plafond de version majeure (5.x)
  # afin d'éviter les breaking changes lors des mises à jour mineures.
  required_providers {
    aws = {
      source  = "hashicorp/aws"   # Registre officiel HashiCorp
      version = "~> 5.0"          # Accepte 5.0, 5.1, … mais pas 6.0
    }
  }

  # Backend distant S3 + verrouillage DynamoDB : permet le partage sécurisé
  # du state entre les développeurs et le pipeline Jenkins, avec historique
  # de versions (S3 versioning) et protection contre les exécutions
  # concurrentes (DynamoDB lock).
  backend "s3" {
    bucket         = "lafarge-truck-traffic-tfstate-eu-west3"  # Bucket dédié au state
    key            = "truck-traffic/terraform.tfstate"          # Chemin dans le bucket
    region         = "eu-west-3"                                # Région AWS (Paris)
    dynamodb_table = "lafarge-truck-traffic-tfstate-lock"       # Table DynamoDB pour verrouillage du state
    encrypt        = true                                       # Chiffrement SSE activé pour le state distant
  }
}

# --------------------------------------------------------------------------
# Provider AWS : région cible pour toutes les ressources suivantes
# --------------------------------------------------------------------------
provider "aws" {
  region = var.aws_region  # Variable définie dans variables.tf (ex: eu-west-3 pour Paris)
}

# --------------------------------------------------------------------------
# Donnée : AMI Amazon Linux 2023 la plus récente (évite les AMI figées)
# --------------------------------------------------------------------------
# Récupère dynamiquement l'identifiant de la dernière AMI Amazon Linux 2023
# compatible x86_64 / HVM, afin de toujours déployer les correctifs de sécurité.
data "aws_ami" "amazon_linux" {
  most_recent = true          # Sélectionne l'AMI la plus récente publiée par Amazon
  owners      = ["amazon"]    # Restreint aux AMIs publiées par le compte officiel Amazon

  # Filtre par nom : al2023-ami-*-x86_64 (toutes les versions mineures)
  filter {
    name   = "name"                                    # Champ de filtrage : nom de l'AMI
    values = ["al2023-ami-*-x86_64"]                   # Motif : al2023 suivi de n'importe quelle version mineure
  }

  # Filtre par type de virtualisation HVM (nécessaire pour le matériel Nitro d'AWS)
  filter {
    name   = "virtualization-type"                     # Champ de filtrage : type de virtualisation
    values = ["hvm"]                                   # HVM (Hardware Virtual Machine) requis pour les instances modernes
  }
}

# --------------------------------------------------------------------------
# VPC : réseau privé virtuel isolé
# --------------------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr       # Bloc CIDR principal du VPC (ex: 10.0.0.0/16)
  enable_dns_support   = true               # Résolution DNS interne activée (nécessaire pour les endpoints internes)
  enable_dns_hostnames = true               # Attribution automatique de noms DNS publics/privés aux instances

  # Fusionne les tags globaux du projet avec un tag Name spécifique
  tags = merge(var.tags, {
    Name = "${var.project_name}-vpc"         # Nom lisible du VPC dans la console AWS
  })
}

# --------------------------------------------------------------------------
# Internet Gateway : passerelle vers Internet pour les sous-réseaux publics
# --------------------------------------------------------------------------
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id  # Associe la passerelle Internet au VPC créé ci-dessus

  tags = merge(var.tags, {
    Name = "${var.project_name}-igw"         # Nom de l'Internet Gateway dans la console AWS
  })
}

# --------------------------------------------------------------------------
# Subnets publics (haute disponibilité sur 2 zones de disponibilité)
# --------------------------------------------------------------------------
# Crée N sous-réseaux publics (1 par AZ) en itérant sur les CIDRs fournis dans la variable.
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)  # Nombre de subnets à créer (typiquement 2 pour la HA)
  vpc_id                  = aws_vpc.main.id                  # VPC parent auquel rattacher le subnet
  cidr_block              = var.public_subnet_cidrs[count.index]  # CIDR du subnet courant dans la boucle
  availability_zone       = var.availability_zones[count.index]   # Zone de disponibilité cible (eu-west-3a, eu-west-3b)
  map_public_ip_on_launch = true    # Attribution automatique d'une IP publique aux instances lancées dans ce subnet

  tags = merge(var.tags, {
    Name = "${var.project_name}-public-subnet-${count.index + 1}"  # Nom lisible (index 1-based pour la console)
  })
}

# --------------------------------------------------------------------------
# Route Table publique : route par défaut vers l'Internet Gateway
# --------------------------------------------------------------------------
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id  # VPC associé à cette table de routage publique

  # Route par défaut : tout le trafic sortant (0.0.0.0/0) transite par l'Internet Gateway
  route {
    cidr_block = "0.0.0.0/0"                  # Toutes les adresses IP de destination
    gateway_id = aws_internet_gateway.main.id  # Passerelle Internet pour sortir vers le web
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-public-rt"    # Nom de la route table publique
  })
}

# --------------------------------------------------------------------------
# Association route table ↔ subnets publics
# --------------------------------------------------------------------------
# Lie chaque subnet public à la route table qui contient la route vers Internet.
resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)          # Une association par subnet public créé
  subnet_id      = aws_subnet.public[count.index].id  # Subnet public à associer
  route_table_id = aws_route_table.public.id           # Route table publique qui contient la route par défaut
}

# --------------------------------------------------------------------------
# Security Group : Application Load Balancer
# --------------------------------------------------------------------------
# Règles de pare-feu pour l'ALB : autorise HTTP/HTTPS depuis Internet,
# limite le trafic sortant au VPC uniquement (sécurité renforcée).
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-sg"   # Nom du security group
  description = "Allow inbound public HTTP traffic to the Load Balancer"  # Description lisible
  vpc_id      = aws_vpc.main.id  # VPC dans lequel s'applique le security group

  # Règle d'entrée : HTTP (port 80) depuis n'importe quelle source Internet
  ingress {
    description = "Allow HTTP inbound from Internet"  # Description de cette règle
    from_port   = 80                                   # Port de début (80 = HTTP)
    to_port     = 80                                   # Port de fin (intervalle 80-80 = port unique)
    protocol    = "tcp"                                # Protocole TCP
    cidr_blocks = ["0.0.0.0/0"]                       # Toute adresse IP source (Internet public)
  }

  # Règle d'entrée : HTTPS (port 443) depuis n'importe quelle source Internet
  ingress {
    description = "Allow HTTPS inbound from Internet"  # Description de cette règle
    from_port   = 443                                  # Port de début (443 = HTTPS)
    to_port     = 443                                  # Port de fin
    protocol    = "tcp"                                # Protocole TCP
    cidr_blocks = ["0.0.0.0/0"]                       # Toute adresse IP source (Internet public)
  }

  # Règle de sortie : tout le trafic autorisé, mais uniquement vers le VPC
  # (l'ALB ne communique qu'avec les instances backend dans le VPC)
  egress {
    description = "Outbound traffic restricted to the VPC"  # Description de cette règle
    from_port   = 0                                          # Tous les ports (début)
    to_port     = 0                                          # Tous les ports (fin)
    protocol    = "-1"                                       # Tous les protocoles (TCP, UDP, ICMP, etc.)
    cidr_blocks = [var.vpc_cidr]                             # Seulement le CIDR du VPC (pas d'accès Internet sortant)
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-alb-sg"  # Tag Name du security group ALB
  })
}

# --------------------------------------------------------------------------
# Security Group : Instances EC2 applicatives
# --------------------------------------------------------------------------
# Règles de pare-feu pour les instances de l'application :
#   - Port 8000 : trafic applicatif depuis l'ALB uniquement
#   - Port 9100 : métriques Node Exporter (Prometheus) depuis le VPC
#   - Port 22  : SSH depuis le réseau d'administration uniquement
resource "aws_security_group" "ec2_app" {
  name        = "${var.project_name}-ec2-sg"  # Nom du security group EC2
  description = "Allow HTTP traffic from ALB and SSH from admin network"  # Description lisible
  vpc_id      = aws_vpc.main.id  # VPC dans lequel s'applique ce security group

  # Entrée : port 8000 depuis le SG de l'ALB (référence au SG, pas de CIDR, plus sécurisé)
  ingress {
    description     = "App traffic only from Load Balancer (target port 8000)"  # Description
    from_port       = 8000   # Port applicatif exposé par le conteneur Docker
    to_port         = 8000   # Port applicatif
    protocol        = "tcp"  # Protocole TCP
    security_groups = [aws_security_group.alb.id]  # Source = SG de l'ALB uniquement (pas d'IP)
  }

  # Entrée : port 9100 (Node Exporter) accessible depuis le VPC pour Prometheus
  ingress {
    description = "Node Exporter metrics accessible within VPC for Prometheus"  # Description
    from_port   = 9100   # Port par défaut de Node Exporter
    to_port     = 9100   # Port par défaut de Node Exporter
    protocol    = "tcp"  # Protocole TCP
    cidr_blocks = [var.vpc_cidr]  # Trafic interne au VPC uniquement (pas d'accès externe aux métriques)
  }

  # Entrée : SSH (port 22) depuis le réseau d'administration uniquement
  ingress {
    description = "SSH for administration restricted to internal network"  # Description
    from_port   = 22           # Port SSH standard
    to_port     = 22           # Port SSH standard
    protocol    = "tcp"        # Protocole TCP
    cidr_blocks = [var.admin_cidr_ssh]  # CIDR du réseau d'administration défini dans les variables
  }

  # Sortie : tout le trafic autorisé vers Internet (Docker pulls, mises à jour, appels API)
  egress {
    description = "Allow all outbound traffic (Docker pulls, package updates, API calls)"  # Description
    from_port   = 0            # Tous les ports (début)
    to_port     = 0            # Tous les ports (fin)
    protocol    = "-1"         # Tous les protocoles
    cidr_blocks = ["0.0.0.0/0"]  # Toute destination (Internet public)
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-ec2-sg"  # Tag Name du security group EC2
  })
}

# --------------------------------------------------------------------------
# IAM : rôle d'instance pour AWS Systems Manager (SSM)
# --------------------------------------------------------------------------
# Le rôle IAM permet aux instances EC2 de communiquer avec le service SSM
# pour l'administration à distance (Session Manager, Patch Manager, etc.)
# sans nécessiter de clé SSH exposée sur Internet.
resource "aws_iam_role" "ec2_role" {
  name = "${var.project_name}-ec2-role"  # Nom du rôle IAM

  # Politique d'assume-role : autorise le service EC2 à endosser ce rôle
  assume_role_policy = jsonencode({
    Version = "2012-10-17"  # Version de la politique IAM (date de publication)
    Statement = [{
      Action    = "sts:AssumeRole"                    # Action STS autorisée : prise de rôle
      Effect    = "Allow"                              # Autorisation explicite (pas de refus)
      Principal = { Service = "ec2.amazonaws.com" }    # Seul le service EC2 peut assumer ce rôle
    }]
  })

  tags = var.tags  # Propagation des tags globaux du projet
}

# Attache la policy AWS managed "AmazonSSMManagedInstanceCore" au rôle :
# autorise les appels SSM (Parameter Store, Session Manager, Run Command…)
resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.ec2_role.name                                    # Rôle IAM cible
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"  # ARN de la policy AWS managed pour SSM
}

# Politique IAM custom : autorise l'accès S3 (logs applicatifs) et
# Secrets Manager (récupération des mots de passe base de données)
resource "aws_iam_role_policy" "ec2_app" {
  name = "${var.project_name}-ec2-app-policy"  # Nom de la politique IAM
  role = aws_iam_role.ec2_role.id               # Rôle IAM auquel cette politique est attachée

  # Contenu de la politique en JSON
  policy = jsonencode({
    Version = "2012-10-17"  # Version du langage de politique IAM
    Statement = [
      {
        # Autorise les opérations de base sur S3 pour le bucket de logs applicatifs
        Sid    = "S3Access"           # Identifiant unique de la déclaration
        Effect = "Allow"               # Autorisation explicite
        Action = [
          "s3:HeadBucket",             # Vérifier l'existence du bucket
          "s3:CreateBucket",            # Créer le bucket s'il n'existe pas encore
          "s3:PutObject",               # Écrire des fichiers de log dans le bucket
          "s3:GetObject",               # Lire des objets depuis le bucket
          "s3:ListBucket",              # Lister le contenu du bucket
        ]
        Resource = [
          "arn:aws:s3:::truck-traffic-logs",    # ARN du bucket lui-même (pour HeadBucket, ListBucket)
          "arn:aws:s3:::truck-traffic-logs/*",  # ARN de tous les objets du bucket (pour Get/PutObject)
        ]
      },
      {
        # Autorise la lecture des secrets dans AWS Secrets Manager
        # Utilisé pour récupérer les mots de passe de la base de données
        Sid    = "SecretsManagerAccess"  # Identifiant unique de la déclaration
        Effect = "Allow"                  # Autorisation explicite
        Action = ["secretsmanager:GetSecretValue"]  # Action : lecture de la valeur d'un secret
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:*:secret:lafarge/truck-traffic/*",
          # ARN pattern : tous les secrets commençant par "lafarge/truck-traffic/" dans la région courante
        ]
      },
      {
        Sid    = "MonitoringAccess"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:GetMetricData",
          "cloudwatch:PutMetricData",
          "autoscaling:DescribeAutoScalingGroups",
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
        ]
        Resource = ["*"]
      },
    ]
  })
}

# Instance profile : conteneur qui encapsule le rôle IAM pour l'attacher aux instances EC2
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-instance-profile"  # Nom du profil d'instance
  role = aws_iam_role.ec2_role.name                   # Nom du rôle IAM à encapsuler
}

# --------------------------------------------------------------------------
# Application Load Balancer (public)
# --------------------------------------------------------------------------

# Bucket S3 destiné à stocker les logs d'accès générés par l'ALB
resource "aws_s3_bucket" "alb_access_logs" {
  bucket = "${var.project_name}-alb-access-logs"  # Nom globalement unique du bucket S3

  tags = merge(var.tags, {
    Name = "${var.project_name}-alb-access-logs"  # Tag Name du bucket
  })
}

# Bloque tout accès public au bucket de logs (principe de sécurité par défaut)
resource "aws_s3_bucket_public_access_block" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id  # ID du bucket à protéger

  block_public_acls       = true  # Bloque les ACLs publiques sur les objets
  block_public_policy     = true  # Bloque les politiques IAM publiques sur le bucket
  ignore_public_acls      = true  # Ignore toute ACL publique existante
  restrict_public_buckets = true  # Restreint l'accès si une politique publique est définie
}

# Active les logs d'accès du bucket S3 sur lui-même (auto-logging des requêtes)
resource "aws_s3_bucket_logging" "alb_access_logs" {
  bucket        = aws_s3_bucket.alb_access_logs.id  # Bucket source des logs
  target_bucket = aws_s3_bucket.alb_access_logs.id  # Bucket cible (identique = auto-logging)
  target_prefix = "bucket-access-logs/"              # Préfixe de dossier pour les logs générés
}

# Politique S3 : autorise le service ELB à écrire les logs d'accès
# et impose l'utilisation de HTTPS pour toutes les connexions
resource "aws_s3_bucket_policy" "alb_access_logs" {
  bucket = aws_s3_bucket.alb_access_logs.id  # Bucket auquel s'applique cette politique

  policy = jsonencode({
    Version = "2012-10-17"  # Version du langage de politique de bucket S3
    Statement = [
      {
        # Autorise le service ELB (log delivery) à écrire les logs d'accès dans le bucket
        Sid       = "AllowALBLogs"                                     # Identifiant de la déclaration
        Effect    = "Allow"                                             # Autorisation explicite
        Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com" }  # Service ELB autorisé
        Action    = "s3:PutObject"                                      # Action : écrire un objet
        Resource  = "${aws_s3_bucket.alb_access_logs.arn}/*"           # Cible : tous les objets du bucket
        Condition = {
          StringEquals = {
            "s3:x-amz-acl" = "bucket-owner-full-control"  # ACL requise par le service ELB pour écrire
          }
        }
      },
      {
        # Refuse toute opération S3 si la connexion n'est pas chiffrée (HTTPS)
        Sid       = "EnforceHTTPS"                  # Identifiant de la déclaration
        Effect    = "Deny"                           # Refus explicite
        Principal = "*"                              # S'applique à tout le monde
        Action    = "s3:*"                           # Toutes les actions S3
        Resource = [
          aws_s3_bucket.alb_access_logs.arn,         # Le bucket lui-même
          "${aws_s3_bucket.alb_access_logs.arn}/*"   # Tous les objets du bucket
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"  # Condition : transport NON sécurisé (HTTP)
          }
        }
      }
    ]
  })
}

# Application Load Balancer : point d'entrée public du trafic HTTP/HTTPS
resource "aws_lb" "app" {
  name               = "${var.project_name}-alb"       # Nom du Load Balancer dans la console AWS
  internal           = false                            # Load Balancer public (accessible depuis Internet)
  load_balancer_type = "application"                    # Type ALB (couche OSI 7 = HTTP/HTTPS)
  security_groups    = [aws_security_group.alb.id]     # Security group associé (ports HTTP/HTTPS)
  subnets            = aws_subnet.public[*].id         # Déploiement dans tous les subnets publics (HA)

  # Désactive la protection contre la suppression (pratique pour les environnements dev/staging)
  enable_deletion_protection = false

  # Active l'envoi des logs d'accès vers le bucket S3 dédié à des fins d'audit
  access_logs {
    enabled = true                                       # Logs activés
    bucket  = aws_s3_bucket.alb_access_logs.id           # Bucket de destination
    prefix  = "alb"                                      # Préfixe de dossier dans le bucket
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-alb"  # Tag Name de l'ALB
  })
}

# Target Group : groupe de cibles (instances EC2) qui reçoivent le trafic de l'ALB
resource "aws_lb_target_group" "app" {
  name     = "${var.project_name}-tg"  # Nom du target group
  port     = 8000                      # Port d'écoute des instances applicatives (conteneur Docker)
  protocol = "HTTP"                    # Protocole HTTP entre l'ALB et les instances (pas de TLS interne)
  vpc_id   = aws_vpc.main.id           # VPC dans lequel se trouvent les instances cibles

  # Vérification de santé : l'ALB interroge régulièrement l'endpoint /healthz
  health_check {
    enabled             = true                          # Vérification de santé activée
    path                = "/healthz"                    # Chemin HTTP à tester
    protocol            = "HTTP"                        # Protocole de la requête de health check
    port                = 8000                          # Port du health check
    matcher             = "200"                         # Code HTTP attendu pour considérer l'instance saine
    interval            = 30                            # Intervalle entre deux health checks (30 secondes)
    timeout             = 5                             # Délai d'attente max avant considérer l'instance comme morte (5s)
    healthy_threshold   = 2                             # Nombre de succès consécutifs pour passer en "healthy"
    unhealthy_threshold = 3                             # Nombre d'échecs consécutifs pour passer en "unhealthy"
  }

  # Délai de dé-référencement : attend 30 secondes avant de couper les connexions actives
  deregistration_delay = 30

  tags = merge(var.tags, {
    Name = "${var.project_name}-tg"  # Tag Name du target group
  })
}

# --------------------------------------------------------------------------
# Listeners ALB : points d'écoute pour le trafic HTTP/HTTPS
# --------------------------------------------------------------------------

# Listener HTTP avec redirection vers HTTPS (actif uniquement si un certificat TLS est fourni)
resource "aws_lb_listener" "http_redirect" {
  # Condition ternaire : n'active ce listener que si certificate_arn est renseigné et non vide
  count = var.certificate_arn != null && trim(var.certificate_arn, " ") != "" ? 1 : 0

  load_balancer_arn = aws_lb.app.arn  # ARN de l'ALB parent auquel rattacher ce listener
  port               = 80             # Port d'écoute HTTP
  protocol           = "HTTP"         # Protocole d'écoute HTTP

  # Redirection 301 permanente vers le port HTTPS pour toutes les requêtes entrantes
  default_action {
    type = "redirect"  # Action de type redirection
    redirect {
      port        = "443"       # Port de destination de la redirection (HTTPS)
      protocol    = "HTTPS"     # Protocole de destination
      status_code = "HTTP_301"  # Code HTTP 301 (Moved Permanently)
    }
  }
}

# Listener HTTP simple : forward direct vers le target group (utilisé quand TLS n'est pas disponible)
resource "aws_lb_listener" "http_forward" {
  # Condition ternaire inverse : activé quand aucun certificat n'est fourni
  count = var.certificate_arn == null || trim(var.certificate_arn, " ") == "" ? 1 : 0

  load_balancer_arn = aws_lb.app.arn  # ARN de l'ALB parent
  port               = 80             # Port d'écoute HTTP
  protocol           = "HTTP"         # Protocole d'écoute HTTP

  # Transmet directement la requête entrante au target group applicatif
  default_action {
    type             = "forward"                       # Action de type forward
    target_group_arn = aws_lb_target_group.app.arn    # Cible : target group des instances EC2
  }
}

# Listener HTTPS : déchiffre le trafic TLS et le transmet au target group
resource "aws_lb_listener" "https" {
  # Condition : activé uniquement si un certificat ACM valide est fourni
  count = var.certificate_arn != null && trim(var.certificate_arn, " ") != "" ? 1 : 0

  load_balancer_arn = aws_lb.app.arn                  # ARN de l'ALB parent
  port               = 443                             # Port d'écoute HTTPS
  protocol           = "HTTPS"                         # Protocole d'écoute HTTPS avec TLS
  ssl_policy         = "ELBSecurityPolicy-TLS13-1-2-2021-06"  # Politique TLS incluant TLS 1.3 et 1.2 (recommandé AWS)
  certificate_arn    = var.certificate_arn             # ARN du certificat ACM à utiliser

  # Transmet le trafic HTTPS déchiffré au target group
  default_action {
    type             = "forward"                       # Action de type forward
    target_group_arn = aws_lb_target_group.app.arn    # Cible : target group des instances EC2
  }
}

# --------------------------------------------------------------------------
# Key Pair : import dans eu-west-3 (Paris) pour l'accès SSH aux instances
# --------------------------------------------------------------------------
resource "aws_key_pair" "app" {
  key_name   = var.key_pair_name       # Nom de la Key Pair tel qu'affiché dans la console AWS
  public_key = var.public_key_content  # Contenu de la clé publique au format OpenSSH (ssh-rsa AAAA...)

  tags = merge(var.tags, {
    Name = "${var.project_name}-keypair"  # Tag Name de la Key Pair
  })
}

# --------------------------------------------------------------------------
# Launch Template : configuration des instances EC2 applicatives
# --------------------------------------------------------------------------
# Définit le modèle de configuration pour toutes les instances lancées par l'ASG.
# Inclut l'AMI, le type d'instance, le profil IAM, le script d'amorçage, etc.
resource "aws_launch_template" "app" {
  name_prefix   = "${var.project_name}-lt-"           # Préfixe pour le nom généré automatiquement par Terraform
  image_id      = data.aws_ami.amazon_linux.id        # AMI dynamique : Amazon Linux 2023 la plus récente
  instance_type = var.instance_type                   # Type d'instance (ex: t3.medium, t3.large)
  key_name      = aws_key_pair.app.key_name           # Key Pair SSH pour accéder aux instances

  # Profil IAM : donne aux instances EC2 les droits S3, Secrets Manager et SSM
  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_profile.name  # Nom du profil d'instance IAM
  }

  # Configuration réseau de l'instance
  network_interfaces {
    associate_public_ip_address = true                # IP publique attribuée (nécessaire en subnet public)
    security_groups             = [aws_security_group.ec2_app.id]  # Security group applicatif
  }

  # Augmentation du volume racine : l'AMI AL2023 par défaut n'a que 2 Go,
  # ce qui est insuffisant pour Docker + MySQL + WordPress + l'application.
  # On passe à 30 Go gp3 pour éviter "no space left on device" lors du pull des images.
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  # Script d'amorçage (user data) : s'exécute au premier démarrage de l'instance.
  # Installe Docker, Node Exporter, puis lance le conteneur de l'application.
  # Les variables sensibles (image Docker, mots de passe DB) sont injectées
  # depuis les variables Terraform et encodées en base64 dans les métadonnées.
  user_data = base64encode(templatefile("${path.module}/user_data.sh.tpl", {
    app_docker_image   = var.app_docker_image      # Nom de l'image Docker de l'application
    db_password        = var.db_password           # Mot de passe de la base de données
    db_root_password   = var.db_root_password      # Mot de passe root de la base de données
    dockerhub_username = var.dockerhub_username    # Docker Hub username (évite rate limiting)
    dockerhub_password = var.dockerhub_password    # Docker Hub password/token
    aws_region         = var.aws_region            # Region AWS (CloudWatch agent, env vars)
    alb_arn_suffix     = aws_lb.app.arn_suffix     # ALB ARN suffix pour CloudWatch latency metrics
    alb_dns_name       = aws_lb.app.dns_name       # ALB DNS name (auto-découverte fallback)
    asg_name           = "${var.project_name}-asg"  # ASG name pour monitoring
    logs_bucket_name   = "truck-traffic-logs"  # S3 bucket name (logs applicatifs)
  }))

  # Specifications de tags : applique automatiquement des tags aux instances créées
  tag_specifications {
    resource_type = "instance"  # Type de ressource à taguer : instance EC2
    tags = merge(var.tags, {
      Name = "${var.project_name}-instance"  # Tag Name appliqué à chaque instance
    })
  }

  # Options des métadonnées : force l'utilisation obligatoire du token IMDSv2
  # pour protéger les instances contre les attaques SSRF et le vol de credentials
  metadata_options {
    http_tokens   = "required"   # IMDSv2 obligatoire (refuse les requêtes sans token)
    http_endpoint = "enabled"    # Endpoint des métadonnées activé (nécessaire pour SSM agent)
  }
}

# --------------------------------------------------------------------------
# Auto Scaling Group : gestion automatique du nombre d'instances
# --------------------------------------------------------------------------
# Gère le cycle de vie des instances EC2 : crée, supprime et remplace
# automatiquement les instances en fonction de la charge, des health checks
# ou des changements de configuration (rolling update).
resource "aws_autoscaling_group" "app" {
  name                = "${var.project_name}-asg"             # Nom de l'ASG
  min_size            = var.asg_min_size                     # Nombre minimum d'instances (toujours au moins 1)
  max_size            = var.asg_max_size                     # Nombre maximum d'instances (limite de scaling)
  desired_capacity    = var.asg_desired_capacity             # Nombre d'instances souhaité (entre min et max)
  vpc_zone_identifier = aws_subnet.public[*].id              # Subnets publics où déployer les instances
  target_group_arns   = [aws_lb_target_group.app.arn]        # Target group ALB auquel rattacher les instances

  # Type de health check : ELB (plus fiable que le health check EC2 natif,
  # car il teste l'application via l'endpoint /healthz de l'ALB)
  health_check_type         = "ELB"
  health_check_grace_period = 500  # Période de grâce après lancement (500s) avant le premier health check

  # Référence le Launch Template dans sa version la plus récente
  launch_template {
    id      = aws_launch_template.app.id   # ID du Launch Template
    version = "$Latest"                     # Toujours utiliser la version la plus récente
  }

  # Stratégie de rafraîchissement des instances (instance refresh) :
  # remplace progressivement les instances par vagues lors d'un changement
  # de configuration (ex: nouvelle AMI, nouveau user_data)
  instance_refresh {
    strategy = "Rolling"           # Remplacement progressif (pas de tout-en-un)
    triggers = ["launch_template"] # Déclenché automatiquement quand le Launch Template change
    preferences {
      min_healthy_percentage = 50  # Au moins 50 % des instances doivent rester saines pendant le refresh
      instance_warmup        = 60  # Délai de 60s avant qu'une nouvelle instance ne soit considérée saine
    }
  }

  # Tag "Name" propagé à chaque instance EC2 créée par cet ASG
  tag {
    key                 = "Name"                           # Clé du tag
    value               = "${var.project_name}-asg-instance"  # Valeur du tag
    propagate_at_launch = true  # Propager le tag aux instances EC2 au lancement
  }

  # Boucle dynamique : propage tous les tags globaux du projet aux instances
  dynamic "tag" {
    for_each = var.tags  # Itère sur chaque entrée du map var.tags
    content {
      key                 = tag.key       # Clé du tag (ex: "Environment", "ManagedBy")
      value               = tag.value     # Valeur du tag (ex: "production", "Terraform")
      propagate_at_launch = true          # Propager aux instances EC2 au lancement
    }
  }
}

# --------------------------------------------------------------------------
# Politiques de scaling automatique basé sur le CPU (Target Tracking)
# --------------------------------------------------------------------------
# Augmente le nombre d'instances lorsque l'utilisation CPU moyenne de l'ASG
# dépasse 60 %, et les réduit automatiquement quand la charge redescend.
resource "aws_autoscaling_policy" "scale_out" {
  name                   = "${var.project_name}-scale-out"          # Nom de la politique de scaling
  autoscaling_group_name = aws_autoscaling_group.app.name           # ASG auquel s'applique cette politique
  policy_type            = "TargetTrackingScaling"                  # Type : suivi d'une cible (CPU à 60 %)

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"  # Métrique : utilisation CPU moyenne de l'ASG
    }
    target_value = 60.0  # Valeur cible : maintient le CPU moyen à 60 % (scaling up/down automatique)
  }
}
