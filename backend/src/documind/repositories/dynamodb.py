"""DynamoDB single-table implementations.

Key design (one partition per user, so every read is a cheap, isolated Query):

    PK = USER#<user_id>   SK = DOC#<document_id>               → document metadata
    PK = USER#<user_id>   SK = CHUNK#<document_id>#<index:05d> → chunk text, page, float16 vector

boto3 is synchronous; calls run in a worker thread so they don't block the event loop locally.
(On Lambda each instance serves one request at a time, so this costs nothing there.)
"""

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from numpy.typing import NDArray

from documind.core import metrics
from documind.core.config import RetrievalMode
from documind.core.errors import ConflictError, NotFoundError
from documind.domain import (
    Chunk,
    Document,
    DocumentPatch,
    DocumentStatus,
    EmbeddedChunk,
    ScoredChunk,
    utcnow,
)
from documind.repositories.search import rank
from documind.repositories.vector_math import decode_vector, encode_vector

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

logger = logging.getLogger(__name__)

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()
_BATCH_WRITE_LIMIT = 25


def _pk(user_id: str) -> str:
    return f"USER#{user_id}"


def _doc_sk(document_id: str) -> str:
    return f"DOC#{document_id}"


def _chunk_prefix(document_id: str) -> str:
    return f"CHUNK#{document_id}#"


def _to_item(data: dict[str, Any]) -> dict[str, Any]:
    return {k: _serializer.serialize(v) for k, v in data.items() if v is not None}


def _from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _deserializer.deserialize(v) for k, v in item.items()}


def _document_from_item(item: dict[str, Any]) -> Document:
    data = _from_item(item)
    for key in ("PK", "SK", "entity"):
        data.pop(key, None)
    return Document.model_validate(data)


