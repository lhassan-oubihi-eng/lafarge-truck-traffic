terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Ce module bootstrap utilise volontairement un state LOCAL : il a pour
  # unique responsabilité de créer l'infrastructure qui hébergera le state
  # distant du projet principal (bucket S3 + table de verrouillage DynamoDB).
  # On ne peut pas utiliser un backend S3 pour créer... le backend S3.
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# --------------------------------------------------------------------------
# Bucket S3 : stockage du fichier terraform.tfstate
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "terraform_state" {
  bucket = var.state_bucket_name

  # Empêche une suppression accidentelle du bucket contenant le state
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name      = "${var.project_name}-terraform-state"
    Project   = var.project_name
    ManagedBy = "Terraform-Bootstrap"
  }
}

# Versioning obligatoire : permet de revenir à une version antérieure du
# state en cas de corruption ou d'apply erroné.
resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Chiffrement systématique du state au repos (le state peut contenir des
# données sensibles : IDs de ressources, parfois des secrets).
resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Bloque tout accès public sur le bucket de state (défense en profondeur)
resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Access logging for the bootstrap state bucket itself, required for audit and Sonar consistency checks.
resource "aws_s3_bucket_logging" "terraform_state_bootstrap" {
  bucket        = aws_s3_bucket.terraform_state.id
  target_bucket = aws_s3_bucket.terraform_state.id
  target_prefix = "bootstrap-access-logs/"
}

# Enforce HTTPS-only access to the bootstrap state bucket.
resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

resource "aws_s3_bucket" "terraform_state_logs" {
  bucket = "${var.project_name}-terraform-state-logs"

  tags = {
    Name      = "${var.project_name}-terraform-state-logs"
    Project   = var.project_name
    ManagedBy = "Terraform-Bootstrap"
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state_logs" {
  bucket = aws_s3_bucket.terraform_state_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "terraform_state_logs_policy" {
  bucket = aws_s3_bucket.terraform_state_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.terraform_state_logs.arn,
          "${aws_s3_bucket.terraform_state_logs.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_logging" "terraform_state_logs_logging" {
  bucket        = aws_s3_bucket.terraform_state_logs.id
  target_bucket = aws_s3_bucket.terraform_state_logs.id
  target_prefix = "logs-self-audit/"
}

resource "aws_s3_bucket_logging" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  target_bucket = aws_s3_bucket.terraform_state_logs.id
  target_prefix = "access-logs/"
}

# --------------------------------------------------------------------------
# Table DynamoDB : verrouillage du state (state locking) pour empêcher
# deux exécutions Terraform concurrentes (ex : deux builds Jenkins en
# parallèle) de corrompre le state.
# --------------------------------------------------------------------------
resource "aws_dynamodb_table" "terraform_locks" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name      = "${var.project_name}-terraform-locks"
    Project   = var.project_name
    ManagedBy = "Terraform-Bootstrap"
  }
}
