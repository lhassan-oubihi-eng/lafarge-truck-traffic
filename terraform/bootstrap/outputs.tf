output "state_bucket_name" {
  description = "Nom du bucket S3 créé pour le state Terraform (à reporter dans terraform/main.tf, bloc backend)"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "dynamodb_table_name" {
  description = "Nom de la table DynamoDB créée pour le verrouillage du state (à reporter dans terraform/main.tf, bloc backend)"
  value       = aws_dynamodb_table.terraform_locks.name
}

output "aws_account_id" {
  description = "ID du compte AWS courant, utile pour vérifier/garantir l'unicité globale du nom du bucket S3"
  value       = data.aws_caller_identity.current.account_id
}
