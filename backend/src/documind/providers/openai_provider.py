"""OpenAI implementations of the provider interfaces.

Retries: the OpenAI SDK already retries connection errors, 408/409/429 and 5xx with exponential
backoff + jitter (honouring Retry-After), so we configure it (``max_retries``/``timeout``) rather
than wrapping it in a second retry layer that would multiply attempts.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import numpy as np
import openai
import tiktoken
from numpy.typing import NDArray
from openai import AsyncOpenAI

from documind.core.errors import ProviderError
from documind.domain import Message, TokenUsage
from documind.providers.base import Completion, StreamEnd, StreamEvent, TextDelta, l2_normalize

logger = logging.getLogger(__name__)


def _wrap(exc: openai.OpenAIError) -> ProviderError:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        # A configuration problem on our side; never echo provider details to end users.
        logger.error("openai auth failed", extra={"error": str(exc)})
        return ProviderError("The language model provider rejected our credentials.")
    logger.warning("openai call failed", extra={"error": str(exc), "type": type(exc).__name__})
    return ProviderError("The language model provider is unavailable. Please retry shortly.")


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        dimensions: int,
        tokenizer: str,
        max_input_tokens: int,
        batch_max_items: int,
        batch_max_tokens: int,
        concurrency: int,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._encoding = tiktoken.get_encoding(tokenizer)
        self._max_input_tokens = max_input_tokens
        self._batch_max_items = batch_max_items
        self._batch_max_tokens = batch_max_tokens
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, self._dimensions), dtype=np.float32)
        batches = self._batches([self._truncate(t) for t in texts])
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return l2_normalize(np.vstack(results))

    def _truncate(self, text: str) -> str:
        tokens = self._encoding.encode(text)
        if len(tokens) <= self._max_input_tokens:
            return text
        return self._encoding.decode(tokens[: self._max_input_tokens])

    def _batches(self, texts: list[str]) -> list[list[str]]:
        """Group inputs so each request stays under both the item and token limits."""
        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0
        for text in texts:
            n = len(self._encoding.encode(text))
            if current and (
                len(current) >= self._batch_max_items or current_tokens + n > self._batch_max_tokens
            ):
                batches.append(current)
                current, current_tokens = [], 0
            current.append(text)
            current_tokens += n
        if current:
            batches.append(current)
        return batches

    async def _embed_batch(self, batch: list[str]) -> NDArray[np.float32]:
        async with self._semaphore:  # bound concurrency so big PDFs don't trip rate limits
            try:
                response = await self._client.embeddings.create(
                    input=batch, model=self._model, dimensions=self._dimensions
                )
            except openai.OpenAIError as exc:
                raise _wrap(exc) from exc
        ordered = sorted(response.data, key=lambda d: d.index)
        return np.asarray([d.embedding for d in ordered], dtype=np.float32)


class OpenAIChatProvider:
    def __init__(self, client: AsyncOpenAI, *, model: str, reasoning_effort: str | None) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort

    def _params(self, messages: Sequence[Message], max_output_tokens: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # For reasoning models this cap includes hidden reasoning tokens.
            "max_completion_tokens": max_output_tokens,
        }
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        return params

    async def complete(self, messages: Sequence[Message], *, max_output_tokens: int) -> Completion:
        try:
            response = await self._client.chat.completions.create(
                **self._params(messages, max_output_tokens)
            )
        except openai.OpenAIError as exc:
            raise _wrap(exc) from exc
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            usage=TokenUsage(
                usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0
            ),
        )

    async def stream(
        self, messages: Sequence[Message], *, max_output_tokens: int
    ) -> AsyncIterator[StreamEvent]:
        # Only opening the stream is retried by the SDK; a mid-stream failure surfaces to the
        # caller, because replaying would duplicate text the client has already rendered.
        usage = TokenUsage()
        try:
            stream = await self._client.chat.completions.create(
                **self._params(messages, max_output_tokens),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield TextDelta(chunk.choices[0].delta.content)
                if chunk.usage:
                    usage = TokenUsage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
        except openai.OpenAIError as exc:
            raise _wrap(exc) from exc
        yield StreamEnd(usage)
