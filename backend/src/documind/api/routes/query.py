import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from documind.api.deps import ContainerDep, UserIdDep
from documind.api.schemas import (
    AccountOut,
    CitationOut,
    ContextOut,
    QueryRequest,
    QueryResponse,
    UsageOut,
)
from documind.core.errors import DocumindError
from documind.providers.base import TextDelta
from documind.services.chat import ChatDone, ChatEvent, ConversationTitled
from documind.services.query import SourcesEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/query", tags=["query"])


@router.post("")
async def query(body: QueryRequest, user_id: UserIdDep, c: ContainerDep) -> QueryResponse:
    result = await c.chat_service.ask(
        user_id,
        body.question,
        conversation_id=body.conversation_id,
        history=[t.to_domain() for t in body.history],
        document_ids=body.document_ids,
    )
    return QueryResponse(
        answer=result.answer.text,
        citations=[CitationOut.from_domain(x) for x in result.answer.citations],
        usage=UsageOut.from_domain(result.answer.usage),
        context=ContextOut.from_domain(result.context),
        account=AccountOut.from_domain(result.account),
        conversation_id=result.conversation_id,
        title=result.title,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _encode(event: ChatEvent) -> str:
    match event:
        case SourcesEvent(citations):
            return _sse("sources", [CitationOut.from_domain(x).model_dump() for x in citations])
        case TextDelta(text):
            return _sse("token", {"text": text})
        case ChatDone(usage, context, account):
            return _sse(
                "done",
                {
                    "usage": UsageOut.from_domain(usage).model_dump(),
                    "context": ContextOut.from_domain(context).model_dump(),
                    "account": AccountOut.from_domain(account).model_dump(mode="json"),
                },
            )
        case ConversationTitled(title):
            return _sse("title", {"title": title})


@router.post("/stream", response_class=StreamingResponse)
async def query_stream(
    body: QueryRequest, user_id: UserIdDep, c: ContainerDep
) -> StreamingResponse:
    """Server-Sent Events: one ``sources`` event, many ``token`` events, then ``done`` with
    token usage, context-window and daily-quota figures (or ``error`` if the model fails).
    A conversation's first answer is followed by a ``title`` event naming the conversation."""
    events = c.chat_service.ask_stream(
        user_id,
        body.question,
        conversation_id=body.conversation_id,
        history=[t.to_domain() for t in body.history],
        document_ids=body.document_ids,
    )
    # Pull the first event before responding, so auth/limit/validation errors still become a
    # proper HTTP 4xx instead of an error hidden inside a 200 stream.
    first = await anext(events)

    async def body_iter() -> AsyncIterator[str]:
        yield _encode(first)
        try:
            async for event in events:
                yield _encode(event)
        except DocumindError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception:
            logger.exception("stream failed")
            yield _sse("error", {"code": "internal_error", "message": "Something went wrong."})

    return StreamingResponse(
        body_iter(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
