"""HTTP-level tests: routing, status codes, error envelope and SSE framing."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from documind.api.app import create_app
from documind.core.auth import LocalAuthenticator
from documind.core.container import Container
from documind.repositories.memory import InlineJobQueue, InMemoryBlobStore
from tests.conftest import TEST_JWT_SECRET

AUTH = LocalAuthenticator(TEST_JWT_SECRET)


def bearer(user: str = "alice") -> dict[str, str]:
    return {"Authorization": f"Bearer {AUTH.issue(user)}"}


@pytest.fixture
async def anonymous(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container=container, authenticator=AUTH)
    # ASGITransport doesn't run lifespan events, so set what the lifespan would.
    app.state.container = container
    app.state.authenticator = AUTH
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def client(anonymous: httpx.AsyncClient) -> httpx.AsyncClient:
    anonymous.headers.update(bearer("alice"))
    return anonymous


async def upload(client: httpx.AsyncClient, container: Container, data: bytes) -> str:
    response = await client.post(
        "/v1/documents", json={"filename": "r.pdf", "size_bytes": len(data)}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["status"] == "awaiting_upload"
    assert body["upload"]["url"]
    assert isinstance(container.blobs, InMemoryBlobStore)
    container.blobs.objects[body["upload"]["fields"]["key"]] = data
    doc_id: str = body["document"]["document_id"]

    response = await client.post(f"/v1/documents/{doc_id}/complete")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "pending"
    assert isinstance(container.queue, InlineJobQueue)
    await container.queue.drain()
    return doc_id


def parse_sse(text: str) -> list[tuple[str, object]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.json() == {"status": "ok"}
    assert "x-request-id" in response.headers


async def test_document_lifecycle(
    client: httpx.AsyncClient, container: Container, sample_pdf: bytes
) -> None:
    doc_id = await upload(client, container, sample_pdf)

    response = await client.get(f"/v1/documents/{doc_id}")
    assert response.json()["status"] == "ready"
    assert "user_id" not in response.json()

    listed = (await client.get("/v1/documents")).json()["documents"]
    assert [d["document_id"] for d in listed] == [doc_id]

    assert (await client.delete(f"/v1/documents/{doc_id}")).status_code == 204
    assert (await client.get(f"/v1/documents/{doc_id}")).status_code == 404


async def test_query_returns_answer_citations_and_usage(
    client: httpx.AsyncClient, container: Container, sample_pdf: bytes
) -> None:
    await upload(client, container, sample_pdf)
    response = await client.post(
        "/v1/query",
        json={
            "question": "What was the revenue growth?",
            "history": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]
    assert body["citations"][0]["page"] == 1
    assert body["usage"]["input_tokens"] > 0


async def test_query_stream_sse(
    client: httpx.AsyncClient, container: Container, sample_pdf: bytes
) -> None:
    await upload(client, container, sample_pdf)
    response = await client.post("/v1/query/stream", json={"question": "How many employees?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "sources"
    assert names[-1] == "done"
    assert set(names[1:-1]) == {"token"}


async def test_errors_use_a_consistent_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/documents/" + "0" * 32)
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]

    response = await client.post("/v1/documents", json={"filename": "a.exe", "size_bytes": 5})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "invalid_input")

    response = await client.post("/v1/query", json={"question": ""})
    assert response.status_code == 422

    response = await client.post("/v1/query/stream", json={"question": "x" * 3000})
    assert response.status_code == 422  # validated before the stream starts


async def test_rejects_malformed_document_ids(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/documents/../../etc")
    assert response.status_code in (404, 422)
    response = await client.get("/v1/documents/not-a-valid-id")
    assert response.status_code == 422
