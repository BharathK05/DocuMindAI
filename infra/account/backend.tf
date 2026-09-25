# Added after the first apply (which created this bucket) and migrated with
# `terraform init -migrate-state`. From a fresh clone, a plain `terraform init` uses it.
terraform {
  backend "s3" {
    bucket       = "documind-tfstate-471112513968"
    key          = "account/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}
