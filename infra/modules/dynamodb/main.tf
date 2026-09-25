# Single-table store for documents, chunks+embeddings, conversations, usage and rate limits.
#
# PROVISIONED (not on-demand) on purpose: the always-free tier is 25 RCU + 25 WCU per region,
# shared by all tables. On-demand is never free. Capacity is fixed (no autoscaling), so a
# traffic spike gets throttled instead of billed.

variable "name" {
  type = string
}

variable "read_capacity" {
  type        = number
  description = "RCUs. Sum across all tables in the region must stay <= 25 to remain free."
}

variable "write_capacity" {
  type        = number
  description = "WCUs. Sum across all tables in the region must stay <= 25 to remain free."
}

variable "deletion_protection" {
  type    = bool
  default = true
}

resource "aws_dynamodb_table" "this" {
  name                        = var.name
  billing_mode                = "PROVISIONED"
  read_capacity               = var.read_capacity
  write_capacity              = var.write_capacity
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # Rate-limit windows, daily usage counters and abandoned uploads carry `expires_at`;
  # TTL deletes them in the background at no cost.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  # Encryption at rest uses the AWS-owned key (free). Point-in-time recovery is off: it is
  # billed per GB-month, and every item here can be rebuilt by re-uploading documents.
  point_in_time_recovery {
    enabled = false
  }
}

output "name" {
  value = aws_dynamodb_table.this.name
}

output "arn" {
  value = aws_dynamodb_table.this.arn
}
