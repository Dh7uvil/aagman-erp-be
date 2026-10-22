"""Boto3 S3 client used for both MinIO and AWS S3."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any, Protocol, cast
from uuid import UUID

from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings
from app.core.exceptions import IntegrationError


class S3ClientProtocol(Protocol):
    """Subset of the boto3 S3 client used by this adapter."""

    def put_object(self, **kwargs: Any) -> Any: ...

    def delete_object(self, **kwargs: Any) -> Any: ...

    def get_object(self, **kwargs: Any) -> Any: ...

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str: ...


def build_org_logo_key(*, organization_id: UUID, filename: str) -> str:
    """Build the object key for the singleton organization's logo."""

    return f"{organization_id}/organization/logo/{filename}"


class S3Storage:
    """Upload, delete, and read objects on an S3-compatible bucket."""

    def __init__(
        self,
        client: S3ClientProtocol,
        *,
        bucket: str,
        presign_ttl_seconds: int,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._presign_ttl_seconds = presign_ttl_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> S3Storage:
        """Build a client from application settings.

        ``S3_ENDPOINT_URL`` selects MinIO (path-style). Leaving it unset talks to AWS S3.
        """

        if not settings.s3_bucket_name:
            raise IntegrationError("Object storage is not configured")
        return cls(
            _build_boto3_client(settings),
            bucket=settings.s3_bucket_name,
            presign_ttl_seconds=settings.s3_presign_ttl_seconds,
        )

    async def upload(self, *, key: str, body: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._upload_sync, key, body, content_type)

    async def delete(self, *, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, key)

    async def download(self, *, key: str) -> tuple[bytes, str]:
        return await asyncio.to_thread(self._download_sync, key)

    def _upload_sync(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to store uploaded file") from exc

    def _delete_sync(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to delete stored file") from exc

    def _download_sync(self, key: str) -> tuple[bytes, str]:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"].read()
            content_type = response.get("ContentType") or "application/octet-stream"
            return body, str(content_type)
        except (BotoCoreError, ClientError) as exc:
            raise IntegrationError("Failed to read stored file") from exc


def _build_boto3_client(settings: Settings) -> S3ClientProtocol:
    import boto3  # type: ignore[import-untyped]

    kwargs: dict[str, Any] = {"service_name": "s3"}
    if settings.aws_region:
        kwargs["region_name"] = settings.aws_region
    if settings.aws_access_key_id is not None and settings.aws_secret_access_key is not None:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key.get_secret_value()
    if settings.s3_endpoint_url is not None:
        kwargs["endpoint_url"] = str(settings.s3_endpoint_url).rstrip("/")
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return cast(S3ClientProtocol, boto3.client(**kwargs))


@lru_cache
def get_storage() -> S3Storage:
    return S3Storage.from_settings(get_settings())


def get_optional_storage() -> S3Storage | None:
    if not get_settings().s3_bucket_name:
        return None
    return get_storage()
