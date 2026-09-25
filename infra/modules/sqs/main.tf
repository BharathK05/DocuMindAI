# Ingestion job queue with a dead-letter queue. Always-free: 1M requests per month.

variable "name" {
  type = string
}

variable "visibility_timeout_seconds" {
  type        = number
  description = "AWS recommends at least 6x the consuming Lambda's timeout."
}

variable "max_receive_count" {
  type        = number
  default     = 3
  description = "Deliveries before a message moves to the DLQ. Must match the app's setting."
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-dlq"
  message_retention_seconds = 14 * 24 * 3600 # keep failed jobs 14 days for inspection
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "this" {
  name                       = var.name
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 4 * 24 * 3600
  receive_wait_time_seconds  = 20 # long polling: fewer (billable-at-scale) empty receives
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.this.arn]
  })
}

output "name" {
  value = aws_sqs_queue.this.name
}

output "arn" {
  value = aws_sqs_queue.this.arn
}

output "dlq_name" {
  value = aws_sqs_queue.dlq.name
}
