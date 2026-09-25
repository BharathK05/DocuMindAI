# 2. Serverless: Lambda + Function URLs + Lambda Web Adapter, not containers

- **Status:** accepted (2026-09-25)

## Context
The API is a normal FastAPI app that must **stream** answers (Server-Sent Events). The traffic is spiky and mostly idle, and the budget is $0.

Container platforms bill while idle, or need a load balancer that does:
- **ECS/Fargate:** billed per task-hour.
- **App Runner:** a per-instance minimum.
- **EKS:** a control-plane fee.
- **An ALB:** billed per hour.

API Gateway adds a per-request charge beyond its 12-month free tier, an extra hop, and a ~30 s default integration timeout, which is tight for long answers.

## Decision
- **Hosting.** The API and the ingestion worker run as **AWS Lambda** functions on arm64 (Graviton), from zip packages plus a dependency layer. There's no container registry, so there's no image-storage cost.
- **Endpoint.** The API is exposed with a **Lambda Function URL** in `RESPONSE_STREAM` mode. It's free, supports streaming, and has no extra gateway hop.
- **Adapter.** The **Lambda Web Adapter** layer runs the unmodified FastAPI app under uvicorn inside Lambda. The same code runs locally, in Docker and on Lambda.
- **Authentication.** It happens in the app: Cognito JWTs are verified against the user pool's public keys (JWKS). The Function URL itself is public. Since October 2025 that needs both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` with `invoked_via_function_url`.

## Consequences
**Good:**
- **Idle cost is zero,** and the free tier covers ~1M requests and 400k GB-seconds a month.
- **Scaling and patching are AWS's job.**
- **No framework lock-in.** The app doesn't know it's on Lambda; moving to a container is a Dockerfile away (one already exists for local use).

**Bad:**
- **Cold starts** of 1.9–3.2 s, measured. About 1 s is our imports; the rest is the platform. Details are in [performance.md](../performance.md).
- **Concurrency.** Each instance serves one request at a time, and the account's concurrency limit (10 on a new account) caps parallel answers.
- **No API Gateway extras.** No built-in throttling, WAF or usage plans. Rate limits and quotas are implemented in the app on DynamoDB (ADR 9).
- **Package size.** The dependency layer is 45.5 MB against Lambda's 50 MB direct-upload limit. Uploading via S3 would lift it to 250 MB unzipped.

## Alternatives considered
| Option | Why not (now) |
|---|---|
| ECS Fargate + ALB | ~$20–30/month minimum even when idle |
| App Runner | Per-instance minimum; less control |
| API Gateway + Lambda | Per-request cost after the free tier; ~30 s default timeout; nothing needed that the app doesn't already do (auth, rate limits) |
| Mangum instead of the Web Adapter | Buffers the whole response, so no token-by-token streaming |

## Revisit when
- Steady traffic keeps several instances busy all day. Containers become cheaper per request, and cold starts stop being amortised.
- Cold starts become a user-visible problem. Options: a keep-warm ping (free), SnapStart or provisioned concurrency (paid).
