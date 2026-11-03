"""Local and S3 storage helpers for job file slots."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import get_settings


def cylinder_file_relative_key(*, cylinder_id: UUID, slot: str, filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_").strip() or "file"
    return f"cylinders/{cylinder_id}/{slot}/{uuid4().hex[:8]}_{safe}"


def cylinder_file_absolute_path(storage_key: str) -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / storage_key


def read_cylinder_file(storage_key: str) -> tuple[bytes, str]:
    import mimetypes

    path = cylinder_file_absolute_path(storage_key)
    if not path.is_file():
        msg = "File not found"
        raise FileNotFoundError(msg)
    content = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return content, content_type


def write_cylinder_file(storage_key: str, content: bytes) -> None:
    path = cylinder_file_absolute_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def delete_cylinder_file(storage_key: str) -> None:
    path = cylinder_file_absolute_path(storage_key)
    if path.is_file():
        path.unlink()


def build_cylinder_file_object_key(*, cylinder_id: UUID, slot: str, filename: str) -> str:
    return cylinder_file_relative_key(cylinder_id=cylinder_id, slot=slot, filename=filename)