def _chunks(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class DynamoTable:
    """Thin shared wrapper: pagination and batch writes with unprocessed-item retries."""

    def __init__(self, client: "DynamoDBClient", table_name: str) -> None:
        self.client = client
        self.name = table_name

    def query_all(self, **kwargs: Any) -> list[dict[str, Any]]:
        paginator = self.client.get_paginator("query")
        items: list[dict[str, Any]] = []
        # Queries are where read capacity goes (a document's chunks are ~4 KB each), so every
        # page reports what it consumed into the current request's stats.
        pages = paginator.paginate(TableName=self.name, ReturnConsumedCapacity="TOTAL", **kwargs)
        for page in pages:
            items.extend(page["Items"])
            metrics.add_read_units(float(page.get("ConsumedCapacity", {}).get("CapacityUnits", 0)))
        return items

    def query_prefix(self, pk: str, sk_prefix: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self.query_all(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": {"S": pk}, ":prefix": {"S": sk_prefix}},
            **kwargs,
        )

    def batch_write(self, requests: list[dict[str, Any]]) -> None:
        for batch in _chunks(requests, _BATCH_WRITE_LIMIT):
            pending: dict[str, Any] = {self.name: batch}
            for attempt in range(8):
                response = self.client.batch_write_item(RequestItems=pending)
                pending = response.get("UnprocessedItems") or {}
                if not pending:
                    break
                # Throttled: back off exponentially before resubmitting the leftovers.
                time.sleep(min(2.0, 0.05 * 2**attempt))
            else:
                raise RuntimeError("DynamoDB batch write kept returning unprocessed items")


class DynamoDocumentRepository:
    def __init__(self, table: DynamoTable) -> None:
        self._t = table

    async def create(self, document: Document) -> None:
        item = _to_item(
            {
                "PK": _pk(document.user_id),
                "SK": _doc_sk(document.document_id),
                "entity": "document",
                **document.model_dump(mode="json"),
            }
        )
        await asyncio.to_thread(
            self._t.client.put_item,
            TableName=self._t.name,
            Item=item,
            ConditionExpression="attribute_not_exists(PK)",
        )

    async def get(self, user_id: str, document_id: str) -> Document | None:
        response = await asyncio.to_thread(
            self._t.client.get_item,
            TableName=self._t.name,
            Key={"PK": {"S": _pk(user_id)}, "SK": {"S": _doc_sk(document_id)}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _document_from_item(item) if item else None

    async def list(self, user_id: str) -> list[Document]:
        items = await asyncio.to_thread(self._t.query_prefix, _pk(user_id), "DOC#")
        docs = [_document_from_item(i) for i in items]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)

    async def update(
        self,
        user_id: str,
        document_id: str,
        patch: DocumentPatch,
        *,
        expected_status: Collection[DocumentStatus] | None = None,
    ) -> Document:
        fields = {
            **patch.model_dump(mode="json", exclude_unset=True),
            "updated_at": utcnow().isoformat(),
        }
        names = {f"#{k}": k for k in fields}
        values = {f":{k}": _serializer.serialize(v) for k, v in fields.items()}
        condition = "attribute_exists(PK)"
        if expected_status is not None:
            names["#status"] = "status"
            placeholders = []
            for i, status in enumerate(expected_status):
                values[f":expected{i}"] = {"S": status.value}
                placeholders.append(f":expected{i}")
            condition += f" AND #status IN ({', '.join(placeholders)})"
        try:
            response = await asyncio.to_thread(
                self._t.client.update_item,
                TableName=self._t.name,
                Key={"PK": {"S": _pk(user_id)}, "SK": {"S": _doc_sk(document_id)}},
                UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
                # Lets us tell "missing" apart from "wrong status" without a second read.
                ReturnValuesOnConditionCheckFailure="ALL_OLD",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            old: dict[str, Any] | None = exc.response.get("Item")  # type: ignore[assignment]
            if not old:
                raise NotFoundError("Document not found.") from exc
            raise ConflictError(f"Document is {_document_from_item(old).status}.") from exc
        return _document_from_item(response["Attributes"])

    async def delete(self, user_id: str, document_id: str) -> None:
        await asyncio.to_thread(
            self._t.client.delete_item,
            TableName=self._t.name,
            Key={"PK": {"S": _pk(user_id)}, "SK": {"S": _doc_sk(document_id)}},
        )


@dataclass(frozen=True, slots=True)
class DocumentChunks:
    """One document's chunks, decoded and ready to rank."""

    chunks: list[Chunk]
    vectors: NDArray[np.float32]  # (len(chunks), dimensions)


class ChunkCache:
    """Least-recently-used cache of decoded chunks per (user, document), capped by chunk count.

    Safe without invalidation because a ready document's chunks never change (re-uploading
    creates a new document id). Keys include the user id, so tenants never share entries.
    Loads happen in worker threads, hence the lock.
    """

    def __init__(self, max_chunks: int) -> None:
        self._max = max_chunks
        self._items: OrderedDict[tuple[str, str], DocumentChunks] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return self._size

    def get(self, key: tuple[str, str]) -> DocumentChunks | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: tuple[str, str], value: DocumentChunks) -> None:
        n = len(value.chunks)
        if n == 0 or n > self._max:
            return
        with self._lock:
            if (old := self._items.pop(key, None)) is not None:
                self._size -= len(old.chunks)
            while self._items and self._size + n > self._max:
                _, evicted = self._items.popitem(last=False)
                self._size -= len(evicted.chunks)
            self._items[key] = value
            self._size += n

    def discard(self, key: tuple[str, str]) -> None:
        with self._lock:
            if (old := self._items.pop(key, None)) is not None:
                self._size -= len(old.chunks)


class DynamoVectorStore:
    """Exact in-process vector search over a user's chunks stored in DynamoDB.

    A cold read of a document costs ~0.5 read units per 4 KB of chunks (text + a 3 KB float16
    vector each), i.e. ~90 units for an 80-page PDF: more than the free tier's 15-25 units per
    second. The ``ChunkCache`` keeps decoded chunks in the Lambda instance's memory, so repeat
    questions on the same documents read nothing but a few small items. Beyond a few thousand
    pages per user, swap this class for pgvector/OpenSearch/S3 Vectors behind VectorStore.
    """

    def __init__(self, table: DynamoTable, cache: ChunkCache | None = None) -> None:
        self._t = table
        self._cache = cache

    async def upsert(self, user_id: str, chunks: Sequence[EmbeddedChunk]) -> None:
        # Deterministic keys make re-ingestion idempotent: a retried job overwrites, not duplicates.
        requests = [
            {
                "PutRequest": {
                    "Item": {
                        "PK": {"S": _pk(user_id)},
                        "SK": {"S": f"{_chunk_prefix(c.chunk.document_id)}{c.chunk.index:05d}"},
                        "entity": {"S": "chunk"},
                        "document_id": {"S": c.chunk.document_id},
                        "idx": {"N": str(c.chunk.index)},
                        "page": {"N": str(c.chunk.page)},
                        "text": {"S": c.chunk.text},
                        "vec": {"B": encode_vector(c.vector)},
                        **({"ctx": {"S": c.chunk.context}} if c.chunk.context else {}),
                    }
                }
            }
            for c in chunks
        ]
        await asyncio.to_thread(self._t.batch_write, requests)

    def _read(self, user_id: str, document_id: str) -> DocumentChunks:
        items = self._t.query_prefix(_pk(user_id), _chunk_prefix(document_id))
        chunks = [
            Chunk(
                document_id=i["document_id"]["S"],
                index=int(i["idx"]["N"]),
                page=int(i["page"]["N"]),
                text=i["text"]["S"],
                context=i.get("ctx", {}).get("S", ""),
            )
            for i in items
        ]
        vectors = (
            np.vstack([decode_vector(i["vec"]["B"]) for i in items])
            if items
            else np.empty((0, 0), dtype=np.float32)
        )
        return DocumentChunks(chunks, vectors)

    async def _load(self, user_id: str, document_id: str) -> DocumentChunks:
        key = (user_id, document_id)
        if self._cache is not None and (cached := self._cache.get(key)) is not None:
            metrics.add_cache_result(hit=True)
            return cached
        loaded = await asyncio.to_thread(self._read, user_id, document_id)
        if self._cache is not None:
            metrics.add_cache_result(hit=False)
            self._cache.put(key, loaded)
        return loaded

    async def search(
        self,
        user_id: str,
        query: NDArray[np.float32],
        *,
        query_text: str,
        top_k: int,
        document_ids: Collection[str],
        mode: RetrievalMode = RetrievalMode.DENSE,
        candidates: int = 30,
    ) -> list[ScoredChunk]:
        docs = [
            d
            for d in await asyncio.gather(*(self._load(user_id, i) for i in document_ids))
            if d.chunks
        ]
        if not docs:
            return []
        chunks = [c for d in docs for c in d.chunks]
        ranked = rank(
            [c.search_text for c in chunks],
            np.vstack([d.vectors for d in docs]),
            query,
            query_text,
            top_k=top_k,
            mode=mode,
            candidates=candidates,
        )
        return [ScoredChunk(chunks[idx], score) for idx, score in ranked]

    async def delete_document(self, user_id: str, document_id: str) -> None:
        def _delete() -> None:
            keys = self._t.query_prefix(
                _pk(user_id), _chunk_prefix(document_id), ProjectionExpression="PK, SK"
            )
            self._t.batch_write([{"DeleteRequest": {"Key": k}} for k in keys])

        await asyncio.to_thread(_delete)
        if self._cache is not None:
            self._cache.discard((user_id, document_id))
