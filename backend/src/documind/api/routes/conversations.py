from typing import Annotated

from fastapi import APIRouter, Path, status

from documind.api.deps import ContainerDep, UserIdDep
from documind.api.schemas import (
    ConversationDetail,
    ConversationList,
    ConversationOut,
    CreateConversationRequest,
    MessageOut,
    RenameConversationRequest,
)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

ConversationId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: CreateConversationRequest, user_id: UserIdDep, c: ContainerDep
) -> ConversationOut:
    """Start a conversation; pass its id as ``conversation_id`` to ``/v1/query``."""
    conversation = await c.conversation_service.create(user_id, body.title, body.document_ids)
    return ConversationOut.from_domain(conversation)


@router.get("")
async def list_conversations(user_id: UserIdDep, c: ContainerDep) -> ConversationList:
    items = await c.conversation_service.list(user_id)
    return ConversationList(conversations=[ConversationOut.from_domain(x) for x in items])


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: ConversationId, user_id: UserIdDep, c: ContainerDep
) -> ConversationDetail:
    conversation = await c.conversation_service.get(user_id, conversation_id)
    messages = await c.conversation_service.messages(user_id, conversation_id)
    return ConversationDetail(
        conversation=ConversationOut.from_domain(conversation),
        messages=[MessageOut.from_domain(m) for m in messages],
    )


@router.patch("/{conversation_id}")
async def rename_conversation(
    conversation_id: ConversationId,
    body: RenameConversationRequest,
    user_id: UserIdDep,
    c: ContainerDep,
) -> ConversationOut:
    return ConversationOut.from_domain(
        await c.conversation_service.rename(user_id, conversation_id, body.title)
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: ConversationId, user_id: UserIdDep, c: ContainerDep
) -> None:
    await c.conversation_service.delete(user_id, conversation_id)
