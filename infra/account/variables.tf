variable "owner" {
  type    = string
  default = "bharath"
}

variable "github_repository" {
  type        = string
  description = "owner/name of the GitHub repo allowed to deploy via OIDC."
  default     = "BharathK05/DocuMindAI"
}

variable "alert_email" {
  type        = string
  description = "Receives budget alerts."
}
