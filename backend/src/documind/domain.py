"""Core domain types shared by every layer."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentStatus(StrEnum):
    AWAITING_UPLOAD = "awaiting_upload"  # record created, presigned URL issued
    PENDING = "pending"  # upload confirmed, ingestion job queued
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(BaseModel):
    user_id: str
    document_id: str
    filename: str
    status: DocumentStatus
    size_bytes: int | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    error: str | None = None
    # Epoch seconds; DynamoDB TTL deletes the record after this (used for abandoned uploads).
    expires_at: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def blob_key(self) -> str:
        return f"uploads/{self.user_id}/{self.document_id}.pdf"


class DocumentPatch(BaseModel):
    """Partial update. Only fields explicitly set are written."""

    status: DocumentStatus | None = None
    size_bytes: int | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    error: str | None = None
    expires_at: int | None = None


@dataclass(frozen=True, slots=True)
class Page:
    number: int  # 1-based, as shown in PDF viewers
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    document_id: str
    index: int
    page: int
    text: str
    # "Document title > section heading", prepended when embedding and keyword-matching so a
    # chunk carries its place in the document (empty for the baseline chunker).
    context: str = ""

    @property
    def search_text(self) -> str:
        return f"{self.context}\n\n{self.text}" if self.context else self.text


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    chunk: Chunk
    vector: NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float


Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens
        )


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: int  # the [n] marker the model uses in its answer
    document_id: str
    filename: str
    page: int
    score: float
    snippet: str


@dataclass(frozen=True, slots=True)
class IngestJob:
    user_id: str
    document_id: str


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """One user's chat-token consumption for one UTC day (e.g. "2026-09-25")."""

    day: str
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ConversationMessage(BaseModel):
    index: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Conversation(BaseModel):
    user_id: str
    conversation_id: str
    title: str
    message_count: int = 0
    # PDFs attached to this chat; retrieval is limited to them (empty = all the user's PDFs).
    document_ids: list[str] = Field(default_factory=list)
    # Messages [0, summarized_through) are represented by ``summary`` in the model's context.
    summary: str | None = None
    summarized_through: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
