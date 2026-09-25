"""FastAPI application factory."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from documind.api.routes import conversations, documents, query, usage
from documind.api.schemas import ErrorBody, ErrorResponse
from documind.core.auth import Authenticator, build_authenticator
from documind.core.config import Settings, get_settings
from documind.core.container import Container, build_container
from documind.core.errors import DocumindError
from documind.core.logging import configure_logging, request_id_var

logger = logging.getLogger(__name__)


def _error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id_var.get())
    )
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)


def create_app(
    settings: Settings | None = None,
    container: Container | None = None,
    authenticator: Authenticator | None = None,
) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        # Fails fast at startup if auth is misconfigured, rather than on the first request.
        app.state.authenticator = authenticator or build_authenticator(settings)
        yield

    app = FastAPI(title="DocuMind AI", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(DocumindError)
    async def domain_error(_: Request, exc: DocumindError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        return _error(422, "invalid_input", f"{where}: {first.get('msg', 'invalid request')}")

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        # Full details go to the logs only; clients get a generic message plus the request id.
        logger.exception("unhandled error")
        return _error(500, "internal_error", "Something went wrong.")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(documents.router)
    app.include_router(conversations.router)
    app.include_router(query.router)
    app.include_router(usage.router)
    return app
