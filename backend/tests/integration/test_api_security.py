"""Auth, tenant isolation, rate limits, quotas, conversations and the usage figures over HTTP."""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

from documind.api.app import create_app
from documind.core.auth import LocalAuthenticator
from documind.core.config import Settings
from documind.core.container import Container, build_container
from documind.repositories.memory import InlineJobQueue, InMemoryBlobStore
from tests.conftest import TEST_JWT_SECRET

AUTH = LocalAuthenticator(TEST_JWT_SECRET)


def bearer(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {AUTH.issue(user)}"}


@asynccontextmanager
async def api(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container=container, authenticator=AUTH)
    app.state.container, app.state.authenticator = container, AUTH
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def upload(client: httpx.AsyncClient, c: Container, data: bytes, user: str) -> str:
    r = await client.post(
        "/v1/documents", json={"filename": "r.pdf", "size_bytes": len(data)}, headers=bearer(user)
    )
    assert r.status_code == 201, r.text
    assert isinstance(c.blobs, InMemoryBlobStore) and isinstance(c.queue, InlineJobQueue)
    c.blobs.objects[r.json()["upload"]["fields"]["key"]] = data
    doc_id: str = r.json()["document"]["document_id"]
    assert (await client.post(f"/v1/documents/{doc_id}/complete", headers=bearer(user))).is_success
    await c.queue.drain()
    return doc_id


def configured(settings: Settings, **overrides: Any) -> Container:
    return build_container(settings.model_copy(update=overrides))


class TestAuthentication:
    async def test_requests_without_a_valid_token_are_rejected(self, container: Container) -> None:
        async with api(container) as client:
            for headers in ({}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic x"}):
                r = await client.get("/v1/documents", headers=headers)
                assert r.status_code == 401
                assert r.json()["error"]["code"] == "unauthorized"
                assert r.headers["www-authenticate"] == "Bearer"
            assert (await client.get("/health")).status_code == 200  # health stays public

    async def test_users_are_isolated(self, container: Container, sample_pdf: bytes) -> None:
        async with api(container) as client:
            doc_id = await upload(client, container, sample_pdf, "alice")
            bob = bearer("bob")
            assert (await client.get("/v1/documents", headers=bob)).json()["documents"] == []
            assert (await client.get(f"/v1/documents/{doc_id}", headers=bob)).status_code == 404
            assert (await client.delete(f"/v1/documents/{doc_id}", headers=bob)).status_code == 404
            r = await client.post("/v1/query", json={"question": "Where is HQ?"}, headers=bob)
            assert r.json()["citations"] == []  # bob's search sees none of alice's chunks
            conv = (await client.post("/v1/conversations", json={}, headers=bearer("alice"))).json()
            path = f"/v1/conversations/{conv['conversation_id']}"
            assert (await client.get(path, headers=bob)).status_code == 404


class TestLimits:
    async def test_queries_are_rate_limited(self, settings: Settings) -> None:
        async with api(configured(settings, rate_limit_queries_per_minute=2)) as client:
            ask: Callable[[], Any] = lambda: client.post(  # noqa: E731
                "/v1/query", json={"question": "hi"}, headers=bearer("alice")
            )
            assert (await ask()).status_code == 200
            assert (await ask()).status_code == 200
            r = await ask()
            assert r.status_code == 429
            assert r.json()["error"]["code"] == "rate_limited"
            assert int(r.headers["retry-after"]) >= 1

    async def test_daily_quota_blocks_further_questions(
        self, settings: Settings, sample_pdf: bytes
    ) -> None:
        c = configured(settings, daily_token_quota=50)
        async with api(c) as client:
            await upload(client, c, sample_pdf, "alice")
            first = await client.post(
                "/v1/query", json={"question": "Where is HQ?"}, headers=bearer("alice")
            )
            assert first.status_code == 200
            assert first.json()["account"]["remaining"] == 0
            second = await client.post(
                "/v1/query", json={"question": "Where is HQ?"}, headers=bearer("alice")
            )
            assert second.status_code == 429
            assert second.json()["error"]["code"] == "quota_exceeded"
            assert "resets at" in second.json()["error"]["message"]
            usage = (await client.get("/v1/usage", headers=bearer("alice"))).json()
            assert usage["account"]["tokens_used_today"] >= 50


class TestConversations:
    async def test_history_is_stored_and_context_grows(
        self, container: Container, sample_pdf: bytes
    ) -> None:
        alice = bearer("alice")
        async with api(container) as client:
            await upload(client, container, sample_pdf, "alice")
            conv = await client.post("/v1/conversations", json={"title": "HQ"}, headers=alice)
            assert conv.status_code == 201
            cid = conv.json()["conversation_id"]

            first = await client.post(
                "/v1/query",
                json={"question": "Where is HQ?", "conversation_id": cid},
                headers=alice,
            )
            second = await client.post(
                "/v1/query",
                json={"question": "And how many employees?", "conversation_id": cid},
                headers=alice,
            )
            assert first.status_code == second.status_code == 200
            body = second.json()
            assert body["conversation_id"] == cid
            assert body["context"]["tokens"] > first.json()["context"]["tokens"]  # history added
            assert body["context"]["limit"] == container.settings.context_limit
            assert 0 < body["context"]["fraction"] < 1

            detail = (await client.get(f"/v1/conversations/{cid}", headers=alice)).json()
            assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
            assert detail["messages"][1]["citations"]  # answers keep their sources
            assert detail["conversation"]["message_count"] == 4

            usage = (await client.get(f"/v1/usage?conversation_id={cid}", headers=alice)).json()
            assert usage["context"]["tokens"] > 0
            assert usage["account"]["tokens_used_today"] > 0

            listed = (await client.get("/v1/conversations", headers=alice)).json()
            assert [x["conversation_id"] for x in listed["conversations"]] == [cid]
            assert (
                await client.delete(f"/v1/conversations/{cid}", headers=alice)
            ).status_code == 204
            assert (await client.get(f"/v1/conversations/{cid}", headers=alice)).status_code == 404

    async def test_stream_reports_usage_and_saves_the_turn(
        self, container: Container, sample_pdf: bytes
    ) -> None:
        alice = bearer("alice")
        async with api(container) as client:
            await upload(client, container, sample_pdf, "alice")
            cid = (await client.post("/v1/conversations", json={}, headers=alice)).json()[
                "conversation_id"
            ]
            r = await client.post(
                "/v1/query/stream",
                json={"question": "How many employees?", "conversation_id": cid},
                headers=alice,
            )
            done = [b for b in r.text.strip().split("\n\n") if b.startswith("event: done")]
            payload = json.loads(done[0].split("data: ", 1)[1])
            assert set(payload) == {"usage", "context", "account"}
            assert payload["account"]["tokens_used_today"] > 0
            detail = (await client.get(f"/v1/conversations/{cid}", headers=alice)).json()
            assert detail["conversation"]["message_count"] == 2

    async def test_first_answer_names_the_conversation(
        self, container: Container, sample_pdf: bytes
    ) -> None:
        alice = bearer("alice")
        async with api(container) as client:
            await upload(client, container, sample_pdf, "alice")
            cid = (await client.post("/v1/conversations", json={}, headers=alice)).json()[
                "conversation_id"
            ]
            question = {"question": "How many employees work there?", "conversation_id": cid}
            r = await client.post("/v1/query/stream", json=question, headers=alice)
            events = [b.split("\n")[0] for b in r.text.strip().split("\n\n")]
            assert events[-2:] == ["event: done", "event: title"]  # title after done
            title = json.loads(r.text.strip().split("\n\n")[-1].split("data: ", 1)[1])["title"]
            assert title == "How Many Employees Work There?"

            listed = (await client.get("/v1/conversations", headers=alice)).json()
            assert listed["conversations"][0]["title"] == title
            again = await client.post("/v1/query/stream", json=question, headers=alice)
            assert "event: title" not in again.text  # named once only

            renamed = await client.patch(
                f"/v1/conversations/{cid}", json={"title": "  Staff   count "}, headers=alice
            )
            assert renamed.json()["title"] == "Staff count"
            assert (
                await client.patch(f"/v1/conversations/{cid}", json={"title": " "}, headers=alice)
            ).status_code == 422
            assert (
                await client.patch(
                    f"/v1/conversations/{cid}", json={"title": "mine"}, headers=bearer("bob")
                )
            ).status_code == 404

            plain = await client.post("/v1/conversations", json={}, headers=alice)
            body = (
                await client.post(
                    "/v1/query",
                    json={
                        "question": "Where is HQ?",
                        "conversation_id": plain.json()["conversation_id"],
                    },
                    headers=alice,
                )
            ).json()
            assert body["title"] == "Where Is Hq?"

    async def test_attached_documents_scope_the_conversation(
        self, container: Container, sample_pdf: bytes
    ) -> None:
        alice = bearer("alice")
        async with api(container) as client:
            first = await upload(client, container, sample_pdf, "alice")
            second = await upload(client, container, sample_pdf, "alice")
            conv = await client.post(
                "/v1/conversations", json={"document_ids": [second]}, headers=alice
            )
            cid = conv.json()["conversation_id"]
            assert conv.json()["document_ids"] == [second]

            async def cited(**extra: Any) -> set[str]:
                r = await client.post(
                    "/v1/query",
                    json={"question": "How many employees?", "conversation_id": cid, **extra},
                    headers=alice,
                )
                assert r.status_code == 200, r.text
                return {c["document_id"] for c in r.json()["citations"]}

            assert await cited() == {second}  # only the attached PDF is searched
            assert await cited(document_ids=[first]) <= {first, second}
            detail = (await client.get(f"/v1/conversations/{cid}", headers=alice)).json()
            assert detail["conversation"]["document_ids"] == [second, first]  # attach order

            too_many = [f"{i:032x}" for i in range(50)]
            r = await client.post(
                "/v1/query",
                json={"question": "hq?", "conversation_id": cid, "document_ids": too_many},
                headers=alice,
            )
            assert r.status_code == 422

    async def test_conversation_and_client_history_are_mutually_exclusive(
        self, container: Container
    ) -> None:
        alice = bearer("alice")
        async with api(container) as client:
            cid = (await client.post("/v1/conversations", json={}, headers=alice)).json()[
                "conversation_id"
            ]
            r = await client.post(
                "/v1/query",
                json={
                    "question": "hi",
                    "conversation_id": cid,
                    "history": [{"role": "user", "content": "x"}],
                },
                headers=alice,
            )
            assert r.status_code == 422


async def test_abandoned_stream_still_charges_estimated_usage(
    container: Container, sample_pdf: bytes
) -> None:
    await container.ingestion_service.ingest_bytes("alice", "r.pdf", sample_pdf)
    events = container.chat_service.ask_stream("alice", "How many employees?")
    await anext(events)  # sources arrive...
    await events.aclose()  # ...then the client disconnects
    account = await container.usage_service.account("alice")
    assert account.tokens_used_today > 0  # OpenAI bills partial answers, so we count them
