"""Conversation CRUD. Every operation is scoped to the calling user."""

import builtins
import uuid

from documind.core.errors import NotFoundError
from documind.domain import Conversation, ConversationMessage
from documind.repositories.base import ConversationRepository

DEFAULT_TITLE = "New conversation"
MAX_TITLE_CHARS = 120


class ConversationService:
    def __init__(self, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        clean = " ".join((title or "").split())[:MAX_TITLE_CHARS] or DEFAULT_TITLE
        conversation = Conversation(user_id=user_id, conversation_id=uuid.uuid4().hex, title=clean)
        await self._conversations.create(conversation)
        return conversation

    async def get(self, user_id: str, conversation_id: str) -> Conversation:
        conversation = await self._conversations.get(user_id, conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation

    async def list(self, user_id: str) -> list[Conversation]:
        return await self._conversations.list(user_id)

    async def messages(
        self, user_id: str, conversation_id: str
    ) -> builtins.list[ConversationMessage]:
        await self.get(user_id, conversation_id)
        return await self._conversations.messages(user_id, conversation_id)

    async def delete(self, user_id: str, conversation_id: str) -> None:
        await self.get(user_id, conversation_id)
        await self._conversations.delete(user_id, conversation_id)
