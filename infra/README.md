# Infrastructure (Terraform, AWS free tier)

```
infra/
├── account/        once per AWS account: state bucket, GitHub OIDC roles, budget alerts
├── modules/
│   ├── stack/      one complete environment (wires the modules below together)
│   ├── dynamodb/   single table, PROVISIONED capacity (always-free), TTL
│   ├── s3_uploads/ private upload bucket: TLS-only, SSE-S3, 1-day expiry, CORS for POST
│   ├── sqs/        ingestion queue + dead-letter queue
│   ├── lambda/     function + least-privilege role + 7-day log group
│   ├── cognito/    user pool + public app client
│   ├── web/        web app: private S3 bucket + CloudFront (HTTPS, security headers, config.json)
│   └── monitoring/ dashboard + 6 CloudWatch alarms → SNS email (prod only)
└── envs/
    ├── dev/        small capacity, no deletion protection, CLI password login allowed
    └── prod/       deletion protection, alarms, deployed only after manual approval
```

## Cost guardrails
| Guardrail | Why |
|---|---|
| DynamoDB `PROVISIONED`: dev 5/5 + prod 15/15 RCU/WCU (≤ 25/25) | On-demand is never free; fixed capacity throttles instead of billing |
| No VPC, NAT gateway, load balancer, KMS CMK or Secrets Manager | Each of these costs money even when idle |
| Lambda arm64, SQS `maximum_concurrency = 2`, account concurrency limit of 10 | A spike or bug can't fan out |
| Logs retained 7 days | Stay within the 5 GB CloudWatch Logs free tier |
| `documind-monthly-1usd` and `documind-zero-spend` budgets | Email on the first cent billed |
| Web app on CloudFront `PriceClass_100`, a few MB in S3 | Within CloudFront's always-free 1 TB and 10M requests a month. Optionally switch the distribution to the **Free flat-rate plan** in the CloudFront console (no overage charges at all; Terraform ignores the web ACL it attaches) |
| OpenAI key in an SSM SecureString **not managed by Terraform** | A managed parameter's value would be copied into the state file |

## One-time bootstrap (administrator, from a laptop)
Use an IAM user or role with administrator rights; don't use root access keys.

```bash
# 1. Account stack. The first apply uses local state, because it creates the state bucket.
cd infra/account
cp terraform.tfvars.example terraform.tfvars      # set alert_email (file is gitignored)
terraform init && terraform apply

# 2. Move the account stack's state into the new bucket (backend.tf is committed).
terraform init -migrate-state

# 3. Put the OpenAI key into SSM for each environment. Terraform never sees it.
#    Only the shell reads the key (a hidden prompt, then an env var) so it doesn't land in
#    your shell history.
read -rs OPENAI_KEY
aws ssm put-parameter --name /documind/dev/openai-api-key --type SecureString \
    --value "$OPENAI_KEY" --overwrite
unset OPENAI_KEY

# 4. Build the Lambda packages, then deploy dev.
python backend/scripts/build_lambda.py --arch arm64
cd infra/envs/dev && terraform init && terraform plan && terraform apply
```

## Day-to-day
- **Pull request:** `.github/workflows/deploy.yml` posts a `terraform plan` for dev and prod as a PR comment, using a read-only OIDC role.
- **Merge to `main`:** dev is applied and smoke-tested, then prod waits for a reviewer to approve the `production` environment in GitHub. After each apply, the web app is synced to its bucket and CloudFront is invalidated (`frontend/scripts/publish.sh`).
- **Repository settings** (`Settings → Secrets and variables → Actions → Variables`):
  - `AWS_PLAN_ROLE_ARN`
  - `AWS_DEPLOY_ROLE_ARN`
  - secret `ALERT_EMAIL` (a secret, so it is masked in public workflow logs)

## Trying a deployed environment
```bash
python backend/scripts/cognito_user.py signup you@example.com     # dev only
python backend/scripts/cognito_user.py confirm you@example.com 123456
python backend/scripts/cognito_user.py login you@example.com
python backend/scripts/try_api.py some.pdf "Question?" --cognito dev \
    --api "$(terraform -chdir=infra/envs/dev output -raw api_url)"
```

## Tearing down
```bash
cd infra/envs/dev && terraform destroy     # prod: set protect_data = false and apply first
```
