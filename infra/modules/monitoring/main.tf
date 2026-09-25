# A dashboard and a few high-signal alarms, emailed via SNS. CloudWatch's always-free tier is
# 3 dashboards and 10 alarms per account; this module uses 1 and 6.

variable "name" {
  type = string
}

variable "alert_email" {
  type = string
}

variable "api_function_name" {
  type = string
}

variable "dlq_name" {
  type = string
}

variable "env" {
  type = string
}

variable "worker_function_name" {
  type = string
}

variable "table_name" {
  type = string
}

variable "queue_name" {
  type = string
}

variable "daily_cost_alarm_usd" {
  type = number
}

data "aws_region" "current" {}

locals {
  region = data.aws_region.current.region
  # The app's own metrics (documind.core.metrics), all with the single dimension Env.
  app = { namespace = "DocuMind", dims = ["Env", var.env] }
}

resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

# AWS emails a confirmation link; alarms are delivered only after it is clicked.
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name}-ingestion-dlq-not-empty"
  alarm_description   = "A document failed ingestion after all retries (see the worker logs)."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${var.name}-api-errors"
  alarm_description   = "The API function is crashing or timing out."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = var.api_function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_throttles" {
  alarm_name          = "${var.name}-api-throttles"
  alarm_description   = "Requests are being throttled (account concurrency limit reached)."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = var.api_function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# --- Alarms on the app's own metrics and on DynamoDB -------------------------------------------

resource "aws_cloudwatch_metric_alarm" "slow_first_token" {
  alarm_name          = "${var.name}-slow-first-token"
  alarm_description   = "p95 time to the first words of an answer is over 8 s for 15 minutes."
  namespace           = "DocuMind"
  metric_name         = "TimeToFirstTokenMs"
  dimensions          = { Env = var.env }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  threshold           = 8000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "dynamodb_read_throttles" {
  alarm_name          = "${var.name}-dynamodb-read-throttles"
  alarm_description   = "Reads exceed the table's provisioned (free-tier) capacity."
  namespace           = "AWS/DynamoDB"
  metric_name         = "ReadThrottleEvents"
  dimensions          = { TableName = var.table_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "daily_openai_cost" {
  alarm_name          = "${var.name}-daily-openai-cost"
  alarm_description   = "Today's OpenAI spend passed USD ${var.daily_cost_alarm_usd} (OpenAI bills this, not AWS)."
  namespace           = "DocuMind"
  metric_name         = "CostUSD"
  dimensions          = { Env = var.env }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.daily_cost_alarm_usd
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# --- Dashboard ------------------------------------------------------------------------------------

locals {
  widgets = [
    {
      title = "Questions per 5 minutes"
      stat  = "SampleCount"
      metrics = [
        [local.app.namespace, "LatencyMs", local.app.dims[0], local.app.dims[1], { label = "questions" }],
      ]
    },
    {
      title = "Time to first token (ms)"
      metrics = [
        [local.app.namespace, "TimeToFirstTokenMs", local.app.dims[0], local.app.dims[1], { stat = "p50", label = "p50" }],
        ["...", { stat = "p95", label = "p95" }],
      ]
    },
    {
      title = "Full answer time (ms)"
      metrics = [
        [local.app.namespace, "LatencyMs", local.app.dims[0], local.app.dims[1], { stat = "p50", label = "p50" }],
        ["...", { stat = "p95", label = "p95" }],
      ]
    },
    {
      title = "OpenAI cost (USD per 5 minutes)"
      stat  = "Sum"
      metrics = [
        [local.app.namespace, "CostUSD", local.app.dims[0], local.app.dims[1], { label = "cost" }],
      ]
    },
    {
      title = "DynamoDB read units per question (cache effect)"
      metrics = [
        [local.app.namespace, "ReadUnits", local.app.dims[0], local.app.dims[1], { stat = "Average", label = "average" }],
        ["...", { stat = "Maximum", label = "max (cache miss)" }],
      ]
    },
    {
      title = "DynamoDB capacity used vs provisioned (units/s)"
      metrics = [
        [{ expression = "consumed_r / PERIOD(consumed_r)", label = "reads used", id = "reads" }],
        ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", var.table_name, { stat = "Sum", id = "consumed_r", visible = false }],
        [".", "ProvisionedReadCapacityUnits", ".", ".", { stat = "Average", label = "reads provisioned" }],
        [".", "ReadThrottleEvents", ".", ".", { stat = "Sum", label = "read throttles" }],
      ]
    },
    {
      title = "Lambda duration p95 (ms)"
      metrics = [
        ["AWS/Lambda", "Duration", "FunctionName", var.api_function_name, { stat = "p95", label = "api" }],
        ["...", var.worker_function_name, { stat = "p95", label = "worker" }],
      ]
    },
    {
      title = "Lambda invocations, errors, throttles"
      stat  = "Sum"
      metrics = [
        ["AWS/Lambda", "Invocations", "FunctionName", var.api_function_name, { label = "api invocations" }],
        [".", "Errors", ".", ".", { label = "api errors" }],
        [".", "Throttles", ".", ".", { label = "api throttles" }],
        [".", "Errors", ".", var.worker_function_name, { label = "worker errors" }],
      ]
    },
    {
      title = "Ingestion: queue, dead letters, seconds per PDF"
      metrics = [
        ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.queue_name, { stat = "Maximum", label = "waiting" }],
        ["...", var.dlq_name, { stat = "Maximum", label = "dead letters" }],
        [local.app.namespace, "IngestSeconds", local.app.dims[0], local.app.dims[1], { stat = "p95", label = "p95 seconds per PDF", yAxis = "right" }],
      ]
    },
  ]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.name
  dashboard_body = jsonencode({
    widgets = [
      for i, w in local.widgets : {
        type   = "metric"
        x      = (i % 3) * 8
        y      = floor(i / 3) * 6
        width  = 8
        height = 6
        properties = merge(
          {
            title   = w.title
            region  = local.region
            view    = "timeSeries"
            period  = 300
            metrics = w.metrics
          },
          lookup(w, "stat", null) == null ? {} : { stat = w.stat },
        )
      }
    ]
  })
}

output "dashboard_url" {
  value = "https://${local.region}.console.aws.amazon.com/cloudwatch/home?region=${local.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.main.dashboard_name}"
}
