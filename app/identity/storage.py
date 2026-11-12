"""Local and S3 storage helpers for the organization logo."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import get_settings


def logo_relative_key(*, organization_id: UUID, filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_").strip() or "file"
    return f"organization/{organization_id}/logo/{uuid4().hex[:8]}_{safe}"


def logo_absolute_path(storage_key: str) -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / storage_key


def read_logo(storage_key: str) -> tuple[bytes, str]:
    path = logo_absolute_path(storage_key)
    if not path.is_file():
        msg = "Organization logo not found"
        raise FileNotFoundError(msg)
    content = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return content, content_type


def write_logo(storage_key: str, content: bytes) -> None:
    path = logo_absolute_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def delete_logo(storage_key: str) -> None:
    path = logo_absolute_path(storage_key)
    if path.is_file():
        path.unlink()


def build_org_logo_object_key(*, organization_id: UUID, filename: str) -> str:
    return logo_relative_key(organization_id=organization_id, filename=filename)
