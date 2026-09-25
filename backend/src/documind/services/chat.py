"""One chat turn, end to end: limits → context → retrieval → answer → accounting → history.

QueryService stays a pure "retrieve and generate" engine (the eval harness uses it directly);
this layer adds everything that depends on *who* is asking: rate limits, quotas, stored
conversations and context management.
"""

import logging
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field

from documind.core.config import Settings
from documind.core.errors import InvalidInputError
from documind.domain import Citation, Conversation, Message, TokenUsage
from documind.providers.base import TextDelta
from documind.repositories.base import ConversationRepository, NewMessage, RateLimiter
from documind.services.context import ContextManager, TokenCounter
from documind.services.conversations import DEFAULT_TITLE, ConversationService
from documind.services.query import Answer, DoneEvent, QueryService, Retrieval, SourcesEvent
from documind.services.titles import TitleGenerator
from documind.services.usage import AccountUsage, UsageService

logger = logging.getLogger(__name__)

QUERY_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ContextUsage:
    tokens: int
    limit: int
    notice: str | None = None

    @property
    def fraction(self) -> float:
        return round(min(1.0, self.tokens / self.limit), 4) if self.limit else 0.0


@dataclass(frozen=True, slots=True)
class ChatResult:
    answer: Answer
    context: ContextUsage
    account: AccountUsage
    conversation_id: str | None
    title: str | None = None  # set when this turn gave the conversation its title


@dataclass(frozen=True, slots=True)
class ChatDone:
    usage: TokenUsage
    context: ContextUsage
    account: AccountUsage


@dataclass(frozen=True, slots=True)
class ConversationTitled:
    """Sent after ``done`` on a conversation's first answer, for the sidebar."""

    title: str


ChatEvent = SourcesEvent | TextDelta | ChatDone | ConversationTitled


@dataclass
class _Turn:
    question: str
    conversation: Conversation | None
    history: list[Message]
    retrieval: Retrieval
    context: ContextUsage
    extra_usage: TokenUsage = field(default_factory=TokenUsage)  # e.g. summarisation


