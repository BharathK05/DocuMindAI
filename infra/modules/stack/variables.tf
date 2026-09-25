variable "env" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}

variable "function_package_path" {
  type = string
}

variable "layer_package_path" {
  type = string
}

variable "web_adapter_layer_version" {
  type    = number
  default = 30
}

variable "cors_origins" {
  type = list(string)
}

variable "dynamodb_read_capacity" {
  type = number
}

variable "dynamodb_write_capacity" {
  type = number
}

variable "api_memory_mb" {
  type = number
  # Lambda's CPU share grows with memory (1,769 MB = one full vCPU), and a cold start is mostly
  # CPU-bound Python imports. 2,048 MB still leaves ~50k questions a month inside the free
  # 400k GB-seconds (at ~4 s per streamed answer).
  default = 2048
}

variable "worker_memory_mb" {
  type    = number
  default = 1024
}

variable "daily_token_quota" {
  type    = number
  default = 200000
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "protect_data" {
  type        = bool
  description = "Deletion protection on the table and user pool; keep S3 objects on destroy."
}

variable "allow_cli_password_login" {
  type        = bool
  default     = false
  description = "Allow USER_PASSWORD_AUTH so developers can get tokens from the CLI."
}

variable "alarms_enabled" {
  type    = bool
  default = false
}

variable "alert_email" {
  type    = string
  default = ""
}

variable "global_daily_token_quota" {
  type        = number
  default     = 0
  description = "Tokens per UTC day for all users together (0 = no cap). Bounds the OpenAI bill."
}

variable "metrics_enabled" {
  type        = bool
  default     = false
  description = "Custom CloudWatch metrics (5 per environment; 10 are free per account)."
}

variable "tracing_enabled" {
  type    = bool
  default = true
}

variable "daily_cost_alarm_usd" {
  type        = number
  default     = 0.5
  description = "Email when the day's OpenAI spend (from the CostUSD metric) passes this."
}
