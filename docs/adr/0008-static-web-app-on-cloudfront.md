# 8. Web app: static Next.js export on S3 + CloudFront, configured at runtime

- **Status:** accepted (2026-09-25)

## Context
The site needs:
- a landing page;
- a chat app with streaming, file upload and Cognito sign-in;
- good Lighthouse scores;
- $0 hosting, one build for dev and prod, and no server to operate.

Amplify Hosting is free only while new-account credits last. Server-side rendering would need a compute tier.

## Decision
- **Build.** Next.js with `output: "export"`: plain HTML, CSS and JS. All data calls happen in the browser, straight to the API Function URL with the user's Cognito token.
- **Hosting.** A **private S3 bucket** that only the CloudFront distribution can read (origin access control). CloudFront adds:
  - HTTPS;
  - security headers (CSP, HSTS, `frame-ancestors 'none'`, nosniff);
  - a tiny CloudFront Function that maps `/route/` to `/route/index.html`.
- **Runtime config.** One build is promoted to every environment. Terraform writes each environment's **`/config.json`** (API URL, Cognito pool and client) next to it.
- **Auth.** Cognito **SRP** sign-in in the browser, so the password never leaves the browser. Amplify's auth library is loaded only when needed.
- **Streaming.** `fetch` plus a small parser for Server-Sent Events (SSE), since `EventSource` can't POST or send an `Authorization` header.

## Consequences
**Good:**
- **$0 hosting.** CloudFront's always-free allowance, and a few MB in S3.
- **Fast pages.** Lighthouse gives performance and accessibility **100** on desktop (mobile performance: 99 on the landing page, 90 for sign-in), and CI enforces 90+.
- **Safe config changes.** Changing the API URL or pool never needs a rebuild.

**Bad:**
- **The CSP allows `'unsafe-inline'` scripts.** A static export can't use per-request nonces, and Next.js inlines its hydration data. `connect-src` uses wildcards for Function URL and bucket hosts, to avoid a Terraform dependency cycle with the API's CORS setting.
- **No server-side rendering of user data.** Fine for an authenticated app.
- **No custom domain yet.** A `*.cloudfront.net` URL; a domain would need Route 53 and a certificate.

## Alternatives considered
| Option | Why not |
|---|---|
| Amplify Hosting | Free only while account credits last |
| Next.js server on Lambda (OpenNext) | More moving parts and cold starts for pages that don't need a server |
| Vercel | Another platform and account; the spec keeps everything in AWS via Terraform |
