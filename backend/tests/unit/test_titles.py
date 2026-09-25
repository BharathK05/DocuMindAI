"""Conversation titles written from the first exchange."""

from collections.abc import AsyncIterator, Sequence

import pytest

from documind.core.errors import InvalidInputError, ProviderError
from documind.domain import Message, TokenUsage
from documind.providers.base import Completion, StreamEvent
from documind.services.conversations import MAX_ATTACHED_DOCUMENTS, merge_documents
from documind.services.titles import (
    MAX_TITLE_CHARS,
    TITLE_PROMPT,
    TitleGenerator,
    clean_title,
    fallback_title,
)


class ScriptedLLM:
    def __init__(self, reply: str | None) -> None:
        self.reply = reply
        self.prompts: list[Sequence[Message]] = []

    async def complete(self, messages: Sequence[Message], *, max_output_tokens: int) -> Completion:
        self.prompts.append(messages)
        if self.reply is None:
            raise ProviderError("down")
        return Completion(self.reply, TokenUsage(40, 6))

    def stream(
        self, messages: Sequence[Message], *, max_output_tokens: int
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Incident Response Phases"', "Incident Response Phases"),
        ("## **Password rules**.\nextra line", "Password rules"),
        ("\n\n  Spaced    out   title  ", "Spaced out title"),
        ("", ""),
    ],
)
def test_clean_title(raw: str, expected: str) -> None:
    assert clean_title(raw) == expected


def test_long_titles_are_cut_at_a_word_boundary() -> None:
    title = clean_title("word " * 40)
    assert len(title) <= MAX_TITLE_CHARS and title.endswith("word")


def test_fallback_uses_the_question() -> None:
    assert fallback_title("  What is MFA?  ") == "What is MFA?"
    assert fallback_title("   ") == "Untitled chat"


async def test_generator_sends_the_exchange_as_data() -> None:
    llm = ScriptedLLM("MFA requirements in 800-63B")
    title, usage = await TitleGenerator(llm).generate("What does 800-63B say about MFA?", "It...")
    assert (title, usage) == ("MFA requirements in 800-63B", TokenUsage(40, 6))
    system, user = llm.prompts[0]
    assert (system.role, system.content) == ("system", TITLE_PROMPT)
    assert user.role == "user" and user.content.startswith("Question: What does 800-63B")


@pytest.mark.parametrize("reply", [None, "  "])
async def test_generator_falls_back_when_the_model_fails_or_is_empty(reply: str | None) -> None:
    title, usage = await TitleGenerator(ScriptedLLM(reply)).generate("Where is HQ?", "Paris [1]")
    assert title == "Where is HQ?"
    assert usage == (TokenUsage() if reply is None else TokenUsage(40, 6))


def test_merge_documents_keeps_order_and_caps_the_count() -> None:
    assert merge_documents(["a", "b"], ["b", "c", "a"]) == ["a", "b", "c"]
    with pytest.raises(InvalidInputError):
        merge_documents([], [str(i) for i in range(MAX_ATTACHED_DOCUMENTS + 1)])
