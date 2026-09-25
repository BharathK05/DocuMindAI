"""HTTP request/response models. Kept separate from domain types so the API contract can evolve
independently of storage."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from documind.domain import (
    Citation,
    Conversation,
    ConversationMessage,
    Document,
    DocumentStatus,
    Message,
    TokenUsage,
)
from documind.services.chat import ContextUsage
from documind.services.usage import AccountUsage


class DocumentOut(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    size_bytes: int | None
    page_count: int | None
    chunk_count: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, d: Document) -> "DocumentOut":
        return cls.model_validate(d.model_dump(exclude={"user_id"}))


class DocumentList(BaseModel):
    documents: list[DocumentOut]


class CreateUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class UploadTarget(BaseModel):
    url: str
    fields: dict[str, str]
    expires_in: int


class CreateUploadResponse(BaseModel):
    document: DocumentOut
    upload: UploadTarget


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)

    def to_domain(self) -> Message:
        return Message(self.role, self.content)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)
    # Restrict retrieval to these documents; omit to search all of the user's documents.
    document_ids: list[str] | None = Field(default=None, max_length=50)
    # Continue a stored conversation (server keeps and manages history). Mutually exclusive
    # with `history`, which is for stateless clients.
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class CitationOut(BaseModel):
    source_id: int
    document_id: str
    filename: str
    page: int
    score: float
    snippet: str

    @classmethod
    def from_domain(cls, c: Citation) -> "CitationOut":
        return cls(**{f: getattr(c, f) for f in cls.model_fields})


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int

    @classmethod
    def from_domain(cls, u: TokenUsage) -> "UsageOut":
        return cls(input_tokens=u.input_tokens, output_tokens=u.output_tokens)


class ContextOut(BaseModel):
    """Drives the context-window bar: e.g. 18.4k / 16k → amber at 70%, red at 90%."""

    tokens: int
    limit: int
    fraction: float
    notice: str | None = None  # set when older turns were summarized or dropped

    @classmethod
    def from_domain(cls, c: ContextUsage) -> "ContextOut":
        return cls(tokens=c.tokens, limit=c.limit, fraction=c.fraction, notice=c.notice)


class AccountOut(BaseModel):
    """Drives the usage-limit bar."""

    tokens_used_today: int
    daily_quota: int
    remaining: int
    reset_at: datetime
    cost_usd_today: float

    @classmethod
    def from_domain(cls, a: AccountUsage) -> "AccountOut":
        return cls(
            tokens_used_today=a.tokens_used_today,
            daily_quota=a.daily_quota,
            remaining=a.remaining,
            reset_at=a.reset_at,
            cost_usd_today=a.cost_usd_today,
        )


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    usage: UsageOut  # tokens used by this request
    context: ContextOut
    account: AccountOut
    conversation_id: str | None = None


class UsageResponse(BaseModel):
    account: AccountOut
    context: ContextOut | None = None  # only when a conversation_id is given


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    conversation_id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, c: Conversation) -> "ConversationOut":
        return cls.model_validate(c.model_dump(include=set(cls.model_fields)))


class ConversationList(BaseModel):
    conversations: list[ConversationOut]


class MessageOut(BaseModel):
    index: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut]
    created_at: datetime

    @classmethod
    def from_domain(cls, m: ConversationMessage) -> "MessageOut":
        return cls(
            index=m.index,
            role=m.role,
            content=m.content,
            citations=[CitationOut.from_domain(c) for c in m.citations],
            created_at=m.created_at,
        )


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
