# Load tests (Locust)

`locustfile.py` simulates people using the app:
- each simulated user asks a question about NIST SP 800-63B, reads the streamed answer for 2–5 s, then asks again;
- now and then a user lists their documents or checks their usage.

Locust reports three things:
- **`POST /v1/query/stream`:** time until the response starts, i.e. the sources event after retrieval;
- **`time to first token`:** when the first words of the answer appear;
- **failures:** HTTP errors, and error events inside the stream.

## Local (recommended; costs nothing)
The override file switches the local stack to the fake LLM. The fake has OpenAI-like delays (0.5 s per call) and produces 1,536-dimension vectors. It also lifts the per-user limits, because every simulated user shares one account.

```bash
# from the repo root; LOADTEST_CACHE_CHUNKS=0 turns the chunk cache off for a baseline
docker compose -f docker-compose.yml -f backend/loadtest/compose.yml up -d --build
cd backend
pip install -e ".[loadtest]"
export $(grep ^DOCUMIND_JWT_SECRET= .env)   # PowerShell: see the note below
locust -f loadtest/locustfile.py --host http://localhost:8000 \
    --headless -u 20 -r 5 -t 2m --csv loadtest/results/local
```
Read units per question come from the API's `"chat turn"` log lines (`ReadUnits`, `cache_hits`):
```bash
docker compose logs api | grep '"chat turn"'
```
PowerShell users: set the secret with `$env:DOCUMIND_JWT_SECRET = (Select-String '^DOCUMIND_JWT_SECRET=(.*)' .env).Matches.Groups[1].Value`.

## AWS dev (small and capped)
Log in, which saves your token to `~/.documind/dev-token`, then run a few users for a couple of minutes:
```bash
python scripts/cognito_user.py login you@example.com
LOADTEST_TOKEN_FILE=~/.documind/dev-token locust -f loadtest/locustfile.py \
    --host "$(terraform -chdir=../infra/envs/dev output -raw api_url)" \
    --headless -u 2 -r 1 -t 3m --csv loadtest/results/aws-dev
```
**Limits that apply on AWS:**
- a single account can ask at most **20 questions a minute** (the rate limit);
- dev has a **daily cap of 300k tokens** for all users together.

So a 3-minute run with 2 users stays under about 60 questions, roughly $0.04 of OpenAI usage.
