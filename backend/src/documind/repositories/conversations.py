"""Conversation storage (in-memory and DynamoDB).

Keeping history on the server (instead of trusting whatever history the client sends) means a
client can't forge earlier "assistant" turns, and lets the API measure and manage context size.

Keys:
    PK = USER#<id>   SK = CONV#<conversation id>              → conversation metadata
    PK = USER#<id>   SK = MSG#<conversation id>#<index:06d>   → one message
"""

import asyncio
import builtins
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from documind.core.errors import NotFoundError
from documind.domain import Conversation, ConversationMessage, utcnow
from documind.repositories.base import NewMessage
from documind.repositories.dynamodb import DynamoTable

_ser = TypeSerializer()
_de = TypeDeserializer()


def _attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Serialize a JSON-mode dict for DynamoDB, which accepts Decimal but not float
    (e.g. citation scores)."""
    safe = json.loads(json.dumps(data), parse_float=Decimal)
    return {k: _ser.serialize(v) for k, v in safe.items() if v is not None}


def _stored(messages: Sequence[NewMessage], first_index: int) -> list[ConversationMessage]:
    return [
        ConversationMessage(
            index=first_index + i, role=m.role, content=m.content, citations=m.citations
        )
        for i, m in enumerate(messages)
    ]


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._conversations: dict[tuple[str, str], Conversation] = {}
        self._messages: dict[tuple[str, str], list[ConversationMessage]] = {}

    async def create(self, conversation: Conversation) -> None:
        key = (conversation.user_id, conversation.conversation_id)
        self._conversations[key] = conversation
        self._messages[key] = []

    async def get(self, user_id: str, conversation_id: str) -> Conversation | None:
        return self._conversations.get((user_id, conversation_id))

    async def list(self, user_id: str) -> list[Conversation]:
        items = [c for (uid, _), c in self._conversations.items() if uid == user_id]
        return sorted(items, key=lambda c: c.updated_at, reverse=True)

    async def messages(
        self, user_id: str, conversation_id: str
    ) -> builtins.list[ConversationMessage]:
        return list(self._messages.get((user_id, conversation_id), []))

    async def append(
        self, user_id: str, conversation_id: str, messages: Sequence[NewMessage]
    ) -> Conversation:
        key = (user_id, conversation_id)
        current = self._conversations.get(key)
        if current is None:
            raise NotFoundError("Conversation not found.")
        self._messages[key].extend(_stored(messages, current.message_count))
        updated = current.model_copy(
            update={"message_count": current.message_count + len(messages), "updated_at": utcnow()}
        )
        self._conversations[key] = updated
        return updated

    async def set_summary(
        self, user_id: str, conversation_id: str, summary: str, summarized_through: int
    ) -> None:
        key = (user_id, conversation_id)
        if key in self._conversations:
            self._conversations[key] = self._conversations[key].model_copy(
                update={"summary": summary, "summarized_through": summarized_through}
            )

    async def update(
        self,
        user_id: str,
        conversation_id: str,
        *,
        title: str | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> Conversation:
        key = (user_id, conversation_id)
        current = self._conversations.get(key)
        if current is None:
            raise NotFoundError("Conversation not found.")
        changes: dict[str, Any] = {"updated_at": utcnow()}
        if title is not None:
            changes["title"] = title
        if document_ids is not None:
            changes["document_ids"] = list(document_ids)
        self._conversations[key] = updated = current.model_copy(update=changes)
        return updated

    async def delete(self, user_id: str, conversation_id: str) -> None:
        self._conversations.pop((user_id, conversation_id), None)
        self._messages.pop((user_id, conversation_id), None)


class DynamoConversationRepository:
    def __init__(self, table: DynamoTable) -> None:
        self._t = table

    @staticmethod
    def _meta_key(user_id: str, conversation_id: str) -> dict[str, Any]:
        return {"PK": {"S": f"USER#{user_id}"}, "SK": {"S": f"CONV#{conversation_id}"}}

    @staticmethod
    def _from_item(item: dict[str, Any]) -> Conversation:
        data = {k: _de.deserialize(v) for k, v in item.items()}
        for key in ("PK", "SK", "entity"):
            data.pop(key, None)
        return Conversation.model_validate(data)

    async def create(self, conversation: Conversation) -> None:
        item = {
            **self._meta_key(conversation.user_id, conversation.conversation_id),
            "entity": {"S": "conversation"},
            **_attributes(conversation.model_dump(mode="json")),
        }
        await asyncio.to_thread(
            self._t.client.put_item,
            TableName=self._t.name,
            Item=item,
            ConditionExpression="attribute_not_exists(PK)",
        )

    async def get(self, user_id: str, conversation_id: str) -> Conversation | None:
        response = await asyncio.to_thread(
            self._t.client.get_item,
            TableName=self._t.name,
            Key=self._meta_key(user_id, conversation_id),
            ConsistentRead=True,
        )
        item = response.get("Item")
        return self._from_item(item) if item else None

    async def list(self, user_id: str) -> list[Conversation]:
        items = await asyncio.to_thread(self._t.query_prefix, f"USER#{user_id}", "CONV#")
        conversations = [self._from_item(i) for i in items]
        return sorted(conversations, key=lambda c: c.updated_at, reverse=True)

    async def messages(
        self, user_id: str, conversation_id: str
    ) -> builtins.list[ConversationMessage]:
        items = await asyncio.to_thread(
            self._t.query_prefix, f"USER#{user_id}", f"MSG#{conversation_id}#"
        )
        return [
            ConversationMessage.model_validate(
                {k: _de.deserialize(v) for k, v in i.items() if k not in ("PK", "SK", "entity")}
            )
            for i in items
        ]

    async def append(
        self, user_id: str, conversation_id: str, messages: Sequence[NewMessage]
    ) -> Conversation:
        # 1) Reserve indexes with an atomic counter increment; 2) write the messages there.
        try:
            response = await asyncio.to_thread(
                self._t.client.update_item,
                TableName=self._t.name,
                Key=self._meta_key(user_id, conversation_id),
                UpdateExpression="ADD message_count :n SET updated_at = :now",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={
                    ":n": {"N": str(len(messages))},
                    ":now": {"S": utcnow().isoformat()},
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFoundError("Conversation not found.") from exc
            raise
        conversation = self._from_item(response["Attributes"])
        first = conversation.message_count - len(messages)
        requests = [
            {
                "PutRequest": {
                    "Item": {
                        "PK": {"S": f"USER#{user_id}"},
                        "SK": {"S": f"MSG#{conversation_id}#{m.index:06d}"},
                        "entity": {"S": "message"},
                        **_attributes(m.model_dump(mode="json")),
                    }
                }
            }
            for m in _stored(messages, first)
        ]
        await asyncio.to_thread(self._t.batch_write, requests)
        return conversation

    async def set_summary(
        self, user_id: str, conversation_id: str, summary: str, summarized_through: int
    ) -> None:
        await asyncio.to_thread(
            self._t.client.update_item,
            TableName=self._t.name,
            Key=self._meta_key(user_id, conversation_id),
            UpdateExpression="SET summary = :s, summarized_through = :t",
            ExpressionAttributeValues={
                ":s": {"S": summary},
                ":t": {"N": str(summarized_through)},
            },
        )

    async def update(
        self,
        user_id: str,
        conversation_id: str,
        *,
        title: str | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> Conversation:
        sets = ["updated_at = :now"]
        values: dict[str, Any] = {":now": {"S": utcnow().isoformat()}}
        if title is not None:
            sets.append("title = :title")
            values[":title"] = {"S": title}
        if document_ids is not None:
            sets.append("document_ids = :docs")
            values[":docs"] = _ser.serialize(list(document_ids))
        try:
            response = await asyncio.to_thread(
                self._t.client.update_item,
                TableName=self._t.name,
                Key=self._meta_key(user_id, conversation_id),
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFoundError("Conversation not found.") from exc
            raise
        return self._from_item(response["Attributes"])

    async def delete(self, user_id: str, conversation_id: str) -> None:
        def _delete() -> None:
            keys = self._t.query_prefix(
                f"USER#{user_id}", f"MSG#{conversation_id}#", ProjectionExpression="PK, SK"
            )
            keys.append(self._meta_key(user_id, conversation_id))
            self._t.batch_write([{"DeleteRequest": {"Key": k}} for k in keys])

        await asyncio.to_thread(_delete)
