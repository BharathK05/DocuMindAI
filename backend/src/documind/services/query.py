"""Question answering: embed question → retrieve chunks → prompt LLM → answer with citations."""

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from documind.core.config import Settings
from documind.core.errors import InvalidInputError, NotFoundError
from documind.domain import Citation, DocumentStatus, Message, ScoredChunk, TokenUsage
from documind.providers.base import EmbeddingProvider, LLMProvider, StreamEnd, TextDelta
from documind.repositories.base import DocumentRepository, VectorStore
from documind.services.prompts import build_messages

logger = logging.getLogger(__name__)

NO_DOCUMENTS_ANSWER = "You don't have any ready documents yet. Upload a PDF, then ask again."
SNIPPET_CHARS = 300


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    citations: list[Citation]
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class SourcesEvent:
    citations: list[Citation]


@dataclass(frozen=True, slots=True)
class DoneEvent:
    usage: TokenUsage


QueryEvent = SourcesEvent | TextDelta | DoneEvent


@dataclass(frozen=True, slots=True)
class _Retrieval:
    chunks: list[ScoredChunk]
    filenames: dict[str, str]

    def citations(self) -> list[Citation]:
        return [
            Citation(
                source_id=n,
                document_id=s.chunk.document_id,
                filename=self.filenames[s.chunk.document_id],
                page=s.chunk.page,
                score=round(s.score, 4),
                snippet=s.chunk.text[:SNIPPET_CHARS],
            )
            for n, s in enumerate(self.chunks, start=1)
        ]


class QueryService:
    def __init__(
        self,
        settings: Settings,
        documents: DocumentRepository,
        vectors: VectorStore,
        embedder: EmbeddingProvider,
        llm: LLMProvider,
    ) -> None:
        self._settings = settings
        self._documents = documents
        self._vectors = vectors
        self._embedder = embedder
        self._llm = llm

    async def answer(
        self,
        user_id: str,
        question: str,
        history: Sequence[Message] = (),
        document_ids: Sequence[str] | None = None,
    ) -> Answer:
        started = time.perf_counter()
        question = self._validate(question)
        retrieval = await self._retrieve(user_id, question, document_ids)
        if not retrieval.chunks:
            return Answer(NO_DOCUMENTS_ANSWER, [], TokenUsage())
        completion = await self._llm.complete(
            self._messages(question, history, retrieval),
            max_output_tokens=self._settings.chat_max_output_tokens,
        )
        self._log(completion.usage, started)
        return Answer(completion.text, retrieval.citations(), completion.usage)

    async def stream(
        self,
        user_id: str,
        question: str,
        history: Sequence[Message] = (),
        document_ids: Sequence[str] | None = None,
    ) -> AsyncIterator[QueryEvent]:
        started = time.perf_counter()
        question = self._validate(question)
        retrieval = await self._retrieve(user_id, question, document_ids)
        if not retrieval.chunks:
            yield SourcesEvent([])
            yield TextDelta(NO_DOCUMENTS_ANSWER)
            yield DoneEvent(TokenUsage())
            return
        # Sources go out first so the UI can render citation cards while the answer streams.
        yield SourcesEvent(retrieval.citations())
        async for event in self._llm.stream(
            self._messages(question, history, retrieval),
            max_output_tokens=self._settings.chat_max_output_tokens,
        ):
            if isinstance(event, StreamEnd):
                self._log(event.usage, started)
                yield DoneEvent(event.usage)
            else:
                yield event

    def _validate(self, question: str) -> str:
        question = question.strip()
        if not question:
            raise InvalidInputError("Question must not be empty.")
        if len(question) > self._settings.max_question_chars:
            raise InvalidInputError(
                f"Question must be at most {self._settings.max_question_chars} characters."
            )
        return question

    async def _retrieve(
        self, user_id: str, question: str, document_ids: Sequence[str] | None
    ) -> _Retrieval:
        ready = {
            d.document_id: d.filename
            for d in await self._documents.list(user_id)
            if d.status == DocumentStatus.READY
        }
        if document_ids:
            missing = set(document_ids) - ready.keys()
            if missing:
                raise NotFoundError("One or more selected documents don't exist or aren't ready.")
            ready = {d: ready[d] for d in document_ids}
        if not ready:
            return _Retrieval([], {})
        query_vector = (await self._embedder.embed([question]))[0]
        chunks = await self._vectors.search(
            user_id, query_vector, top_k=self._settings.retrieval_top_k, document_ids=ready.keys()
        )
        return _Retrieval(chunks, ready)

    def _messages(
        self, question: str, history: Sequence[Message], retrieval: _Retrieval
    ) -> list[Message]:
        # Only plain conversation turns are accepted from the client, and only the most recent
        # ones, which bounds prompt size (token-budget trimming arrives with the usage bars).
        turns = [m for m in history if m.role in ("user", "assistant")]
        turns = turns[-self._settings.max_history_messages :]
        return build_messages(question, turns, retrieval.chunks, retrieval.filenames)

    def _log(self, usage: TokenUsage, started: float) -> None:
        logger.info(
            "query answered",
            extra={
                "model": self._settings.chat_model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            },
        )
