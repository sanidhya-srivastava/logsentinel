# =============================================================================
# LogSentinel — Terraform: Main AWS Infrastructure
# =============================================================================

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket         = "logsentinel-terraform-state"
    key            = "infra/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "logsentinel-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "LogSentinel"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# =============================================================================
# Data sources
# =============================================================================
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "amazon_linux_2" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

# =============================================================================
# VPC & Networking
# =============================================================================
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "logsentinel-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway     = true
  single_nat_gateway     = var.environment != "production"
  enable_dns_hostnames   = true
  enable_dns_support     = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }
}

# =============================================================================
# S3 Bucket — ML models and log archives
# =============================================================================
resource "aws_s3_bucket" "logsentinel_storage" {
  bucket        = "logsentinel-storage-${var.environment}-${random_id.suffix.hex}"
  force_destroy = var.environment != "production"
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_versioning" "logsentinel_storage" {
  bucket = aws_s3_bucket.logsentinel_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logsentinel_storage" {
  bucket = aws_s3_bucket.logsentinel_storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logsentinel_storage" {
  bucket                  = aws_s3_bucket.logsentinel_storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =============================================================================
# EKS Cluster
# =============================================================================
locals {
  cluster_name = "logsentinel-${var.environment}"
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = "1.29"

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnet_ids

  eks_managed_node_groups = {
    general = {
      min_size       = 2
      max_size       = 10
      desired_size   = 3
      instance_types = [var.node_instance_type]
      capacity_type  = "ON_DEMAND"
      disk_size      = 50

      labels = {
        role = "general"
      }
    }

    ml = {
      min_size       = 1
      max_size       = 4
      desired_size   = 1
      instance_types = [var.ml_node_instance_type]
      capacity_type  = "SPOT"
      disk_size      = 100

      labels = {
        role = "ml-workload"
      }

      taints = {
        ml = {
          key    = "workload"
          value  = "ml"
          effect = "NO_SCHEDULE"
        }
      }
    }
  }

  cluster_addons = {
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    vpc-cni                = { most_recent = true }
    aws-ebs-csi-driver     = { most_recent = true }
  }
}

# =============================================================================
# AWS Secrets Manager — sensitive config
# =============================================================================
resource "aws_secretsmanager_secret" "logsentinel_secrets" {
  name        = "logsentinel/${var.environment}/app-secrets"
  description = "LogSentinel application secrets"

  recovery_window_in_days = var.environment == "production" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "logsentinel_secrets" {
  secret_id = aws_secretsmanager_secret.logsentinel_secrets.id
  secret_string = jsonencode({
    POSTGRES_PASSWORD  = var.postgres_password
    SLACK_WEBHOOK_URL  = var.slack_webhook_url
    SMTP_USERNAME      = var.smtp_username
    SMTP_PASSWORD      = var.smtp_password
    SMTP_TO_EMAILS     = var.smtp_to_emails
  })
}

# =============================================================================
# IAM Role for service account (IRSA)
# =============================================================================
module "logsentinel_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.30"

  role_name = "logsentinel-${var.environment}-irsa"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["logsentinel:logsentinel-sa"]
    }
  }

  role_policy_arns = {
    s3_access           = aws_iam_policy.logsentinel_s3.arn
    secrets_manager     = aws_iam_policy.logsentinel_secrets_access.arn
  }
}

resource "aws_iam_policy" "logsentinel_s3" {
  name        = "logsentinel-${var.environment}-s3"
  description = "Allow LogSentinel pods to access S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.logsentinel_storage.arn,
          "${aws_s3_bucket.logsentinel_storage.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_policy" "logsentinel_secrets_access" {
  name        = "logsentinel-${var.environment}-secrets"
  description = "Allow LogSentinel pods to read AWS Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [aws_secretsmanager_secret.logsentinel_secrets.arn]
      }
    ]
  })
}

# =============================================================================
# ECR Repositories
# =============================================================================
resource "aws_ecr_repository" "services" {
  for_each = toset([
    "log-ingestion-api",
    "log-processor",
    "ml-engine",
    "alert-service",
    "dashboard-backend"
  ])

  name                 = "logsentinel/${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "services" {
  for_each   = aws_ecr_repository.services
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus     = "any"
        countType     = "imageCountMoreThan"
        countNumber   = 10
      }
      action = { type = "expire" }
    }]
  })
}
