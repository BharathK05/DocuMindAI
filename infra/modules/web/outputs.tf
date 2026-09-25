output "url" {
  description = "The site's HTTPS origin (no trailing slash), for CORS and links."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "bucket" {
  value = aws_s3_bucket.site.bucket
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}
