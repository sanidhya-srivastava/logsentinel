# =============================================================================
# LogSentinel — Terraform Outputs
# =============================================================================

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_certificate_authority" {
  description = "EKS cluster CA data"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "s3_bucket_name" {
  description = "S3 bucket for LogSentinel storage"
  value       = aws_s3_bucket.logsentinel_storage.bucket
}

output "ecr_repository_urls" {
  description = "ECR repository URLs for all services"
  value = {
    for k, v in aws_ecr_repository.services : k => v.repository_url
  }
}

output "secrets_manager_arn" {
  description = "ARN of the AWS Secrets Manager secret"
  value       = aws_secretsmanager_secret.logsentinel_secrets.arn
}

output "kubeconfig_command" {
  description = "Command to update kubeconfig for this cluster"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
