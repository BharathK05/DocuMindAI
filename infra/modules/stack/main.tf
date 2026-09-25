# One complete DocuMind environment (dev or prod). Environments differ only in variables.
#
#   client ─HTTPS─► Function URL ─► API Lambda (FastAPI behind the Lambda Web Adapter)
#                                     ├─► DynamoDB   (documents, chunks, conversations, usage)
#   client ─presigned POST─► S3       ├─► SQS ─► worker Lambda (PDF ingestion) ─► DLQ on failure
#                                     └─► Cognito JWKS (login tokens), SSM (OpenAI key)

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  prefix     = "documind-${var.env}"
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region

  # AWS-published Lambda Web Adapter layer: lets an ordinary ASGI app (FastAPI + uvicorn) run
  # on Lambda and enables response streaming through the Function URL.
  web_adapter_layer = "arn:aws:lambda:${local.region}:753240598075:layer:LambdaAdapterLayerArm64:${var.web_adapter_layer_version}"

  # The OpenAI key lives in an SSM SecureString that the operator creates by hand:
  #   aws ssm put-parameter --name /documind/<env>/openai-api-key --type SecureString ...
  # Terraform deliberately does NOT manage it: a managed parameter's value is read back into
  # the Terraform state (plain text) on every refresh, even with ignore_changes.
  openai_key_parameter     = "/documind/${var.env}/openai-api-key"
  openai_key_parameter_arn = "arn:aws:ssm:${local.region}:${local.account_id}:parameter${local.openai_key_parameter}"
  worker_timeout           = 300

  # Settings shared by both functions (read by documind.core.config.Settings).
  common_env = {
    DOCUMIND_ENV                          = var.env
    DOCUMIND_BACKEND                      = "aws"
    DOCUMIND_LOG_LEVEL                    = var.log_level
    DOCUMIND_DYNAMODB_TABLE               = module.dynamodb.name
    DOCUMIND_S3_BUCKET                    = module.uploads.name
    DOCUMIND_SQS_QUEUE_NAME               = module.queue.name
    DOCUMIND_SQS_MAX_RECEIVE_COUNT        = "3"
    DOCUMIND_OPENAI_API_KEY_SSM_PARAMETER = local.openai_key_parameter
    DOCUMIND_CORS_ORIGINS                 = jsonencode(var.cors_origins)
    DOCUMIND_DAILY_TOKEN_QUOTA            = tostring(var.daily_token_quota)
    TIKTOKEN_CACHE_DIR                    = "/opt/tiktoken_cache" # bundled in the layer
  }
}

module "dynamodb" {
  source              = "../dynamodb"
  name                = "${local.prefix}-data"
  read_capacity       = var.dynamodb_read_capacity
  write_capacity      = var.dynamodb_write_capacity
  deletion_protection = var.protect_data
}

module "uploads" {
  source        = "../s3_uploads"
  name          = "${local.prefix}-uploads-${local.account_id}" # bucket names are global
  cors_origins  = var.cors_origins
  force_destroy = !var.protect_data
}

module "queue" {
  source                     = "../sqs"
  name                       = "${local.prefix}-ingest"
  visibility_timeout_seconds = 6 * local.worker_timeout
  max_receive_count          = 3
}

module "cognito" {
  source              = "../cognito"
  name                = local.prefix
  allow_password_auth = var.allow_cli_password_login
  deletion_protection = var.protect_data
}

resource "aws_lambda_layer_version" "deps" {
  layer_name               = "${local.prefix}-deps"
  description              = "Python dependencies + tiktoken files for DocuMind"
  filename                 = var.layer_package_path
  source_code_hash         = filebase64sha256(var.layer_package_path)
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["arm64"]
}

# --- IAM: each function gets exactly what it uses ---------------------------------------------

