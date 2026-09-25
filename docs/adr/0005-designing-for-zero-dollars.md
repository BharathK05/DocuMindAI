# 5. Designing for a $0 AWS bill

- **Status:** accepted (2026-09-24)

## Context
The project must run on AWS for $0 a month and stay safe from surprise bills, including from bugs, traffic spikes or abuse. OpenAI is billed separately and must be bounded too. AWS's free tier changed in July 2025: new accounts get credits for 6–12 months. So only the **always-free** allowances are relied on.

## Decision
**Use only always-free services, sized inside their allowances:**

| Service | How it's sized |
|---|---|
| Lambda | 1M requests and 400k GB-seconds a month |
| DynamoDB | **provisioned** capacity: dev 5/5 + prod 15/15 of the free 25 RCU/25 WCU. On-demand is never free, and provisioned throttles instead of billing |
| SQS | 1M requests a month |
| Cognito | 10k monthly active users |
| CloudFront | 1 TB and 10M requests a month |
| CloudWatch | 10 alarms, 3 dashboards, 10 custom metrics, 5 GB of logs (kept 7 days) |
| X-Ray | 100k traces a month |
| SSM | Parameter Store standard parameters |

**Never create anything that bills while idle:**
- no NAT gateways, load balancers or RDS/Aurora;
- no OpenSearch, ElastiCache or Fargate;
- no Secrets Manager (SSM SecureString instead);
- no KMS customer-managed keys (SSE-S3 and AWS-owned keys instead);
- no VPC. Lambda runs outside a VPC, so no NAT is needed.

**Bounded fan-out:**
- SQS `maximum_concurrency = 2`;
- the account concurrency limit (10);
- `batch_size = 1`.

**Storage near zero:**
- PDFs are deleted after indexing;
- an S3 lifecycle rule expires leftovers after 1 day;
- DynamoDB TTL removes abandoned uploads and old counters.

**Budgets:**
- a $1 monthly budget and a zero-spend budget email on the first cent;
- CloudWatch alarms cover errors, throttles, dead letters and slow answers.

**OpenAI spend is bounded in the app:**
- per-user rate limits (20 questions a minute) and daily token quotas (200k);
- a **service-wide daily cap** (prod 1M tokens, about 200 questions or about $0.12);
- a daily-cost alarm at $0.50;
- `max_completion_tokens` on every call;
- a 3,000-token context budget.

## Consequences
**Good:**
- **The worst case is small and known.** A spike gets throttled or capped, not billed.
- **Every cost-relevant limit is a Terraform variable or a setting.**

**Bad:**
- **Throughput is capped by design.** Provisioned DynamoDB capacity throttles. The service-wide cap turns requests away when reached; that's intended.
- **Some good defaults are off-limits:**
  - a WAF;
  - customer-managed KMS keys;
  - provisioned concurrency for cold starts;
  - multi-region.

## Revisit when
The project has real users or revenue. [scaling.md](../scaling.md) lists what to pay for first.
