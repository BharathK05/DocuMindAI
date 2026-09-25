# Least-privilege permissions for the CI deploy role: it can manage only resources named
# documind-* (plus the state bucket), not the rest of the account.
#
# Two unavoidable exceptions, both documented: Cognito user pool ARNs contain random IDs (can't
# be name-scoped, so pools are limited to this account and region), and a few list/describe
# APIs only accept "*".

data "aws_region" "current" {}

locals {
  region = data.aws_region.current.region
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid     = "TerraformState"
    actions = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/envs/*",
    ]
  }

  statement {
    sid       = "UploadBuckets"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::documind-*-uploads-*", "arn:aws:s3:::documind-*-uploads-*/*"]
  }

  statement {
    sid       = "WebBuckets" # static site: Terraform manages the bucket, CI syncs the files
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::documind-*-web-*", "arn:aws:s3:::documind-*-web-*/*"]
  }

  # CloudFront distribution, origin-access-control and policy ARNs contain random IDs, so (as
  # with Cognito) these are limited to this account rather than to documind-* names. Only the
  # actions the web module and the cache invalidation use are allowed.
  statement {
    sid = "CloudFront"
    actions = [
      "cloudfront:CreateDistribution", "cloudfront:CreateDistributionWithTags",
      "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig",
      "cloudfront:UpdateDistribution", "cloudfront:DeleteDistribution",
      "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:ListTagsForResource",
      "cloudfront:CreateOriginAccessControl", "cloudfront:GetOriginAccessControl",
      "cloudfront:GetOriginAccessControlConfig", "cloudfront:UpdateOriginAccessControl",
      "cloudfront:DeleteOriginAccessControl", "cloudfront:ListOriginAccessControls",
      "cloudfront:CreateResponseHeadersPolicy", "cloudfront:GetResponseHeadersPolicy",
      "cloudfront:GetResponseHeadersPolicyConfig", "cloudfront:UpdateResponseHeadersPolicy",
      "cloudfront:DeleteResponseHeadersPolicy", "cloudfront:ListResponseHeadersPolicies",
      "cloudfront:GetCachePolicy", "cloudfront:ListCachePolicies",
      "cloudfront:CreateInvalidation", "cloudfront:GetInvalidation",
    ]
    resources = [
      "arn:aws:cloudfront::${local.account_id}:distribution/*",
      "arn:aws:cloudfront::${local.account_id}:origin-access-control/*",
      "arn:aws:cloudfront::${local.account_id}:response-headers-policy/*",
      "arn:aws:cloudfront::${local.account_id}:cache-policy/*",
    ]
  }

  statement {
    sid = "CloudFrontFunctions"
    actions = [
      "cloudfront:CreateFunction", "cloudfront:DescribeFunction", "cloudfront:GetFunction",
      "cloudfront:UpdateFunction", "cloudfront:PublishFunction", "cloudfront:DeleteFunction",
      # the provider's default_tags are applied to functions too
      "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:ListTagsForResource",
    ]
    resources = ["arn:aws:cloudfront::${local.account_id}:function/documind-*"]
  }

  statement {
    sid       = "CloudFrontList" # list APIs only accept "*"
    actions   = ["cloudfront:ListDistributions", "cloudfront:ListFunctions"]
    resources = ["*"]
  }

  statement {
    sid       = "DynamoDB"
    actions   = ["dynamodb:*"]
    resources = ["arn:aws:dynamodb:${local.region}:${local.account_id}:table/documind-*"]
  }

  statement {
    sid       = "SQS"
    actions   = ["sqs:*"]
    resources = ["arn:aws:sqs:${local.region}:${local.account_id}:documind-*"]
  }

  statement {
    sid     = "LambdaFunctionsAndLayers"
    actions = ["lambda:*"]
    resources = [
      "arn:aws:lambda:${local.region}:${local.account_id}:function:documind-*",
      "arn:aws:lambda:${local.region}:${local.account_id}:layer:documind-*",
      "arn:aws:lambda:${local.region}:${local.account_id}:layer:documind-*:*",
    ]
  }

  statement {
    sid       = "PublicWebAdapterLayer"
    actions   = ["lambda:GetLayerVersion"]
    resources = ["arn:aws:lambda:${local.region}:753240598075:layer:LambdaAdapterLayerArm64:*"]
  }

  statement {
    sid = "EventSourceMappings" # these APIs don't support resource-level scoping
    actions = [
      "lambda:CreateEventSourceMapping", "lambda:GetEventSourceMapping",
      "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping",
      "lambda:ListEventSourceMappings", "lambda:TagResource", "lambda:ListTags",
    ]
    resources = ["*"]
  }

  statement {
    sid = "FunctionRoles"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
      "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/documind-*-role"]
  }

  statement {
    sid       = "PassRolesToLambdaOnly"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/documind-*-role"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:*"]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/documind-*"]
  }

  statement {
    sid       = "LogsDescribe"
    actions   = ["logs:DescribeLogGroups", "logs:ListTagsForResource"]
    resources = ["*"]
  }

  statement {
    sid       = "Cognito"
    actions   = ["cognito-idp:*"]
    resources = ["arn:aws:cognito-idp:${local.region}:${local.account_id}:userpool/*"]
  }

  statement {
    sid       = "CognitoCreate" # CreateUserPool happens before a pool ARN exists
    actions   = ["cognito-idp:CreateUserPool", "cognito-idp:ListUserPools"]
    resources = ["*"]
  }

  statement {
    sid       = "AlarmsTopic"
    actions   = ["sns:*"]
    resources = ["arn:aws:sns:${local.region}:${local.account_id}:documind-*"]
  }

  statement {
    sid       = "Alarms"
    actions   = ["cloudwatch:*Alarm*", "cloudwatch:TagResource", "cloudwatch:ListTagsForResource"]
    resources = ["arn:aws:cloudwatch:${local.region}:${local.account_id}:alarm:documind-*"]
  }

  statement {
    sid       = "Identity"
    actions   = ["sts:GetCallerIdentity", "cloudwatch:DescribeAlarms"]
    resources = ["*"]
  }
}
