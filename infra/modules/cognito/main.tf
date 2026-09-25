# User pool for sign-up/sign-in. Always free up to 10,000 monthly active users (Lite and
# Essentials tiers). The API only ever sees the resulting JWT access tokens, never passwords.

variable "name" {
  type = string
}

variable "allow_password_auth" {
  type        = bool
  default     = false
  description = "Enable USER_PASSWORD_AUTH (for CLI testing in dev). Browsers use SRP."
}

variable "verification_email_subject" {
  type        = string
  default     = "Your DocuMind AI verification code"
  description = "Subject of the email with the sign-up or password-reset code."
}

variable "verification_email_html" {
  type        = string
  default     = null
  description = "HTML body; must contain {####} (the code). Defaults to templates/verification-email.html."
}

variable "deletion_protection" {
  type    = bool
  default = true
}

locals {
  verification_email_html = coalesce(
    var.verification_email_html,
    file("${path.module}/templates/verification-email.html"),
  )
}

resource "aws_cognito_user_pool" "this" {
  name                     = var.name
  user_pool_tier           = "ESSENTIALS"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"
  deletion_protection      = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
    password_history_size            = 1 # AWS default on this tier: a reset can't reuse the current password
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Cognito's built-in sender is free (limited to ~50 emails/day), enough for this project.
  # It always sends from no-reply@verificationemail.com; a custom sender needs Amazon SES.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # One template serves sign-up codes, resent codes and password-reset codes, so the wording
  # has to fit all three (separate wording per case needs a "custom message" Lambda trigger).
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = var.verification_email_subject
    email_message        = local.verification_email_html
  }

  lifecycle {
    precondition {
      condition     = strcontains(local.verification_email_html, "{####}")
      error_message = "The verification email must contain the {####} placeholder for the code."
    }
  }
}

resource "aws_cognito_user_pool_client" "this" {
  name         = "${var.name}-web"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = false # public client (browser/CLI); a secret can't be kept there
  explicit_auth_flows = concat(
    ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    var.allow_password_auth ? ["ALLOW_USER_PASSWORD_AUTH"] : [],
  )
  prevent_user_existence_errors = "ENABLED" # don't reveal which emails have accounts
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "app_client_id" {
  value = aws_cognito_user_pool_client.this.id
}
