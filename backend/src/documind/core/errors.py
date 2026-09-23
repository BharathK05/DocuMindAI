"""Domain exceptions. The API layer maps each to an HTTP status; services never import FastAPI."""


class DocumindError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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