class ChatService:
    def __init__(
        self,
        settings: Settings,
        query: QueryService,
        conversations: ConversationService,
        conversation_repo: ConversationRepository,
        context: ContextManager,
        counter: TokenCounter,
        usage: UsageService,
        limiter: RateLimiter,
        titles: TitleGenerator,
    ) -> None:
        self._settings = settings
        self._query = query
        self._conversations = conversations
        self._conversation_repo = conversation_repo
        self._context = context
        self._counter = counter
        self._usage = usage
        self._limiter = limiter
        self._titles = titles

    async def ask(
        self,
        user_id: str,
        question: str,
        *,
        conversation_id: str | None = None,
        history: Sequence[Message] = (),
        document_ids: Sequence[str] | None = None,
    ) -> ChatResult:
        turn = await self._prepare(user_id, question, conversation_id, history, document_ids)
        answer = await self._query.generate(turn.question, turn.history, turn.retrieval)
        usage = answer.usage + turn.extra_usage
        await self._usage.record(user_id, usage)
        await self._save(user_id, turn, answer.text, answer.citations)
        title = await self._maybe_title(user_id, turn, answer.text)
        return ChatResult(
            answer=Answer(answer.text, answer.citations, usage),
            context=turn.context,
            account=await self._usage.account(user_id),
            conversation_id=conversation_id,
            title=title,
        )

    async def ask_stream(
        self,
        user_id: str,
        question: str,
        *,
        conversation_id: str | None = None,
        history: Sequence[Message] = (),
        document_ids: Sequence[str] | None = None,
    ) -> AsyncGenerator[ChatEvent]:
        turn = await self._prepare(user_id, question, conversation_id, history, document_ids)
        parts: list[str] = []
        citations: list[Citation] = []
        finished = False
        try:
            async for event in self._query.stream_from(turn.question, turn.history, turn.retrieval):
                if isinstance(event, SourcesEvent):
                    citations = event.citations
                    yield event
                elif isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield event
                elif isinstance(event, DoneEvent):
                    usage = event.usage + turn.extra_usage
                    await self._usage.record(user_id, usage)
                    finished = True
                    await self._save(user_id, turn, "".join(parts), citations)
                    yield ChatDone(usage, turn.context, await self._usage.account(user_id))
                    if title := await self._maybe_title(user_id, turn, "".join(parts)):
                        yield ConversationTitled(title)
        finally:
            if not finished:
                # Client disconnected or the provider failed mid-answer. OpenAI still bills the
                # tokens already produced, so charge an estimate rather than nothing.
                estimate = TokenUsage(turn.context.tokens, self._counter.text("".join(parts)))
                await self._usage.record(user_id, estimate + turn.retrieval.usage)
                logger.info("stream ended early; usage estimated", extra={"user_id": user_id})

    async def context_usage(self, user_id: str, conversation_id: str) -> ContextUsage:
        """How full the conversation's context is before the next question is added."""
        conversation = await self._conversations.get(user_id, conversation_id)
        messages = await self._conversation_repo.messages(user_id, conversation_id)
        history = self._context.history_for(conversation, messages)
        tokens = self._query.prompt_tokens("", history, Retrieval([], {}))
        return ContextUsage(tokens, self._context.limit)

    async def _prepare(
        self,
        user_id: str,
        question: str,
        conversation_id: str | None,
        history: Sequence[Message],
        document_ids: Sequence[str] | None,
    ) -> _Turn:
        if conversation_id and history:
            raise InvalidInputError("Send either conversation_id or history, not both.")
        await self._limiter.hit(
            user_id,
            "query",
            limit=self._settings.rate_limit_queries_per_minute,
            window_seconds=QUERY_WINDOW_SECONDS,
        )
        await self._usage.ensure_within_quota(user_id)
        conversation = (
            await self._conversations.get(user_id, conversation_id) if conversation_id else None
        )
        if conversation is not None:
            # Attachments stick to the conversation, like files dropped into a chat: later
            # questions search them without the client resending the ids.
            if document_ids:
                conversation = await self._conversations.attach(conversation, document_ids)
            document_ids = conversation.document_ids or None
        retrieval = await self._query.retrieve(user_id, question, document_ids)
        question = question.strip()

        if conversation is None:
            turns = self._query.client_history(history)
            tokens = self._query.prompt_tokens(question, turns, retrieval)
            return _Turn(
                question, None, turns, retrieval, ContextUsage(tokens, self._context.limit)
            )

        stored = await self._conversation_repo.messages(user_id, conversation.conversation_id)
        fixed = self._query.prompt_tokens(question, [], retrieval)
        fitted = await self._context.fit(conversation, stored, fixed)
        if fitted.new_summary:
            summary, through = fitted.new_summary
            await self._conversation_repo.set_summary(
                user_id, conversation.conversation_id, summary, through
            )
        return _Turn(
            question,
            conversation,
            fitted.history,
            retrieval,
            ContextUsage(fitted.tokens, self._context.limit, fitted.notice),
            fitted.usage,
        )

    async def _maybe_title(self, user_id: str, turn: _Turn, answer: str) -> str | None:
        """Name an untitled conversation from its first exchange (charged to the user)."""
        if turn.conversation is None or turn.conversation.title != DEFAULT_TITLE:
            return None
        title, usage = await self._titles.generate(turn.question, answer)
        await self._usage.record(user_id, usage)
        await self._conversation_repo.update(
            user_id, turn.conversation.conversation_id, title=title
        )
        return title

    async def _save(
        self, user_id: str, turn: _Turn, answer: str, citations: list[Citation]
    ) -> None:
        if turn.conversation is None:
            return
        await self._conversation_repo.append(
            user_id,
            turn.conversation.conversation_id,
            [NewMessage("user", turn.question), NewMessage("assistant", answer, citations)],
        )
