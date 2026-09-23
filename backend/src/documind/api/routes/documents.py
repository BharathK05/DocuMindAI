from typing import Annotated

from fastapi import APIRouter, Path, status

from documind.api.deps import ContainerDep, UserIdDep
from documind.api.schemas import (
    CreateUploadRequest,
    CreateUploadResponse,
    DocumentList,
    DocumentOut,
    UploadTarget,
)

router = APIRouter(prefix="/v1/documents", tags=["documents"])

DocumentId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_upload(
    body: CreateUploadRequest, user_id: UserIdDep, c: ContainerDep
) -> CreateUploadResponse:
    """Register a document and get a presigned URL. The client POSTs the PDF straight to S3
    (multipart form with the returned fields), then calls ``/complete``."""
    ticket = await c.document_service.create_upload(user_id, body.filename, body.size_bytes)
    return CreateUploadResponse(
        document=DocumentOut.from_domain(ticket.document),
        upload=UploadTarget(
            url=ticket.upload.url, fields=ticket.upload.fields, expires_in=ticket.upload.expires_in
        ),
    )


@router.post("/{document_id}/complete", status_code=status.HTTP_202_ACCEPTED)
async def complete_upload(
    document_id: DocumentId, user_id: UserIdDep, c: ContainerDep
) -> DocumentOut:
    """Confirm the upload finished and queue ingestion. Poll ``GET /{id}`` for status."""
    return DocumentOut.from_domain(await c.document_service.complete_upload(user_id, document_id))


@router.get("")
async def list_documents(user_id: UserIdDep, c: ContainerDep) -> DocumentList:
    docs = await c.document_service.list(user_id)
    return DocumentList(documents=[DocumentOut.from_domain(d) for d in docs])


@router.get("/{document_id}")
async def get_document(document_id: DocumentId, user_id: UserIdDep, c: ContainerDep) -> DocumentOut:
    """Document metadata, including ingestion status: pending → processing → ready | failed."""
    return DocumentOut.from_domain(await c.document_service.get(user_id, document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: DocumentId, user_id: UserIdDep, c: ContainerDep) -> None:
    await c.document_service.delete(user_id, document_id)
