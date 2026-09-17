# =============================================================================
# LogSentinel — Terraform Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (development, staging, production)"
  type        = string
  default     = "staging"
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be one of: development, staging, production"
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "node_instance_type" {
  description = "EC2 instance type for general EKS node group"
  type        = string
  default     = "t3.medium"
}

variable "ml_node_instance_type" {
  description = "EC2 instance type for ML EKS node group"
  type        = string
  default     = "m5.xlarge"
}

variable "postgres_password" {
  description = "PostgreSQL superuser password"
  type        = string
  sensitive   = true
}

variable "slack_webhook_url" {
  description = "Slack incoming webhook URL for anomaly alerts"
  type        = string
  sensitive   = true
  default     = ""
}

variable "smtp_username" {
  description = "SMTP authentication username (email address)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "smtp_password" {
  description = "SMTP authentication password / app password"
  type        = string
  sensitive   = true
  default     = ""
}

variable "smtp_to_emails" {
  description = "JSON-encoded list of email recipients"
  type        = string
  default     = "[]"
}
