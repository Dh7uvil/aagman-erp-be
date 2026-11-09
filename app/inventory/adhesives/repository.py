"""Adhesive inventory data access."""

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
from app.inventory.adhesives.models import AdhesiveBrand, AdhesiveCode, AdhesiveLine, AdhesiveMovement, AdhesiveSheet
from app.inventory.pricing import PurchasePriceStats


class AdhesiveCodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            AdhesiveCode,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "code"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"code"}),
        )

    async def get(self, adhesive_code_id: UUID) -> AdhesiveCode | None:
        return await self._repo.get(adhesive_code_id)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[AdhesiveCode], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> AdhesiveCode:
        return await self._repo.create(values)

    async def update(self, adhesive_code_id: UUID, values: Mapping[str, object]) -> AdhesiveCode | None:
        return await self._repo.update(adhesive_code_id, values)

    async def soft_delete(self, adhesive_code_id: UUID) -> AdhesiveCode | None:
        return await self._repo.soft_delete(adhesive_code_id)

    async def count_lines(self, adhesive_code_id: UUID) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(AdhesiveLine)
            .where(AdhesiveLine.adhesive_code_id == adhesive_code_id, AdhesiveLine.deleted_at.is_(None))
        )
        return int(result or 0)


class AdhesiveBrandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            AdhesiveBrand,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, brand_id: UUID) -> AdhesiveBrand | None:
        return await self._repo.get(brand_id)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[AdhesiveBrand], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> AdhesiveBrand:
        return await self._repo.create(values)

    async def update(self, brand_id: UUID, values: Mapping[str, object]) -> AdhesiveBrand | None:
        return await self._repo.update(brand_id, values)

    async def soft_delete(self, brand_id: UUID) -> AdhesiveBrand | None:
        return await self._repo.soft_delete(brand_id)

    async def count_lines(self, brand_id: UUID) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(AdhesiveLine)
            .where(AdhesiveLine.brand_id == brand_id, AdhesiveLine.deleted_at.is_(None))
        )
        return int(result or 0)


class AdhesiveSheetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            AdhesiveSheet,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"company_id"}),
            search_fields=frozenset(),
            related_searches=(
                RelatedSearch(model=Company, local_key="company_id", fields=frozenset({"name"})),
            ),
        )

    async def get(self, sheet_id: UUID) -> AdhesiveSheet | None:
        return await self._repo.get(sheet_id)

    async def get_by_company(self, company_id: UUID) -> AdhesiveSheet | None:
        result = await self.session.execute(
            select(AdhesiveSheet).where(
                AdhesiveSheet.company_id == company_id,
                AdhesiveSheet.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[AdhesiveSheet], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> AdhesiveSheet:
        return await self._repo.create(values)

    async def update(self, sheet_id: UUID, values: Mapping[str, object]) -> AdhesiveSheet | None:
        return await self._repo.update(sheet_id, values)

    async def soft_delete(self, sheet_id: UUID) -> AdhesiveSheet | None:
        return await self._repo.soft_delete(sheet_id)


class AdhesiveLineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            AdhesiveLine,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"adhesive_sheet_id", "adhesive_code_id", "brand_id"}),
            search_fields=frozenset(),
        )

    async def get(self, line_id: UUID) -> AdhesiveLine | None:
        return await self._repo.get(line_id)

    async def list_for_sheet(self, sheet_id: UUID) -> list[AdhesiveLine]:
        result = await self.session.execute(
            select(AdhesiveLine)
            .where(AdhesiveLine.adhesive_sheet_id == sheet_id, AdhesiveLine.deleted_at.is_(None))
            .order_by(AdhesiveLine.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_code(self, adhesive_code_id: UUID) -> list[AdhesiveLine]:
        result = await self.session.execute(
            select(AdhesiveLine).where(AdhesiveLine.adhesive_code_id == adhesive_code_id, AdhesiveLine.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def create(self, values: Mapping[str, object]) -> AdhesiveLine:
        return await self._repo.create(values)

    async def update(self, line_id: UUID, values: Mapping[str, object]) -> AdhesiveLine | None:
        return await self._repo.update(line_id, values)

    async def soft_delete(self, line_id: UUID) -> AdhesiveLine | None:
        return await self._repo.soft_delete(line_id)

    async def list_active_lines(self) -> list[AdhesiveLine]:
        result = await self.session.execute(
            select(AdhesiveLine).where(AdhesiveLine.deleted_at.is_(None)).order_by(AdhesiveLine.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_inventory(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
    ) -> tuple[list[AdhesiveLine], int]:
        allowed_sort = frozenset({"created_at", "updated_at"})
        sort_by = common_filter.sort_by if common_filter and common_filter.sort_by else "created_at"
        sort_order = common_filter.sort_order if common_filter and common_filter.sort_order else "desc"
        if sort_by not in allowed_sort:
            allowed = ", ".join(sorted(allowed_sort))
            raise ValidationError(f"sort_by must be one of: {allowed}")

        criteria = [
            AdhesiveLine.deleted_at.is_(None),
            AdhesiveSheet.deleted_at.is_(None),
        ]
        stmt = select(AdhesiveLine).join(AdhesiveSheet, AdhesiveLine.adhesive_sheet_id == AdhesiveSheet.id)
        if company_id is not None:
            criteria.append(AdhesiveSheet.company_id == company_id)
        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(AdhesiveLine.created_at >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(AdhesiveLine.created_at <= common_filter.date_to)
            if common_filter.search:
                term = f"%{common_filter.search.strip()}%"
                stmt = (
                    stmt.join(Company, AdhesiveSheet.company_id == Company.id)
                    .join(AdhesiveBrand, AdhesiveLine.brand_id == AdhesiveBrand.id)
                    .join(AdhesiveCode, AdhesiveLine.adhesive_code_id == AdhesiveCode.id)
                )
                criteria.append(
                    or_(
                        Company.name.ilike(term),
                        AdhesiveBrand.name.ilike(term),
                        AdhesiveCode.code.ilike(term),
                    )
                )

        stmt = stmt.where(and_(*criteria))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.session.scalar(count_stmt)) or 0)

        sort_column = getattr(AdhesiveLine, sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        offset = (page.page - 1) * page.page_size
        result = await self.session.execute(
            stmt.order_by(ordering).offset(offset).limit(page.page_size)
        )
        return list(result.scalars().all()), total


class AdhesiveMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            AdhesiveMovement,
            allowed_sort_fields=frozenset({"created_at", "movement_date"}),
            allowed_filter_fields=frozenset({"movement_date", "adhesive_line_id"}),
            search_fields=frozenset(),
        )

    async def create(self, values: Mapping[str, object]) -> AdhesiveMovement:
        return await self._repo.create(values)

    async def list_for_line(
        self,
        line_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[AdhesiveMovement], int]:
        criteria = (
            AdhesiveMovement.adhesive_line_id == line_id,
            AdhesiveMovement.deleted_at.is_(None),
            AdhesiveMovement.direction.in_(
                (
                    MaterialMovementDirection.IN.value,
                    MaterialMovementDirection.OUT.value,
                    MaterialMovementDirection.OPENING.value,
                )
            ),
        )
        total = await self.session.scalar(
            select(func.count()).select_from(AdhesiveMovement).where(*criteria),
        )
        offset = (page.page - 1) * page.page_size
        result = await self.session.execute(
            select(AdhesiveMovement)
            .where(*criteria)
            .order_by(AdhesiveMovement.created_at.desc())
            .offset(offset)
            .limit(page.page_size)
        )
        return list(result.scalars().all()), int(total or 0)

    async def purchase_price_stats_by_line_ids(
        self,
        line_ids: Sequence[UUID],
    ) -> dict[UUID, PurchasePriceStats]:
        unique = list(dict.fromkeys(line_ids))
        if not unique:
            return {}
        rows = await self.session.execute(
            select(
                AdhesiveMovement.adhesive_line_id,
                func.count(),
                func.coalesce(func.sum(AdhesiveMovement.quantity), 0),
                func.coalesce(
                    func.sum(AdhesiveMovement.quantity * AdhesiveMovement.adhesive_rate),
                    0,
                ),
                func.coalesce(func.sum(AdhesiveMovement.adhesive_rate), 0),
            ).where(
                AdhesiveMovement.adhesive_line_id.in_(unique),
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OPENING.value,
                    )
                ),
                AdhesiveMovement.adhesive_rate.is_not(None),
            ).group_by(AdhesiveMovement.adhesive_line_id)
        )
        return {
            line_id: PurchasePriceStats(
                priced_count=int(count),
                sum_kg=Decimal(sum_kg or 0),
                sum_kg_price=Decimal(sum_kg_price or 0),
                sum_price=Decimal(sum_price or 0),
            )
            for line_id, count, sum_kg, sum_kg_price, sum_price in rows.all()
        }

    async def last_stock_in(self, line_id: UUID) -> AdhesiveMovement | None:
        result = await self.session.execute(
            select(AdhesiveMovement)
            .where(
                AdhesiveMovement.adhesive_line_id == line_id,
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.direction == MaterialMovementDirection.IN.value,
            )
            .order_by(AdhesiveMovement.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def day_totals(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]]:
        rows = await self.session.execute(
            select(
                AdhesiveMovement.adhesive_line_id,
                AdhesiveMovement.direction,
                func.coalesce(func.sum(AdhesiveMovement.drums), 0),
                func.coalesce(func.sum(AdhesiveMovement.quantity), 0),
            )
            .where(
                AdhesiveMovement.movement_date >= start_date,
                AdhesiveMovement.movement_date <= end_date,
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OPENING.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(AdhesiveMovement.adhesive_line_id, AdhesiveMovement.direction)
        )
        result: dict[UUID, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
        for line_id, direction, sum_drums, sum_qty in rows.all():
            current = result.get(line_id, (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")))
            in_d, in_q, out_d, out_q = current
            if direction in (
                MaterialMovementDirection.IN.value,
                MaterialMovementDirection.OPENING.value,
            ):
                in_d += Decimal(sum_drums)
                in_q += Decimal(sum_qty)
            else:
                out_d += Decimal(sum_drums)
                out_q += Decimal(sum_qty)
            result[line_id] = (in_d, in_q, out_d, out_q)
        return result

    async def sum_through_date(self, line_id: UUID, through_date: date) -> tuple[Decimal, Decimal]:
        rows = await self.session.execute(
            select(AdhesiveMovement.direction, AdhesiveMovement.drums, AdhesiveMovement.quantity).where(
                AdhesiveMovement.adhesive_line_id == line_id,
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.movement_date <= through_date,
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
            select(AdhesiveMovement.adhesive_line_id)
            .where(
                AdhesiveMovement.movement_date == movement_date,
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .distinct()
        )
        return {row[0] for row in rows.all()}
