"""HTTP request/response models. Kept separate from domain types so the API contract can evolve
independently of storage."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from documind.domain import Citation, Document, DocumentStatus, Message, TokenUsage


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


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    usage: UsageOut


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
