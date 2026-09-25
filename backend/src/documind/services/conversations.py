"""Conversation CRUD. Every operation is scoped to the calling user."""

import builtins
import uuid
from collections.abc import Sequence

from documind.core.errors import InvalidInputError, NotFoundError
from documind.domain import Conversation, ConversationMessage
from documind.repositories.base import ConversationRepository

DEFAULT_TITLE = "New conversation"
MAX_TITLE_CHARS = 120
MAX_ATTACHED_DOCUMENTS = 50


def merge_documents(current: Sequence[str], added: Sequence[str]) -> list[str]:
    """Attached PDFs in attach order, without duplicates."""
    merged = list(dict.fromkeys([*current, *added]))
    if len(merged) > MAX_ATTACHED_DOCUMENTS:
        raise InvalidInputError(
            f"A conversation can have at most {MAX_ATTACHED_DOCUMENTS} documents."
        )
    return merged


def _clean(title: str | None) -> str:
    return " ".join((title or "").split())[:MAX_TITLE_CHARS]


class ConversationService:
    def __init__(self, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def create(
        self, user_id: str, title: str | None = None, document_ids: Sequence[str] = ()
    ) -> Conversation:
        conversation = Conversation(
            user_id=user_id,
            conversation_id=uuid.uuid4().hex,
            title=_clean(title) or DEFAULT_TITLE,
            document_ids=merge_documents([], document_ids),
        )
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

    async def rename(self, user_id: str, conversation_id: str, title: str) -> Conversation:
        clean = _clean(title)
        if not clean:
            raise InvalidInputError("Title can't be empty.")
        return await self._conversations.update(user_id, conversation_id, title=clean)

    async def attach(self, conversation: Conversation, document_ids: Sequence[str]) -> Conversation:
        """Add PDFs to the conversation's attachments (a no-op if they're already attached)."""
        merged = merge_documents(conversation.document_ids, document_ids)
        if merged == conversation.document_ids:
            return conversation
        return await self._conversations.update(
            conversation.user_id, conversation.conversation_id, document_ids=merged
        )

    async def delete(self, user_id: str, conversation_id: str) -> None:
        await self.get(user_id, conversation_id)
        await self._conversations.delete(user_id, conversation_id)
