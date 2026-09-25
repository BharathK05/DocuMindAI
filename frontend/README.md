# DocuMind AI web app

A Next.js static site: a landing page and a chat app for the DocuMind API.

- **Stack:** Next.js (static export), Tailwind CSS v4 and Motion.
- **Hosting:** S3 and CloudFront. There is no server to run.
- **Design tokens:** all colours, radii and type sizes live in [`src/app/globals.css`](src/app/globals.css), with light and dark mode.
- **Fonts:** served from the site itself (Fraunces for headlines and answers, Geist for everything else).

| Route | What it is |
|---|---|
| `/` | Landing page. The "proof" numbers come from the eval harness's results file via `scripts/sync-eval.mjs`. |
| `/login/` | Cognito sign-in, sign-up, email verification and password reset. Locally, you paste a dev token instead. |
| `/chat/?c=<id>` | The chat app: chats in the sidebar (named automatically after the first answer), PDFs attached in the composer, streamed answers with inline citations, and the context-window and daily-quota bars. |

## Configuration
The app reads `/config.json` at runtime, so the **same build** is deployed to dev and prod:
```json
{ "apiUrl": "https://…lambda-url…/", "auth": { "mode": "cognito", "userPoolId": "…", "clientId": "…" } }
```
- [`public/config.json`](public/config.json) is the local default: the API at `localhost:8000` with dev tokens.
- On AWS, Terraform writes each environment's `config.json` next to the site.

## Run locally
```bash
docker compose up --build            # from the repo root: API, worker, DynamoDB Local, moto
cd frontend && npm install && npm run dev   # http://localhost:3000
cd backend && python -m documind.scripts.dev_token --user alice   # paste at /login
```

## Checks
```bash
npm run lint && npm run typecheck && npm test && npm run build   # build output goes to out/
```

## Hosting on Vercel (free `*.vercel.app` address)
The same static build also runs on Vercel.
- **Setup:** import the GitHub repo in Vercel, set **Root Directory** to `frontend`, and add these environment variables:

  | Variable | Value (prod) |
  |---|---|
  | `DOCUMIND_API_URL` | `terraform -chdir=infra/envs/prod output -raw api_url` |
  | `DOCUMIND_COGNITO_USER_POOL_ID` | `terraform -chdir=infra/envs/prod output -raw cognito_user_pool_id` |
  | `DOCUMIND_COGNITO_CLIENT_ID` | `terraform -chdir=infra/envs/prod output -raw cognito_app_client_id` |

- **Build:** `scripts/write-config.mjs` turns them into `config.json`.
- **Headers:** `vercel.json` sends the same security headers as CloudFront.
- **CORS:** the Vercel address must be in prod's `cors_origins` ([infra/envs/prod/main.tf](../infra/envs/prod/main.tf)). Preview deployments get other addresses, so they can't call the API.
