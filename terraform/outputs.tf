output "alb_dns_name" {
  description = "Nom DNS public du Load Balancer, point d'entrée unique de l'application"
  value       = aws_lb.app.dns_name
}

output "alb_zone_id" {
  description = "Zone ID de l'ALB (utile pour créer un enregistrement Route53 de type alias)"
  value       = aws_lb.app.zone_id
}

output "vpc_id" {
  description = "Identifiant du VPC créé"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Identifiants des subnets publics"
  value       = aws_subnet.public[*].id
}

output "autoscaling_group_name" {
  description = "Nom de l'Auto Scaling Group, utilisé par Jenkins pour déclencher un instance refresh"
  value       = aws_autoscaling_group.app.name
}

output "ec2_security_group_id" {
  description = "ID du Security Group des instances applicatives"
  value       = aws_security_group.ec2_app.id
}
