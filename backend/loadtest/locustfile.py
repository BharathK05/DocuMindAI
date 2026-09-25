"""Load test for the DocuMind API (Locust).

Every simulated user asks questions about the same PDF, as one test account, with a short
think time between questions:
  * "POST /v1/query/stream" is the whole answer (Locust's usual response time);
  * "time to first token" is a separate row: when the first words would appear on screen.

Before the test starts, the account gets the sample PDF (uploaded once, then reused).

Local run (fake LLM, no OpenAI cost): see loadtest/README.md.
    locust -f loadtest/locustfile.py --host http://localhost:8000
AWS run: LOADTEST_TOKEN_FILE=~/.documind/dev-token (from scripts/cognito_user.py login).
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Any

import requests
from locust import HttpUser, between, events, task
from locust.env import Environment

BACKEND = Path(__file__).resolve().parents[1]
PDF = BACKEND / "evals" / "corpus" / "NIST.SP.800-63b.pdf"
QUESTIONS = [
    row["question"]
    for row in map(json.loads, (BACKEND / "evals" / "golden.jsonl").read_text().splitlines())
    if row["document"] == PDF.name
]


def _token() -> str:
    """A bearer token: from LOADTEST_TOKEN_FILE (AWS/Cognito) or minted locally."""
    if path := os.environ.get("LOADTEST_TOKEN_FILE"):
        return Path(path).expanduser().read_text().strip()
    from documind.core.auth import LocalAuthenticator  # local stack: sign our own dev token

    secret = os.environ["DOCUMIND_JWT_SECRET"]
    return LocalAuthenticator(secret).issue(os.environ.get("LOADTEST_USER", "loadtest"))


TOKEN = _token()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
document_ids: list[str] = []


def _ensure_document(host: str) -> str:
    """Reuse the sample PDF if the account already has it; otherwise upload and wait."""
    api = host.rstrip("/")
    listed = requests.get(f"{api}/v1/documents", headers=HEADERS, timeout=30)
    listed.raise_for_status()
    for doc in listed.json()["documents"]:
        if doc["filename"] == PDF.name and doc["status"] == "ready":
            return str(doc["document_id"])
    data = PDF.read_bytes()
    created = requests.post(
        f"{api}/v1/documents",
        json={"filename": PDF.name, "size_bytes": len(data)},
        headers=HEADERS,
        timeout=30,
    )
    created.raise_for_status()
    body = created.json()
    target = body["upload"]
    requests.post(
        target["url"],
        data=target["fields"],
        files={"file": (PDF.name, data, "application/pdf")},
        timeout=120,
    ).raise_for_status()
    doc_id = str(body["document"]["document_id"])
    requests.post(f"{api}/v1/documents/{doc_id}/complete", headers=HEADERS, timeout=30)
    for _ in range(120):
        status = requests.get(f"{api}/v1/documents/{doc_id}", headers=HEADERS, timeout=30).json()
        if status["status"] == "ready":
            return doc_id
        if status["status"] == "failed":
            raise RuntimeError(f"ingestion failed: {status['error']}")
        time.sleep(1)
    raise TimeoutError("the sample PDF didn't finish ingesting within 2 minutes")


@events.test_start.add_listener
def _setup(environment: Environment, **_: Any) -> None:
    document_ids.append(_ensure_document(environment.host or ""))


class Reader(HttpUser):
    # A person reads an answer before asking the next question.
    wait_time = between(
        float(os.environ.get("LOADTEST_WAIT_MIN", "2")),
        float(os.environ.get("LOADTEST_WAIT_MAX", "5")),
    )

    @task(8)
    def ask(self) -> None:
        started = time.perf_counter()
        first_token_ms: float | None = None
        with self.client.post(
            "/v1/query/stream",
            json={"question": random.choice(QUESTIONS), "document_ids": document_ids},
            headers=HEADERS,
            stream=True,
            catch_response=True,
            name="POST /v1/query/stream",
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}: {response.text[:200]}")
                return
            done = False
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("event: token") and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - started) * 1000
                elif line.startswith("event: error"):
                    response.failure("error event in the stream")
                    return
                elif line.startswith("event: done"):
                    done = True
            if not done:
                response.failure("stream ended without a done event")
                return
            response.success()
        if first_token_ms is not None:
            events.request.fire(
                request_type="SSE",
                name="time to first token",
                response_time=first_token_ms,
                response_length=0,
                exception=None,
                context={},
            )

    @task(1)
    def list_documents(self) -> None:
        self.client.get("/v1/documents", headers=HEADERS)

    @task(1)
    def usage(self) -> None:
        self.client.get("/v1/usage", headers=HEADERS)
