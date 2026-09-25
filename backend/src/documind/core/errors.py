"""Domain exceptions. The API layer maps each to an HTTP status; services never import FastAPI."""


class DocumindError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @property
    def headers(self) -> dict[str, str]:
        """Extra HTTP headers for this error (e.g. Retry-After)."""
        return {}


class NotFoundError(DocumindError):
    status_code = 404
    code = "not_found"


class InvalidInputError(DocumindError):
    status_code = 422
    code = "invalid_input"


class PayloadTooLargeError(DocumindError):
    status_code = 413
    code = "payload_too_large"


class ConflictError(DocumindError):
    status_code = 409
    code = "conflict"


class InvalidDocumentError(DocumindError):
    """The uploaded file can never be ingested (corrupt, encrypted, no text). Not retryable."""

    status_code = 422
    code = "invalid_document"


class ProviderError(DocumindError):
    """The LLM/embedding provider failed after retries. Usually transient."""

    status_code = 503
    code = "provider_unavailable"


class UnauthorizedError(DocumindError):
    status_code = 401
    code = "unauthorized"

    @property
    def headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": "Bearer"}


class RateLimitedError(DocumindError):
    """Too many requests in the current window. ``retry_after`` is in seconds."""

    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after

    @property
    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)}


class QuotaExceededError(RateLimitedError):
    """The user's daily token quota is used up until ``retry_after`` seconds from now."""

    code = "quota_exceeded"
