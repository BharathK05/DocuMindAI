variable "name" {
  type        = string
  description = "Resource name prefix, e.g. documind-dev."
}

variable "bucket_name" {
  type = string
}

variable "api_url" {
  type        = string
  description = "The API's Function URL, written into the site's config.json."
}

variable "cognito_user_pool_id" {
  type = string
}

variable "cognito_app_client_id" {
  type = string
}

variable "allow_sign_up" {
  type    = bool
  default = true
}
