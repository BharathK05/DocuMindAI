# The web app: a private S3 bucket holding the static Next.js export, served over HTTPS by
# CloudFront. CloudFront's always-free allowance (1 TB and 10M requests a month) covers this
# comfortably, and the bucket holds a few MB.
#
#   browser ─HTTPS─► CloudFront ─(origin access control, SigV4)─► S3 (private)
#
# CI uploads the site files (aws s3 sync) and invalidates the cache after `terraform apply`;
# Terraform owns only config.json, the per-environment settings the app reads at runtime.

data "aws_region" "current" {}

locals {
  region = data.aws_region.current.region

  # Content-Security-Policy. The browser may only connect to this environment's kinds of
  # endpoints. Wildcards for the Function URL and bucket hosts avoid a dependency cycle (the
  # API's CORS setting needs this distribution's domain first).
  # 'unsafe-inline' scripts: a static export can't use per-request nonces, and Next.js inlines
  # its hydration data. Everything else is locked down.
  csp = join("; ", [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    join(" ", [
      "connect-src 'self'",
      "https://*.lambda-url.${local.region}.on.aws",
      "https://cognito-idp.${local.region}.amazonaws.com",
      "https://*.s3.amazonaws.com",
      "https://*.s3.${local.region}.amazonaws.com",
    ]),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ])
}

# --- Bucket -------------------------------------------------------------------------------------

resource "aws_s3_bucket" "site" {
  bucket        = var.bucket_name
  force_destroy = true # only build output lives here; it's recreated on every deploy
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Only this distribution can read the bucket; the bucket itself stays private.
data "aws_iam_policy_document" "site" {
  statement {
    sid       = "CloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
  statement {
    sid     = "TLSOnly"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.site.arn,
      "${aws_s3_bucket.site.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  policy     = data.aws_iam_policy_document.site.json
  depends_on = [aws_s3_bucket_public_access_block.site]
}

# --- CloudFront ---------------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name}-web"
  description                       = "CloudFront signs its requests to the ${var.name} site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "rewrite" {
  name    = "${var.name}-web-rewrite"
  comment = "Map /route/ to /route/index.html for the static export"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = file("${path.module}/rewrite.js")
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "${var.name}-web-security"
  comment = "Security headers for the DocuMind web app"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
  }
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized" # honours the Cache-Control headers CI sets on each file
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "${var.name} web app"
  default_root_object = "index.html"
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  price_class         = "PriceClass_100" # North America and Europe edges: the cheapest class

  origin {
    origin_id                = "site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id           = "site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.rewrite.arn
    }
  }

  # Without s3:ListBucket, S3 answers a missing key with 403; show the site's 404 page instead.
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 60
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # *.cloudfront.net; a custom domain is optional later
  }

  lifecycle {
    # Subscribing the distribution to CloudFront's Free flat-rate plan (console, optional)
    # attaches a WAF web ACL that Terraform must not remove.
    ignore_changes = [web_acl_id]
  }
}

# --- Runtime configuration ----------------------------------------------------------------------

resource "aws_s3_object" "config" {
  bucket        = aws_s3_bucket.site.id
  key           = "config.json"
  content_type  = "application/json"
  cache_control = "no-cache" # always revalidated, so a new API URL takes effect immediately
  content = jsonencode({
    apiUrl = var.api_url
    auth = {
      mode        = "cognito"
      userPoolId  = var.cognito_user_pool_id
      clientId    = var.cognito_app_client_id
      allowSignUp = var.allow_sign_up
    }
  })
}
