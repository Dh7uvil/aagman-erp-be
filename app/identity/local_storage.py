"""Local disk storage for organization logos."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app.core.config import get_settings


def logo_relative_key(filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_").strip() or "logo"
    return f"organization/logo/{safe}"


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
