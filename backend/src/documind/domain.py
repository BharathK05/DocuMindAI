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
