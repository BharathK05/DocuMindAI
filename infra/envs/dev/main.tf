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
  cors_origins          = [module.web.url, "http://localhost:3000"] # local frontend too

  # dev + prod must stay within DynamoDB's always-free 25 RCU / 25 WCU per region.
  dynamodb_read_capacity  = 5
  dynamodb_write_capacity = 5

  protect_data             = false # dev can be torn down and rebuilt freely
  allow_cli_password_login = true  # lets developers fetch a token from the terminal
  alarms_enabled           = false
  daily_token_quota        = 100000
  global_daily_token_quota = 300000 # all dev users together: ~60 questions (~$0.04) a day
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

# The web app (S3 + CloudFront). Its URL is the API's allowed CORS origin, and its config.json
# points the app at this environment's API and Cognito pool.
module "web" {
  source                = "../../modules/web"
  name                  = "documind-dev"
  bucket_name           = "documind-dev-web-${data.aws_caller_identity.current.account_id}"
  api_url               = module.stack.api_url
  cognito_user_pool_id  = module.stack.cognito_user_pool_id
  cognito_app_client_id = module.stack.cognito_app_client_id
}

data "aws_caller_identity" "current" {}

output "web_url" {
  value = module.web.url
}

output "web_bucket" {
  value = module.web.bucket
}

output "web_distribution_id" {
  value = module.web.distribution_id
}
