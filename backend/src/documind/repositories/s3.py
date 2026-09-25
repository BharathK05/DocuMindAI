"""S3 blob store. Uploads go browser → S3 directly via presigned POST, never through Lambda
(which caps request payloads at 6 MB and would bill for the transfer time)."""

import asyncio
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from documind.core.errors import NotFoundError
from documind.repositories.base import PresignedUpload

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3BlobStore:
    def __init__(self, client: "S3Client", presign_client: "S3Client", bucket: str) -> None:
        self._client = client
        self._presign_client = presign_client  # signed for the browser-visible endpoint
        self._bucket = bucket

    def presign_upload(self, key: str, *, max_bytes: int, expires_in: int) -> PresignedUpload:
        # Presigned POST (unlike PUT) lets S3 itself reject oversized files via the policy.
        post = self._presign_client.generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": "application/pdf"},
            Conditions=[
                ["content-length-range", 1, max_bytes],
                {"Content-Type": "application/pdf"},
            ],
            ExpiresIn=expires_in,
        )
        return PresignedUpload(url=post["url"], fields=post["fields"], expires_in=expires_in)

    async def size(self, key: str) -> int | None:
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return head["ContentLength"]

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                raise NotFoundError("Upload not found.") from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
