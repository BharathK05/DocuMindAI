# One Lambda function with its own least-privilege role and a log group that expires logs
# after a few days (CloudWatch Logs' always-free tier is 5 GB).

variable "name" {
  type = string
}

variable "description" {
  type = string
}

variable "handler" {
  type = string
}

variable "package_path" {
  type        = string
  description = "Path to function.zip built by backend/scripts/build_lambda.py."
}

variable "layer_arns" {
  type = list(string)
}

variable "environment" {
  type    = map(string)
  default = {}
}

variable "memory_mb" {
  type = number
}

variable "timeout_seconds" {
  type = number
}

variable "policy_json" {
  type        = string
  description = "IAM policy with exactly the app permissions this function needs."
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "tracing_enabled" {
  type        = bool
  default     = true
  description = "X-Ray active tracing (free up to 100k traces a month; sampled at ~1/s + 5%)."
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Created before the function so Lambda doesn't auto-create one with infinite retention.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

# Lambda's own trace segments, plus the app's spans (documind.core.tracing). X-Ray's write
# APIs don't support resource-level permissions, hence "*".
data "aws_iam_policy_document" "tracing" {
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "tracing" {
  count  = var.tracing_enabled ? 1 : 0
  name   = "tracing"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.tracing.json
}

resource "aws_iam_role_policy" "app" {
  name   = "app"
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

resource "aws_lambda_function" "this" {
  function_name    = var.name
  description      = var.description
  role             = aws_iam_role.this.arn
  runtime          = "python3.13"
  architectures    = ["arm64"] # Graviton: ~20% cheaper per GB-second than x86 once past free
  handler          = var.handler
  filename         = var.package_path
  source_code_hash = filebase64sha256(var.package_path)
  layers           = var.layer_arns
  memory_size      = var.memory_mb
  timeout          = var.timeout_seconds

  environment {
    variables = var.environment
  }

  tracing_config {
    mode = var.tracing_enabled ? "Active" : "PassThrough"
  }

  logging_config {
    log_format = "Text" # the app already writes one JSON object per line
    log_group  = aws_cloudwatch_log_group.this.name
  }

  depends_on = [aws_iam_role_policy.logs, aws_iam_role_policy.app, aws_iam_role_policy.tracing]
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "function_arn" {
  value = aws_lambda_function.this.arn
}

output "role_name" {
  value = aws_iam_role.this.name
}
