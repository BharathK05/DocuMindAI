"""Question answering: embed question → retrieve chunks → prompt LLM → answer with citations."""

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import tiktoken

from documind.core.config import Settings
from documind.core.errors import InvalidInputError, NotFoundError
from documind.domain import Citation, DocumentStatus, Message, ScoredChunk, TokenUsage
from documind.providers.base import EmbeddingProvider, LLMProvider, StreamEnd, TextDelta
from documind.repositories.base import DocumentRepository, VectorStore
from documind.services.context import PER_MESSAGE_OVERHEAD
from documind.services.prompts import build_messages
from documind.services.rerank import Reranker

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
class Retrieval:
    chunks: list[ScoredChunk]
    filenames: dict[str, str]
    usage: TokenUsage = field(default_factory=TokenUsage)  # spent retrieving (reranking)

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
        reranker: Reranker | None = None,
    ) -> None:
        self._settings = settings
        self._documents = documents
        self._vectors = vectors
        self._embedder = embedder
        self._llm = llm
        self._reranker = reranker
        self._encoding = tiktoken.get_encoding(settings.chat_tokenizer)

    async def answer(
        self,
        user_id: str,
        question: str,
        history: Sequence[Message] = (),
        document_ids: Sequence[str] | None = None,
    ) -> Answer:
        retrieval = await self.retrieve(user_id, question, document_ids)
        return await self.generate(question, self.client_history(history), retrieval)

    async def generate(
        self, question: str, history: Sequence[Message], retrieval: "Retrieval"
    ) -> Answer:
        """Answer from an existing retrieval (lets the eval harness score both stages)."""
        started = time.perf_counter()
        question = self._validate(question)
        if not retrieval.chunks:
            return Answer(NO_DOCUMENTS_ANSWER, [], retrieval.usage)
        retrieval = self.fit_budget(retrieval)
        completion = await self._llm.complete(
            self._messages(question, history, retrieval),
            max_output_tokens=self._settings.chat_max_output_tokens,
        )
        usage = completion.usage + retrieval.usage
        self._log(usage, started)
        return Answer(completion.text, retrieval.citations(), usage)

    async def stream(
        self,
        user_id: str,
        question: str,
        history: Sequence[Message] = (),
        document_ids: Sequence[str] | None = None,
    ) -> AsyncIterator[QueryEvent]:
        retrieval = await self.retrieve(user_id, question, document_ids)
        async for event in self.stream_from(question, self.client_history(history), retrieval):
            yield event

    async def stream_from(
        self, question: str, history: Sequence[Message], retrieval: Retrieval
    ) -> AsyncIterator[QueryEvent]:
        """Stream an answer from an existing retrieval (sources, tokens, then done)."""
        started = time.perf_counter()
        question = self._validate(question)
        if not retrieval.chunks:
            yield SourcesEvent([])
            yield TextDelta(NO_DOCUMENTS_ANSWER)
            yield DoneEvent(retrieval.usage)
            return
        retrieval = self.fit_budget(retrieval)
        # Sources go out first so the UI can render citation cards while the answer streams.
        yield SourcesEvent(retrieval.citations())
        async for event in self._llm.stream(
            self._messages(question, history, retrieval),
            max_output_tokens=self._settings.chat_max_output_tokens,
        ):
            if isinstance(event, StreamEnd):
                usage = event.usage + retrieval.usage
                self._log(usage, started)
                yield DoneEvent(usage)
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

    async def retrieve(
        self,
        user_id: str,
        question: str,
        document_ids: Sequence[str] | None = None,
        *,
        top_k: int | None = None,
    ) -> Retrieval:
        """Rank the user's chunks for ``question``, best first."""
        question = self._validate(question)
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
            return Retrieval([], {})
        s = self._settings
        top_k = top_k or s.retrieval_top_k
        # With a reranker, fetch a wider pool first; the reranker decides the final order.
        fetch = max(top_k, s.rerank_candidates) if self._reranker else top_k
        query_vector = (await self._embedder.embed([question]))[0]
        chunks = await self._vectors.search(
            user_id,
            query_vector,
            query_text=question,
            top_k=fetch,
            document_ids=ready.keys(),
            mode=s.retrieval_mode,
            candidates=s.retrieval_candidates,
        )
        usage = TokenUsage()
        if self._reranker and len(chunks) > 1:
            reranked = await self._reranker.rerank(question, chunks)
            chunks, usage = reranked.chunks, reranked.usage
        return Retrieval(chunks[:top_k], ready, usage)

    def fit_budget(self, retrieval: Retrieval) -> Retrieval:
        """Keep best-first chunks while they fit ``context_token_budget`` (always at least one),
        so a few huge chunks can't blow up prompt size and cost."""
        kept: list[ScoredChunk] = []
        used = 0
        for scored in retrieval.chunks:
            tokens = len(self._encoding.encode(scored.chunk.text, disallowed_special=()))
            if kept and used + tokens > self._settings.context_token_budget:
                break
            kept.append(scored)
            used += tokens
        return Retrieval(kept, retrieval.filenames, retrieval.usage)

    def client_history(self, history: Sequence[Message]) -> list[Message]:
        """History sent by a stateless client: plain turns only (a client must never inject a
        system message), and only the most recent ones, which bounds prompt size."""
        turns = [m for m in history if m.role in ("user", "assistant")]
        return turns[-self._settings.max_history_messages :]

    def prompt_tokens(self, question: str, history: Sequence[Message], retrieval: Retrieval) -> int:
        """Tokens the model will receive for this turn (what the context bar shows)."""
        messages = self._messages(question, history, self.fit_budget(retrieval))
        return sum(
            len(self._encoding.encode(m.content, disallowed_special=())) + PER_MESSAGE_OVERHEAD
            for m in messages
        )

    def _messages(
        self, question: str, history: Sequence[Message], retrieval: Retrieval
    ) -> list[Message]:
        turns = [m for m in history if m.role in ("user", "assistant")]
        return build_messages(
            question,
            turns,
            retrieval.chunks,
            retrieval.filenames,
            version=self._settings.prompt_version,
        )

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