data "aws_iam_policy_document" "api" {
  statement {
    sid = "Data"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
      "dynamodb:Query", "dynamodb:BatchWriteItem",
    ]
    resources = [module.dynamodb.arn]
  }
  statement {
    sid = "Uploads"
    # PutObject: presigned POSTs are signed with this role's credentials.
    # GetObject covers HEAD (size check before queueing). DeleteObject: user deletes.
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${module.uploads.arn}/uploads/*"]
  }
  statement {
    sid       = "Queue"
    actions   = ["sqs:SendMessage", "sqs:GetQueueUrl"]
    resources = [module.queue.arn]
  }
  statement {
    sid       = "OpenAIKey"
    actions   = ["ssm:GetParameter"]
    resources = [local.openai_key_parameter_arn]
  }
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid = "Data"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query",
      "dynamodb:BatchWriteItem",
    ]
    resources = [module.dynamodb.arn]
  }
  statement {
    sid       = "Uploads"
    actions   = ["s3:GetObject", "s3:DeleteObject"]
    resources = ["${module.uploads.arn}/uploads/*"]
  }
  statement {
    sid = "Queue"
    actions = [
      "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility", "sqs:GetQueueUrl",
    ]
    resources = [module.queue.arn]
  }
  statement {
    sid       = "OpenAIKey"
    actions   = ["ssm:GetParameter"]
    resources = [local.openai_key_parameter_arn]
  }
}

# --- Functions ---------------------------------------------------------------------------------

module "api" {
  source          = "../lambda"
  name            = "${local.prefix}-api"
  description     = "DocuMind HTTP API (FastAPI via Lambda Web Adapter, streaming)"
  handler         = "run.sh" # Web Adapter starts uvicorn from this script
  package_path    = var.function_package_path
  layer_arns      = [aws_lambda_layer_version.deps.arn, local.web_adapter_layer]
  memory_mb       = var.api_memory_mb
  timeout_seconds = 60
  policy_json     = data.aws_iam_policy_document.api.json
  environment = merge(local.common_env, {
    AWS_LAMBDA_EXEC_WRAPPER        = "/opt/bootstrap"
    AWS_LWA_INVOKE_MODE            = "response_stream"
    AWS_LWA_READINESS_CHECK_PATH   = "/health"
    PORT                           = "8080"
    PYTHONPATH                     = "/opt/python:/var/task"
    DOCUMIND_AUTH_MODE             = "cognito"
    DOCUMIND_COGNITO_USER_POOL_ID  = module.cognito.user_pool_id
    DOCUMIND_COGNITO_APP_CLIENT_ID = module.cognito.app_client_id
  })
}

module "worker" {
  source          = "../lambda"
  name            = "${local.prefix}-worker"
  description     = "DocuMind ingestion worker (SQS -> parse, chunk, embed, store)"
  handler         = "documind.lambda_worker.handler"
  package_path    = var.function_package_path
  layer_arns      = [aws_lambda_layer_version.deps.arn]
  memory_mb       = var.worker_memory_mb
  timeout_seconds = local.worker_timeout
  policy_json     = data.aws_iam_policy_document.worker.json
  environment     = local.common_env
}

resource "aws_lambda_event_source_mapping" "ingest" {
  event_source_arn        = module.queue.arn
  function_name           = module.worker.function_arn
  batch_size              = 1 # one PDF per invocation keeps memory and timeouts predictable
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    # Caps parallel ingestion (AWS minimum is 2). This, not reserved concurrency, is the cap:
    # the account's concurrency limit (10) is too low to reserve any.
    maximum_concurrency = 2
  }
}

# --- Public HTTPS endpoint ---------------------------------------------------------------------

resource "aws_lambda_function_url" "api" {
  function_name      = module.api.function_name
  authorization_type = "NONE" # the app verifies Cognito JWTs itself; /health is public
  invoke_mode        = "RESPONSE_STREAM"
}

# Since Oct 2025 a public Function URL needs both permissions below. The second is scoped with
# invoked_via_function_url, so it does NOT let anyone invoke the function any other way.
resource "aws_lambda_permission" "url_invoke_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = module.api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke_function" {
  statement_id             = "AllowInvokeViaFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = module.api.function_name
  principal                = "*"
  invoked_via_function_url = true
}

module "monitoring" {
  count             = var.alarms_enabled ? 1 : 0
  source            = "../monitoring"
  name              = local.prefix
  alert_email       = var.alert_email
  api_function_name = module.api.function_name
  dlq_name          = module.queue.dlq_name
}
