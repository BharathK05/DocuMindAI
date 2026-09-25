output "api_url" {
  value = aws_lambda_function_url.api.function_url
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "cognito_app_client_id" {
  value = module.cognito.app_client_id
}

output "openai_key_parameter" {
  value = local.openai_key_parameter
}

output "table_name" {
  value = module.dynamodb.name
}

output "uploads_bucket" {
  value = module.uploads.name
}

output "api_function_name" {
  value = module.api.function_name
}

output "worker_function_name" {
  value = module.worker.function_name
}

output "dashboard_url" {
  value = var.alarms_enabled ? module.monitoring[0].dashboard_url : null
}
