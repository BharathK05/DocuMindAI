# Account-level resources, applied once by an administrator (not by CI):
#   * S3 bucket holding Terraform state for every environment (native S3 locking, no DynamoDB)
#   * GitHub Actions OIDC trust + two roles, so CI deploys with short-lived credentials and no
#     stored AWS keys: a read-only "plan" role for pull requests, a "deploy" role for main
#   * Budget alerts: $1 monthly cap and a zero-spend alert that fires on the first cent billed

terraform {
  required_version = ">= 1.10" # native S3 state locking (use_lockfile)
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66"
    }
  }
  # Backend: see backend.tf. The very first apply runs with local state because this stack
  # creates the state bucket; the state is then migrated into it (infra/README.md).
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      project    = "documind"
      env        = "account"
      owner      = var.owner
      managed_by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  state_bucket = "documind-tfstate-${local.account_id}"
  github_sub   = "repo:${var.github_repository}"
}

# --- Terraform state bucket ----------------------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled" # recover from a bad apply by restoring an older state version
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

data "aws_iam_policy_document" "state_tls_only" {
  statement {
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket     = aws_s3_bucket.state.id
  policy     = data.aws_iam_policy_document.state_tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.state]
}

# --- GitHub Actions OIDC -------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust_pull_requests" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_sub}:pull_request"]
    }
  }
}

# Only workflow jobs running in the named GitHub environments may deploy. "production" has a
# required reviewer, so prod changes need a human click even after merge.
data "aws_iam_policy_document" "trust_deployments" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${local.github_sub}:environment:dev",
        "${local.github_sub}:environment:production",
      ]
    }
  }
}

resource "aws_iam_role" "github_plan" {
  name                 = "documind-github-plan"
  assume_role_policy   = data.aws_iam_policy_document.trust_pull_requests.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "plan_extra" {
  statement {
    sid       = "StateLockFile"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/*.tflock"]
  }
  # ReadOnlyAccess would also let PR plans read user data and secrets. Nothing in a plan needs
  # that, so deny it explicitly.
  statement {
    sid    = "NoUserDataOrSecrets"
    effect = "Deny"
    actions = [
      "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:Scan",
      "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "NoUploadedDocuments"
    effect    = "Deny"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::documind-*-uploads-*/*"]
  }
}

resource "aws_iam_role_policy" "plan_extra" {
  name   = "state-lock-and-denies"
  role   = aws_iam_role.github_plan.id
  policy = data.aws_iam_policy_document.plan_extra.json
}

resource "aws_iam_role" "github_deploy" {
  name                 = "documind-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.trust_deployments.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "deploy" {
  name   = "manage-documind"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# --- Budgets (free: budgets without automated actions cost nothing) -------------------------------

resource "aws_budgets_budget" "monthly_cap" {
  name         = "documind-monthly-1usd"
  budget_type  = "COST"
  limit_amount = "1"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# Acts as the "free tier exceeded" alarm: emails as soon as any charge at all appears.
resource "aws_budgets_budget" "zero_spend" {
  name         = "documind-zero-spend"
  budget_type  = "COST"
  limit_amount = "0.01"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
