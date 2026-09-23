"""Provider interfaces. Business logic depends only on these, so OpenAI can later be swapped for
Bedrock (or anything else) by adding one implementation and one line in the factory."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from documind.domain import Message, TokenUsage


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class StreamEnd:
    usage: TokenUsage


StreamEvent = TextDelta | StreamEnd


class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Return an (len(texts), dimensions) matrix of L2-normalised vectors."""
        ...


class LLMProvider(Protocol):
    async def complete(
        self, messages: Sequence[Message], *, max_output_tokens: int
    ) -> Completion: ...

    def stream(
        self, messages: Sequence[Message], *, max_output_tokens: int
    ) -> AsyncIterator[StreamEvent]:
        """Yield TextDelta events, then exactly one StreamEnd carrying token usage."""
        ...


def l2_normalize(matrix: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)
