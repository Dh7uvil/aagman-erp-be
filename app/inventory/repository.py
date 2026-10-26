"""Inventory data access."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import MaterialCategoryKind, MaterialMovementDirection
from app.inventory.models import InventoryUnit, MaterialCategory, MaterialMovement


class UnitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            InventoryUnit,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"code", "name"}),
        )

    async def get(self, unit_id: UUID) -> InventoryUnit | None:
        return await self._repo.get(unit_id)

    async def get_by_code(self, code: str) -> InventoryUnit | None:
        result = await self.session.execute(
            select(InventoryUnit).where(
                InventoryUnit.code == code,
                InventoryUnit.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[InventoryUnit], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> InventoryUnit:
        return await self._repo.create(values)

    async def update(self, unit_id: UUID, values: Mapping[str, object]) -> InventoryUnit | None:
        return await self._repo.update(unit_id, values)

    async def soft_delete(self, unit_id: UUID) -> InventoryUnit | None:
        return await self._repo.soft_delete(unit_id)


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            MaterialCategory,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "size"}),
            allowed_filter_fields=frozenset({"is_active", "parent_id", "category_kind"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, category_id: UUID) -> MaterialCategory | None:
        return await self._repo.get(category_id)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[MaterialCategory], int]:
        return await self._repo.list(
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def create(self, values: Mapping[str, object]) -> MaterialCategory:
        return await self._repo.create(values)

    async def update(self, category_id: UUID, values: Mapping[str, object]) -> MaterialCategory | None:
        return await self._repo.update(category_id, values)

    async def soft_delete(self, category_id: UUID) -> MaterialCategory | None:
        return await self._repo.soft_delete(category_id)

    async def count_active_children(
        self,
        parent_id: UUID,
        *,
        category_kind: MaterialCategoryKind | None = None,
    ) -> int:
        criteria = [
            MaterialCategory.parent_id == parent_id,
            MaterialCategory.deleted_at.is_(None),
        ]
        if category_kind is not None:
            criteria.append(MaterialCategory.category_kind == category_kind.value)
        total = await self.session.scalar(select(func.count()).select_from(MaterialCategory).where(*criteria))
        return int(total or 0)

    async def micron_ids_for_product(self, product_id: UUID) -> list[UUID]:
        result = await self.session.execute(
            select(MaterialCategory.id).where(
                MaterialCategory.parent_id == product_id,
                MaterialCategory.category_kind == MaterialCategoryKind.MICRON.value,
                MaterialCategory.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_ids(self, ids: Sequence[UUID]) -> dict[UUID, MaterialCategory]:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return {}
        result = await self.session.execute(
            select(MaterialCategory).where(
                MaterialCategory.id.in_(unique),
                MaterialCategory.deleted_at.is_(None),
            )
        )
        return {row.id: row for row in result.scalars().all()}

    async def list_active_skus(self) -> Sequence[MaterialCategory]:
        result = await self.session.execute(
            select(MaterialCategory)
            .where(
                MaterialCategory.category_kind == MaterialCategoryKind.SKU.value,
                MaterialCategory.deleted_at.is_(None),
                MaterialCategory.is_active.is_(True),
            )
            .order_by(MaterialCategory.name)
        )
        return result.scalars().all()


class UnitLookupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_units_by_ids(self, ids: Sequence[UUID]) -> dict[UUID, InventoryUnit]:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return {}
        result = await self.session.execute(
            select(InventoryUnit).where(
                InventoryUnit.id.in_(unique),
                InventoryUnit.deleted_at.is_(None),
            )
        )
        return {row.id: row for row in result.scalars().all()}


class MovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            MaterialMovement,
            allowed_sort_fields=frozenset({"created_at", "movement_date"}),
            allowed_filter_fields=frozenset({"movement_date", "category_id"}),
            search_fields=frozenset(),
        )

    async def get(self, movement_id: UUID) -> MaterialMovement | None:
        return await self._repo.get(movement_id)

    async def list_for_date(
        self,
        *,
        movement_date: date,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[Sequence[MaterialMovement], int]:
        criteria = [
            MaterialMovement.movement_date == movement_date,
            MaterialMovement.direction.in_(
                (
                    MaterialMovementDirection.IN.value,
                    MaterialMovementDirection.OUT.value,
                )
            ),
        ]
        return await self._repo.list(
            page=page,
            common_filter=common_filter,
            extra_criteria=criteria,
        )

    async def create(self, values: Mapping[str, object]) -> MaterialMovement:
        return await self._repo.create(values)

    async def soft_delete(self, movement_id: UUID) -> MaterialMovement | None:
        return await self._repo.soft_delete(movement_id)

    async def sum_through_date(
        self,
        category_id: UUID,
        through_date: date,
    ) -> tuple[Decimal, Decimal]:
        rows = await self.session.execute(
            select(MaterialMovement.direction, MaterialMovement.rolls, MaterialMovement.kilograms)
            .where(
                MaterialMovement.category_id == category_id,
                MaterialMovement.deleted_at.is_(None),
                MaterialMovement.movement_date <= through_date,
            )
        )
        rolls = Decimal("0")
        kg = Decimal("0")
        for direction, row_rolls, row_kg in rows.all():
            sign = Decimal("-1") if direction == MaterialMovementDirection.OUT.value else Decimal("1")
            rolls += sign * Decimal(row_rolls)
            kg += sign * Decimal(row_kg)
        return rolls, kg

    async def day_totals(
        self,
        movement_date: date,
    ) -> dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]]:
        rows = await self.session.execute(
            select(
                MaterialMovement.category_id,
                MaterialMovement.direction,
                func.coalesce(func.sum(MaterialMovement.rolls), 0),
                func.coalesce(func.sum(MaterialMovement.kilograms), 0),
            )
            .where(
                MaterialMovement.movement_date == movement_date,
                MaterialMovement.deleted_at.is_(None),
                MaterialMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(MaterialMovement.category_id, MaterialMovement.direction)
        )
        result: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        for category_id, direction, sum_rolls, sum_kg in rows.all():
            current = result.get(category_id, (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")))
            in_r, in_k, out_r, out_k = current
            if direction == MaterialMovementDirection.IN.value:
                in_r += Decimal(sum_rolls)
                in_k += Decimal(sum_kg)
            else:
                out_r += Decimal(sum_rolls)
                out_k += Decimal(sum_kg)
            result[category_id] = (in_r, in_k, out_r, out_k)
        return result

    async def category_ids_with_activity_on(self, movement_date: date) -> set[UUID]:
        rows = await self.session.execute(
            select(MaterialMovement.category_id)
            .where(
                MaterialMovement.movement_date == movement_date,
                MaterialMovement.deleted_at.is_(None),
                MaterialMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .distinct()
        )
        return {row[0] for row in rows.all()}
