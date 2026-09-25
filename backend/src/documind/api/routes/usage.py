from typing import Annotated

from fastapi import APIRouter, Query

from documind.api.deps import ContainerDep, UserIdDep
from documind.api.schemas import AccountOut, ContextOut, UsageResponse

router = APIRouter(prefix="/v1/usage", tags=["usage"])


@router.get("")
async def get_usage(
    user_id: UserIdDep,
    c: ContainerDep,
    conversation_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")] = None,
) -> UsageResponse:
    """Figures for the two usage bars: tokens used today vs the daily quota (with reset time),
    and, for a conversation, how full its context window currently is."""
    account = await c.usage_service.account(user_id)
    context = (
        await c.chat_service.context_usage(user_id, conversation_id) if conversation_id else None
    )
    return UsageResponse(
        account=AccountOut.from_domain(account),
        context=ContextOut.from_domain(context) if context else None,
    )
