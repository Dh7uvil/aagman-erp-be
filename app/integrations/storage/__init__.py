"""S3-compatible object storage (MinIO locally, AWS S3 in production)."""

from app.integrations.storage.client import (
    S3Storage,
    build_org_logo_key,
    get_optional_storage,
    get_storage,
)

__all__ = [
    "S3Storage",
    "build_org_logo_key",
    "get_optional_storage",
    "get_storage",
]
