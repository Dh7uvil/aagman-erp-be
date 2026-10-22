"""Small, domain-neutral validation helpers."""

import re
from uuid import UUID

_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
_OPTIONAL_UUID_SENTINELS = frozenset({"none", "null"})


def blank_to_none(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def optional_uuid_input(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in _OPTIONAL_UUID_SENTINELS:
            return None
        return stripped
    return value


def normalize_required_text(value: str, *, field_name: str = "value") -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty"
        raise ValueError(msg)
    return normalized


def normalize_currency_code(value: str) -> str:
    normalized = value.strip().upper()
    if _CURRENCY_CODE_PATTERN.fullmatch(normalized) is None:
        msg = "currency code must contain exactly three ASCII letters"
        raise ValueError(msg)
    return normalized


def parse_uuid(value: str | UUID, *, field_name: str = "value") -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"{field_name} must be a valid UUID"
        raise ValueError(msg) from exc
