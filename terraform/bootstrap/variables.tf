variable "aws_region" {
  description = "Région AWS où créer le bucket S3 et la table DynamoDB du backend"
  type        = string
  default     = "eu-west-3"
}

variable "project_name" {
  description = "Nom du projet, utilisé pour le tagging"
  type        = string
  default     = "lafarge-truck-traffic"
}

variable "state_bucket_name" {
  description = <<-EOT
    Nom du bucket S3 qui hébergera le fichier terraform.tfstate.
    IMPORTANT : les noms de bucket S3 sont GLOBALEMENT uniques sur l'ensemble
    d'AWS (tous comptes confondus). La valeur ci-dessous doit donc être
    vérifiée/adaptée avant le premier déploiement (par exemple en y ajoutant
    votre AWS Account ID) si elle est déjà prise par un autre compte.
  EOT
  type    = string
  default = "lafarge-truck-traffic-tfstate-eu-west3"
}

variable "dynamodb_table_name" {
  description = "Nom de la table DynamoDB utilisée pour le verrouillage du state Terraform"
  type        = string
  default     = "lafarge-truck-traffic-tfstate-lock"
}
