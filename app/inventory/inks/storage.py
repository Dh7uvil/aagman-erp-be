"""Local ink file storage."""

from pathlib import Path

from app.core.config import get_settings


def ink_file_absolute_path(storage_key: str) -> Path:
    settings = get_settings()
    return Path(settings.upload_dir) / storage_key


def read_ink_file(storage_key: str) -> tuple[bytes, str]:
    import mimetypes

    path = ink_file_absolute_path(storage_key)
    if not path.is_file():
        msg = "File not found"
        raise FileNotFoundError(msg)
    content = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return content, content_type


def write_ink_file(storage_key: str, content: bytes) -> None:
    path = ink_file_absolute_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def delete_ink_file(storage_key: str) -> None:
    path = ink_file_absolute_path(storage_key)
    if path.is_file():
        path.unlink()
