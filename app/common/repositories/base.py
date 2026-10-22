"""Generic async repository primitives for soft-deletable models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy import false as sql_false
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.search import RelatedSearch, search_clause, validate_related_search
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.time import utcnow
from app.core.exceptions import ValidationError
from app.db.base import SoftDeleteModel


class BaseRepository[ModelT: SoftDeleteModel]:
    _immutable_fields = frozenset({"id", "created_at", "updated_at", "deleted_at"})

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        *,
        allowed_sort_fields: frozenset[str],
        allowed_filter_fields: frozenset[str] = frozenset(),
        search_fields: frozenset[str] = frozenset(),
        related_searches: Sequence[RelatedSearch] = (),
    ) -> None:
        self.session = session
        self.model = model
        self.allowed_sort_fields = allowed_sort_fields
        self.allowed_filter_fields = allowed_filter_fields
        self.search_fields = search_fields
        self.related_searches = tuple(related_searches)

        self._column("id")
        self._column("deleted_at")
        for field in allowed_sort_fields | allowed_filter_fields | search_fields:
            self._column(field)
        for spec in self.related_searches:
            validate_related_search(spec, model)

    def _column(self, name: str) -> InstrumentedAttribute[Any]:
        column = getattr(self.model, name, None)
        if not isinstance(column, InstrumentedAttribute):
            msg = f"{self.model.__name__} has no mapped column {name!r}"
            raise TypeError(msg)
        return column

    @staticmethod
    def _set_attribute(entity: ModelT, name: str, value: object) -> None:
        setattr(entity, name, value)

    def _criteria(
        self,
        *,
        filters: Mapping[str, object] | None = None,
        common_filter: BaseFilter | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [self._column("deleted_at").is_(None)]

        if filters:
            unknown = filters.keys() - self.allowed_filter_fields
            if unknown:
                fields = ", ".join(sorted(unknown))
                msg = f"filter fields are not allowed: {fields}"
                raise ValueError(msg)
            criteria.extend(self._filter_clause(name, value) for name, value in filters.items())

        if extra_criteria:
            criteria.extend(extra_criteria)

        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(self._column("created_at") >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(self._column("created_at") <= common_filter.date_to)
            if common_filter.search is not None:
                criteria.append(
                    search_clause(
                        self.model,
                        tenant_id=UUID(int=0),
                        search=common_filter.search,
                        fields=self.search_fields,
                        related=self.related_searches,
                    )
                )

        return criteria

    def _filter_clause(self, name: str, value: object) -> ColumnElement[bool]:
        column = self._column(name)
        if isinstance(value, (list, tuple, set, frozenset)):
            if not value:
                return sql_false()
            return column.in_(value)
        return column == value

    def base_query(self) -> Select[tuple[ModelT]]:
        return select(self.model).where(*self._criteria())

    async def get(self, entity_id: UUID) -> ModelT | None:
        statement = self.base_query().where(self._column("id") == entity_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        criteria = self._criteria(
            filters=filters,
            common_filter=common_filter,
            extra_criteria=extra_criteria,
        )
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in self.allowed_sort_fields:
            allowed = ", ".join(sorted(self.allowed_sort_fields))
            raise ValidationError(f"sort_by must be one of: {allowed}")

        sort_column = self._column(sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        statement = (
            select(self.model)
            .where(*criteria)
            .order_by(ordering)
            .offset(page.offset)
            .limit(page.page_size)
        )
        count_statement = select(func.count()).select_from(self.model).where(*criteria)

        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def create(self, values: Mapping[str, object]) -> ModelT:
        entity = self.model()
        for name, value in values.items():
            if name in self._immutable_fields:
                msg = f"field cannot be set during create: {name}"
                raise ValueError(msg)
            self._column(name)
            self._set_attribute(entity, name, value)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity_id: UUID, values: Mapping[str, object]) -> ModelT | None:
        entity = await self.get(entity_id)
        if entity is None:
            return None
        for name, value in values.items():
            if name in self._immutable_fields:
                msg = f"field cannot be updated: {name}"
                raise ValueError(msg)
            self._column(name)
            self._set_attribute(entity, name, value)
        await self.session.flush()
        await self.session.refresh(entity, attribute_names=["updated_at"])
        return entity

    async def soft_delete(self, entity_id: UUID) -> ModelT | None:
        entity = await self.get(entity_id)
        if entity is None:
            return None
        self._set_attribute(entity, "deleted_at", utcnow())
        await self.session.flush()
        return entity
