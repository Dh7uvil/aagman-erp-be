"""Shared ILIKE search helpers, including related-entity EXISTS matches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import exists, literal, or_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.db.base import Base

_ILIKE_ESCAPE = "\\"


@dataclass(frozen=True, slots=True)
class RelatedSearch:
    """Match list rows when a related entity's text fields contain the search term."""

    model: type[Base]
    local_key: str
    fields: frozenset[str] = frozenset()
    remote_key: str = "id"
    nested: tuple[RelatedSearch, ...] = ()
    equals: tuple[tuple[str, str], ...] = ()
    null_keys: tuple[str, ...] = ()


def mapped_column(model: type[Any], name: str) -> InstrumentedAttribute[Any]:
    """Return a mapped column or raise if ``name`` is not an instrumented attribute."""

    column = getattr(model, name, None)
    if not isinstance(column, InstrumentedAttribute):
        msg = f"{model.__name__} has no mapped column {name!r}"
        raise TypeError(msg)
    return column


def ilike_pattern(term: str) -> str:
    """Build a case-insensitive partial-match pattern, escaping ``%``, ``_``, and ``\\``."""

    escaped = (
        term.replace(_ILIKE_ESCAPE, _ILIKE_ESCAPE + _ILIKE_ESCAPE)
        .replace("%", _ILIKE_ESCAPE + "%")
        .replace("_", _ILIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def column_ilike(column: InstrumentedAttribute[Any], pattern: str) -> ColumnElement[bool]:
    """ILIKE with an explicit escape so user input is treated as a literal substring."""

    return column.ilike(pattern, escape=_ILIKE_ESCAPE)


def validate_related_search(spec: RelatedSearch, parent: type[Any]) -> None:
    """Ensure every related-search key is a mapped column on the expected model."""

    mapped_column(parent, spec.local_key)
    mapped_column(spec.model, spec.remote_key)
    for field in spec.fields:
        mapped_column(spec.model, field)
    for name, _value in spec.equals:
        mapped_column(spec.model, name)
    for name in spec.null_keys:
        mapped_column(spec.model, name)
    if not spec.fields and not spec.nested:
        msg = f"{spec.model.__name__} related search has no fields or nested matches"
        raise ValueError(msg)
    for child in spec.nested:
        validate_related_search(child, spec.model)


def related_exists(
    spec: RelatedSearch,
    *,
    parent: type[Any],
    tenant_id: UUID,
    pattern: str,
) -> ColumnElement[bool]:
    """EXISTS subquery correlating ``parent.local_key`` to ``spec.model.remote_key``."""

    related = spec.model
    match_parts: list[ColumnElement[bool]] = [
        column_ilike(mapped_column(related, field), pattern) for field in spec.fields
    ]
    match_parts.extend(
        related_exists(child, parent=related, tenant_id=tenant_id, pattern=pattern)
        for child in spec.nested
    )
    criteria: list[ColumnElement[bool]] = [
        mapped_column(related, spec.remote_key) == mapped_column(parent, spec.local_key),
        or_(*match_parts),
    ]
    tenant_col = getattr(related, "tenant_id", None)
    if isinstance(tenant_col, InstrumentedAttribute):
        criteria.append(tenant_col == tenant_id)
    deleted_col = getattr(related, "deleted_at", None)
    if isinstance(deleted_col, InstrumentedAttribute):
        criteria.append(deleted_col.is_(None))
    for name, value in spec.equals:
        criteria.append(mapped_column(related, name) == value)
    for name in spec.null_keys:
        criteria.append(mapped_column(related, name).is_(None))
    return exists(select(literal(1)).select_from(related).where(*criteria))


def search_clause(
    model: type[Any],
    *,
    tenant_id: UUID,
    search: str,
    fields: frozenset[str],
    related: Sequence[RelatedSearch] = (),
) -> ColumnElement[bool]:
    """OR of own-column ILIKE matches and related EXISTS clauses."""

    if not fields and not related:
        msg = "search is not supported by this repository"
        raise ValueError(msg)
    pattern = ilike_pattern(search)
    clauses: list[ColumnElement[bool]] = [
        column_ilike(mapped_column(model, field), pattern) for field in fields
    ]
    clauses.extend(
        related_exists(spec, parent=model, tenant_id=tenant_id, pattern=pattern)
        for spec in related
    )
    return or_(*clauses)


ADDRESS_FIELDS = frozenset(
    {
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "country",
        "country_code",
        "postal_code",
    }
)
USER_FIELDS = frozenset({"name", "email", "phone"})


def address_search(local_key: str) -> RelatedSearch:
    from app.identity.models import Address

    return RelatedSearch(Address, local_key=local_key, fields=ADDRESS_FIELDS)


def branch_search(local_key: str = "branch_id") -> RelatedSearch:
    from app.identity.models import Branch

    return RelatedSearch(Branch, local_key=local_key, fields=frozenset({"name", "code", "phone"}))


def user_search(local_key: str) -> RelatedSearch:
    from app.identity.models import User

    return RelatedSearch(User, local_key=local_key, fields=USER_FIELDS)
