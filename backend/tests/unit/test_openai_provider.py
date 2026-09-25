"""OpenAI provider tests against a stub client: no network, no tokens spent."""

from types import SimpleNamespace
from typing import Any

import httpx2  # the OpenAI SDK v3 HTTP client
import numpy as np
import openai
import pytest

from documind.core.errors import ProviderError
from documind.domain import Message
from documind.providers.base import StreamEnd, TextDelta
from documind.providers.openai_provider import OpenAIChatProvider, OpenAIEmbeddingProvider


class StubEmbeddings:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_with = fail_with

    async def create(self, *, input: list[str], model: str, dimensions: int) -> Any:
        if self.fail_with:
            raise self.fail_with
        self.calls.append(input)
        # Return rows out of order to prove the provider re-sorts by index.
        data = [
            SimpleNamespace(index=i, embedding=[float(len(t)), 1.0] + [0.0] * (dimensions - 2))
            for i, t in enumerate(input)
        ]
        return SimpleNamespace(data=list(reversed(data)))


def embedder(stub: StubEmbeddings, **overrides: Any) -> OpenAIEmbeddingProvider:
    options: dict[str, Any] = {
        "model": "text-embedding-3-small",
        "dimensions": 4,
        "tokenizer": "cl100k_base",
        "max_input_tokens": 8191,
        "batch_max_items": 3,
        "batch_max_tokens": 10_000,
        "concurrency": 2,
    } | overrides
    return OpenAIEmbeddingProvider(SimpleNamespace(embeddings=stub), **options)  # type: ignore[arg-type]


async def test_embed_batches_by_item_count_and_preserves_order() -> None:
    stub = StubEmbeddings()
    texts = ["a", "bb", "ccc", "dddd", "eeeee", "ffffff", "g"]
    vectors = await embedder(stub).embed(texts)
    assert [len(c) for c in stub.calls] == [3, 3, 1]
    assert vectors.shape == (7, 4)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-5)
    # First component tracks text length, so ordering is observable after normalisation.
    ratios = vectors[:, 0] / vectors[:, 1]
    np.testing.assert_allclose(ratios, [len(t) for t in texts], rtol=1e-5)


async def test_embed_batches_by_token_budget() -> None:
    stub = StubEmbeddings()
    texts = ["word " * 30] * 4  # ~30 tokens each
    await embedder(stub, batch_max_items=100, batch_max_tokens=70).embed(texts)
    assert [len(c) for c in stub.calls] == [2, 2]


async def test_embed_empty_input_makes_no_calls() -> None:
    stub = StubEmbeddings()
    assert (await embedder(stub).embed([])).shape == (0, 4)
    assert stub.calls == []


async def test_embed_wraps_provider_errors() -> None:
    request = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")
    error = openai.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )
    with pytest.raises(ProviderError, match="unavailable"):
        await embedder(StubEmbeddings(fail_with=error)).embed(["x"])


class StubCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        usage = SimpleNamespace(prompt_tokens=11, completion_tokens=3)
        if not kwargs.get("stream"):
            message = SimpleNamespace(content="Hello there")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

        async def chunks() -> Any:
            for piece in ["Hel", "lo"]:
                delta = SimpleNamespace(content=piece)
                yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)
            yield SimpleNamespace(choices=[], usage=usage)

        return chunks()


def chat(stub: StubCompletions) -> OpenAIChatProvider:
    client = SimpleNamespace(chat=SimpleNamespace(completions=stub))
    return OpenAIChatProvider(client, model="gpt-test", reasoning_effort="low")  # type: ignore[arg-type]


async def test_complete_sends_caps_and_returns_usage() -> None:
    stub = StubCompletions()
    result = await chat(stub).complete([Message("user", "hi")], max_output_tokens=50)
    assert result.text == "Hello there"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 3)
    assert stub.kwargs["max_completion_tokens"] == 50
    assert stub.kwargs["reasoning_effort"] == "low"
    assert stub.kwargs["model"] == "gpt-test"


async def test_stream_yields_deltas_then_usage() -> None:
    events = [e async for e in chat(StubCompletions()).stream([], max_output_tokens=50)]
    assert events[:-1] == [TextDelta("Hel"), TextDelta("lo")]
    assert isinstance(events[-1], StreamEnd)
    assert events[-1].usage.input_tokens == 11
