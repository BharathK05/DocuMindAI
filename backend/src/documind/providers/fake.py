"""Deterministic offline providers for tests, load tests and running without an API key.

The fake embedder is a hashed bag-of-words, so retrieval still behaves sensibly (chunks sharing
words with the question score higher), which keeps end-to-end tests meaningful.
"""

import hashlib
import re
from collections.abc import AsyncIterator, Sequence

import numpy as np
from numpy.typing import NDArray

from documind.domain import Message, TokenUsage
from documind.providers.base import Completion, StreamEnd, StreamEvent, TextDelta, l2_normalize

_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        matrix = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.lower()):
                digest = hashlib.blake2b(word.encode(), digest_size=4).digest()
                matrix[row, int.from_bytes(digest) % self._dimensions] += 1.0
        return l2_normalize(matrix)


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeLLMProvider:
    """Answers by quoting the start of the first source in the prompt, citing it as [1]."""

    def _answer(self, messages: Sequence[Message]) -> str:
        prompt = messages[-1].content
        if messages[0].content.startswith("Write a title"):  # services.titles.TITLE_PROMPT
            question = prompt.removeprefix("Question: ").split("\n", 1)[0]
            return " ".join(question.split()[:5]).title()
        match = re.search(r'<source id="1"[^>]*>\s*(.*?)\s*</source>', prompt, re.DOTALL)
        if not match:
            return "I don't know. The provided documents don't contain that information."
        return f"According to the document: {match.group(1)[:200]} [1]"

    def _usage(self, messages: Sequence[Message], answer: str) -> TokenUsage:
        return TokenUsage(sum(_approx_tokens(m.content) for m in messages), _approx_tokens(answer))

    async def complete(self, messages: Sequence[Message], *, max_output_tokens: int) -> Completion:
        answer = self._answer(messages)
        return Completion(answer, self._usage(messages, answer))

    async def stream(
        self, messages: Sequence[Message], *, max_output_tokens: int
    ) -> AsyncIterator[StreamEvent]:
        answer = self._answer(messages)
        for word in re.findall(r"\S+\s*", answer):
            yield TextDelta(word)
        yield StreamEnd(self._usage(messages, answer))
