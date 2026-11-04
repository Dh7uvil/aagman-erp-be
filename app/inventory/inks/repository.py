"""Ink inventory data access."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.repositories.search import RelatedSearch
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import MaterialMovementDirection
from app.core.exceptions import ValidationError
from app.identity.models import Company
from app.inventory.inks.models import InkBrand, InkColor, InkLine, InkMovement, InkSheet


class InkColorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            InkColor,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, color_id: UUID) -> InkColor | None:
        return await self._repo.get(color_id)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[InkColor], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> InkColor:
        return await self._repo.create(values)

    async def update(self, color_id: UUID, values: Mapping[str, object]) -> InkColor | None:
        return await self._repo.update(color_id, values)

    async def soft_delete(self, color_id: UUID) -> InkColor | None:
        return await self._repo.soft_delete(color_id)

    async def count_lines(self, color_id: UUID) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(InkLine)
            .where(InkLine.color_id == color_id, InkLine.deleted_at.is_(None))
        )
        return int(result or 0)


class InkBrandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            InkBrand,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, brand_id: UUID) -> InkBrand | None:
        return await self._repo.get(brand_id)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[InkBrand], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> InkBrand:
        return await self._repo.create(values)

    async def update(self, brand_id: UUID, values: Mapping[str, object]) -> InkBrand | None:
        return await self._repo.update(brand_id, values)

    async def soft_delete(self, brand_id: UUID) -> InkBrand | None:
        return await self._repo.soft_delete(brand_id)

    async def count_lines(self, brand_id: UUID) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(InkLine)
            .where(InkLine.brand_id == brand_id, InkLine.deleted_at.is_(None))
        )
        return int(result or 0)


class InkSheetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            InkSheet,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"company_id"}),
            search_fields=frozenset(),
            related_searches=(
                RelatedSearch(model=Company, local_key="company_id", fields=frozenset({"name"})),
            ),
        )

    async def get(self, sheet_id: UUID) -> InkSheet | None:
        return await self._repo.get(sheet_id)

    async def get_by_company(self, company_id: UUID) -> InkSheet | None:
        result = await self.session.execute(
            select(InkSheet).where(
                InkSheet.company_id == company_id,
                InkSheet.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[InkSheet], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> InkSheet:
        return await self._repo.create(values)

    async def update(self, sheet_id: UUID, values: Mapping[str, object]) -> InkSheet | None:
        return await self._repo.update(sheet_id, values)

    async def soft_delete(self, sheet_id: UUID) -> InkSheet | None:
        return await self._repo.soft_delete(sheet_id)


class InkLineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            InkLine,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"ink_sheet_id", "color_id", "brand_id"}),
            search_fields=frozenset(),
        )

    async def get(self, line_id: UUID) -> InkLine | None:
        return await self._repo.get(line_id)

    async def list_for_sheet(self, sheet_id: UUID) -> list[InkLine]:
        result = await self.session.execute(
            select(InkLine)
            .where(InkLine.ink_sheet_id == sheet_id, InkLine.deleted_at.is_(None))
            .order_by(InkLine.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_color(self, color_id: UUID) -> list[InkLine]:
        result = await self.session.execute(
            select(InkLine).where(InkLine.color_id == color_id, InkLine.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def create(self, values: Mapping[str, object]) -> InkLine:
        return await self._repo.create(values)

    async def update(self, line_id: UUID, values: Mapping[str, object]) -> InkLine | None:
        return await self._repo.update(line_id, values)

    async def soft_delete(self, line_id: UUID) -> InkLine | None:
        return await self._repo.soft_delete(line_id)

    async def list_active_lines(self) -> list[InkLine]:
        result = await self.session.execute(
            select(InkLine).where(InkLine.deleted_at.is_(None)).order_by(InkLine.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_inventory(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
    ) -> tuple[list[InkLine], int]:
        allowed_sort = frozenset({"created_at", "updated_at"})
        sort_by = common_filter.sort_by if common_filter and common_filter.sort_by else "created_at"
        sort_order = common_filter.sort_order if common_filter and common_filter.sort_order else "desc"
        if sort_by not in allowed_sort:
            allowed = ", ".join(sorted(allowed_sort))
            raise ValidationError(f"sort_by must be one of: {allowed}")

        criteria = [
            InkLine.deleted_at.is_(None),
            InkSheet.deleted_at.is_(None),
        ]
        stmt = select(InkLine).join(InkSheet, InkLine.ink_sheet_id == InkSheet.id)
        if company_id is not None:
            criteria.append(InkSheet.company_id == company_id)
        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(InkLine.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(InkLine.created_at <= common_filter.date_to)
            if common_filter.search:
                term = f"%{common_filter.search.strip()}%"
                stmt = (
                    stmt.join(Company, InkSheet.company_id == Company.id)
                    .join(InkBrand, InkLine.brand_id == InkBrand.id)
                    .join(InkColor, InkLine.color_id == InkColor.id)
                )
                criteria.append(
                    or_(
                        Company.name.ilike(term),
                        InkBrand.name.ilike(term),
                        InkColor.name.ilike(term),
                    )
                )

        stmt = stmt.where(and_(*criteria))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.session.scalar(count_stmt)) or 0)

        sort_column = getattr(InkLine, sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        offset = (page.page - 1) * page.page_size
        result = await self.session.execute(
            stmt.order_by(ordering).offset(offset).limit(page.page_size)
        )
        return list(result.scalars().all()), total


class InkMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            InkMovement,
            allowed_sort_fields=frozenset({"created_at", "movement_date"}),
            allowed_filter_fields=frozenset({"movement_date", "ink_line_id"}),
            search_fields=frozenset(),
        )

    async def create(self, values: Mapping[str, object]) -> InkMovement:
        return await self._repo.create(values)

    async def day_totals(self, movement_date: date) -> dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]]:
        rows = await self.session.execute(
            select(
                InkMovement.ink_line_id,
                InkMovement.direction,
                func.coalesce(func.sum(InkMovement.drums), 0),
                func.coalesce(func.sum(InkMovement.quantity), 0),
            )
            .where(
                InkMovement.movement_date == movement_date,
                InkMovement.deleted_at.is_(None),
                InkMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(InkMovement.ink_line_id, InkMovement.direction)
        )
        result: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        for line_id, direction, sum_drums, sum_qty in rows.all():
            current = result.get(line_id, (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")))
            in_d, in_q, out_d, out_q = current
            if direction == MaterialMovementDirection.IN.value:
                in_d += Decimal(sum_drums)
                in_q += Decimal(sum_qty)
            else:
                out_d += Decimal(sum_drums)
                out_q += Decimal(sum_qty)
            result[line_id] = (in_d, in_q, out_d, out_q)
        return result

    async def sum_through_date(self, line_id: UUID, through_date: date) -> tuple[Decimal, Decimal]:
        rows = await self.session.execute(
            select(InkMovement.direction, InkMovement.drums, InkMovement.quantity).where(
                InkMovement.ink_line_id == line_id,
                InkMovement.deleted_at.is_(None),
                InkMovement.movement_date <= through_date,
            )
        )
        drums = Decimal("0")
        qty = Decimal("0")
        for direction, row_drums, row_qty in rows.all():
            sign = Decimal("-1") if direction == MaterialMovementDirection.OUT.value else Decimal("1")
            drums += sign * Decimal(row_drums)
            qty += sign * Decimal(row_qty)
        return drums, qty

    async def line_ids_with_activity_on(self, movement_date: date) -> set[UUID]:
        rows = await self.session.execute(
            select(InkMovement.ink_line_id)
            .where(
                InkMovement.movement_date == movement_date,
                InkMovement.deleted_at.is_(None),
                InkMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .distinct()
        )
        return {row[0] for row in rows.all()}
