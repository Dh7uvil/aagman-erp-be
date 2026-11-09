"""Read nested attributes for export cells."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def path_getter(path: str) -> Callable[[Any], object]:
    parts = path.split(".")

    def getter(row: Any) -> object:
        current = row
        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
                continue
            current = getattr(current, part, None)
        return current

    return getter


def attr_getter(attr: str) -> Callable[[Any], object]:
    return path_getter(attr)


def role_labels(row: Any) -> object:
    roles = getattr(row, "roles", None)
    if not roles:
        return ""
    return ", ".join(getattr(role, "name", str(role)) for role in roles)
