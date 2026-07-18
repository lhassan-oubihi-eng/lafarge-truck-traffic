variable "aws_region" {
  description = "Région AWS de déploiement de l'infrastructure"
  type        = string
  default     = "eu-west-3" # Paris - région recommandée pour la conformité data EU
}

variable "project_name" {
  description = "Nom du projet, utilisé comme préfixe pour le nommage des ressources"
  type        = string
  default     = "lafarge-truck-traffic"
}

variable "environment" {
  description = "Environnement de déploiement (production, staging, dev)"
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "Bloc CIDR du VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Blocs CIDR des 2 subnets publics (un par zone de disponibilité)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "availability_zones" {
  description = "Zones de disponibilité utilisées pour la haute disponibilité"
  type        = list(string)
  default     = ["eu-west-3a", "eu-west-3b"]
}

variable "instance_type" {
  description = "Type d'instance EC2 utilisé par l'Auto Scaling Group"
  type        = string
  default     = "t3.micro"
}

variable "asg_min_size" {
  description = "Nombre minimum d'instances dans l'Auto Scaling Group"
  type        = number
  default     = 2
}

variable "asg_max_size" {
  description = "Nombre maximum d'instances dans l'Auto Scaling Group"
  type        = number
  default     = 4
}

variable "asg_desired_capacity" {
  description = "Nombre d'instances souhaité au démarrage"
  type        = number
  default     = 2
}

variable "key_pair_name" {
  description = "Nom de la paire de clés EC2 (SSH) existante dans le compte AWS, utilisée pour l'accès de dépannage aux instances"
  type        = string
  default     = "lafarge-devops-keypair"
}

variable "app_docker_image" {
  description = "Image Docker de l'application publiée sur le registre (Docker Hub ou ECR), construite et poussée par le pipeline Jenkins. Surchargée dynamiquement via TF_VAR_app_docker_image dans le pipeline CI/CD avec le tag BUILD_NUMBER ou GIT_HASH."
  type        = string
  default     = "lhassan1/truck-traffic-app:latest"
}

variable "certificate_arn" {
  description = "ARN du certificat ACM utilisé par le listener HTTPS du load balancer"
  type        = string
  default     = null
}

variable "admin_cidr_ssh" {
  description = "Bloc CIDR autorisé à se connecter en SSH (22) aux instances pour l'administration/dépannage. À restreindre au VPN/IP du bastion de l'entreprise."
  type        = string
  default     = "10.0.0.0/16" # Par défaut restreint au VPC interne uniquement
}

variable "tags" {
  description = "Tags communs appliqués à toutes les ressources"
  type        = map(string)
  default = {
    Project     = "TruckTrafficManagement"
    Owner       = "DevOps-Lafarge"
    ManagedBy   = "Terraform"
    Environment = "production"
  }
}
variable "db_password" {
  description = "Password for WordPress database"
  type        = string
  sensitive   = true # كيحمي الباسورد باش ما يبانش في الـ Logs
}

variable "db_root_password" {
  description = "Root password for MySQL"
  type        = string
  sensitive   = true
}
