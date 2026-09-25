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
