# DocuMind dev environment. All logic lives in modules/stack; this file only sets sizes.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66"
    }
  }
  backend "s3" {
    bucket       = "documind-tfstate-471112513968"
    key          = "envs/dev/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true # native S3 locking (Terraform >= 1.10): no DynamoDB lock table
    encrypt      = true
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      project    = "documind"
      env        = "dev"
      owner      = "bharath"
      managed_by = "terraform"
    }
  }
}

variable "package_dir" {
  type        = string
  description = "Folder with function.zip and layer-arm64.zip (backend/scripts/build_lambda.py)."
  default     = "../../../backend/dist"
}

variable "alert_email" {
  type    = string
  default = ""
}

module "stack" {
  source                = "../../modules/stack"
  env                   = "dev"
  function_package_path = "${var.package_dir}/function.zip"
  layer_package_path    = "${var.package_dir}/layer-arm64.zip"
  cors_origins          = ["http://localhost:3000"]

  # dev + prod must stay within DynamoDB's always-free 25 RCU / 25 WCU per region.
  dynamodb_read_capacity  = 5
  dynamodb_write_capacity = 5

  protect_data             = false # dev can be torn down and rebuilt freely
  allow_cli_password_login = true  # lets developers fetch a token from the terminal
  alarms_enabled           = false
  daily_token_quota        = 100000
  log_level                = "DEBUG"
  alert_email              = var.alert_email
}

output "api_url" {
  value = module.stack.api_url
}

output "cognito_user_pool_id" {
  value = module.stack.cognito_user_pool_id
}

output "cognito_app_client_id" {
  value = module.stack.cognito_app_client_id
}

output "openai_key_parameter" {
  value = module.stack.openai_key_parameter
}
