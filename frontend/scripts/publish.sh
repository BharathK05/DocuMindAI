#!/usr/bin/env bash
# Upload the static build (out/) to the site bucket and refresh CloudFront.
#   usage: scripts/publish.sh <bucket> <distribution-id>
# config.json is excluded: Terraform writes the environment's own copy.
set -euo pipefail
bucket="$1"
distribution="$2"
cd "$(dirname "$0")/.."

# Hashed JS/CSS/font files never change: cache them for a year.
aws s3 sync out/_next/static "s3://${bucket}/_next/static" \
  --cache-control "public, max-age=31536000, immutable" --only-show-errors

# Everything else (HTML, route data) is revalidated on every visit.
aws s3 sync out "s3://${bucket}" --delete \
  --exclude "_next/static/*" --exclude "config.json" \
  --cache-control "no-cache" --only-show-errors

aws cloudfront create-invalidation --distribution-id "$distribution" --paths "/*" \
  --query "Invalidation.Id" --output text
