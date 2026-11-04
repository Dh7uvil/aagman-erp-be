"""Solvent inventory business logic."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter, audit_field_changes, jsonable_value
from app.common.services.entity_history import EntityHistoryEntry, EntityHistoryService
from app.common.utils.files import (
    MIME_JPEG,
    MIME_PDF,
    MIME_PNG,
    MIME_WEBP,
    validate_upload,
)
from app.core.enums import AuditAction, INVENTORY_MODULE, MaterialMovementDirection
from app.core.exceptions import (
    DuplicateResourceError,
    InsufficientStockError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.identity.models import Company, User
from app.identity.schemas import AuditLogUserSummary
from app.inventory.catalog import SOLVENT_VIEW_PRICE
from app.inventory.solvents.models import SolventBrand, SolventName, SolventLine, SolventMovement, SolventSheet
from app.inventory.solvents.repository import (
    SolventBrandRepository,
    SolventNameRepository,
    SolventLineRepository,
    SolventMovementRepository,
    SolventSheetRepository,
)
from app.inventory.solvents.schemas import (
    SolventBrandCreate,
    SolventBrandResponse,
    SolventBrandUpdate,
    SolventNameCreate,
    SolventNameResponse,
    SolventNameUpdate,
    SolventNameUsageLine,
    SolventNameUsageResponse,
    SolventDayReportRow,
    SolventLineResponse,
    SolventLineUpsert,
    SolventSheetCreate,
    SolventLineListItem,
    SolventSheetListItem,
    SolventSheetResponse,
    SolventSheetUpdate,
    SolventStockOutCreate,
)
from app.inventory.models import InventoryUnit
from app.inventory.pricing import compute_avg_price
from app.inventory.repository import UnitRepository
from app.inventory.schemas import DrumLineHistoryEntry, DrumLineHistorySummary

class SolventService:
    _DISPLAY_SCALE = Decimal("0.01")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.names = SolventNameRepository(session)
        self.brands = SolventBrandRepository(session)
        self.sheets = SolventSheetRepository(session)
        self.lines = SolventLineRepository(session)
        self.movements = SolventMovementRepository(session)
        self.units = UnitRepository(session)
        self.audit = AuditWriter(session)
        self.history = EntityHistoryService(session)

    @classmethod
    def _display_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(cls._DISPLAY_SCALE, rounding=ROUND_HALF_UP)

    @staticmethod
    def _can_view_price(permissions: frozenset[str]) -> bool:
        return has_permission(permissions, SOLVENT_VIEW_PRICE)

    async def _require_company(self, company_id: UUID) -> Company:
        result = await self.session.execute(
            select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError("Company not found")
        return row

    async def _default_kg_unit_id(self) -> UUID:
        unit = await self.units.get_by_code("kg")
        if unit is None:
            raise ValidationError("Default kg unit is not configured")
        return unit.id

    @staticmethod
    def _line_totals(drum_count: Decimal, drum_qty: Decimal, solvent_rate: Decimal | None) -> tuple[Decimal, Decimal | None]:
        total_qty = drum_count * drum_qty
        total_rate = (total_qty * solvent_rate) if solvent_rate is not None else None
        return total_qty, total_rate

    async def _load_unit_codes(self, unit_ids: list[UUID]) -> dict[UUID, InventoryUnit]:
        unique = list(dict.fromkeys(unit_ids))
        if not unique:
            return {}
        result = await self.session.execute(
            select(InventoryUnit).where(
                InventoryUnit.id.in_(unique),
                InventoryUnit.deleted_at.is_(None),
            )
        )
        return {row.id: row for row in result.scalars().all()}

    async def _avg_prices_by_line_ids(
        self,
        line_ids: list[UUID],
    ) -> dict[UUID, Decimal | None]:
        unique = list(dict.fromkeys(line_ids))
        if not unique:
            return {}
        stats_map = await self.movements.purchase_price_stats_by_line_ids(unique)
        return {
            line_id: self._display_decimal(compute_avg_price(stats_map.get(line_id)))
            for line_id in unique
        }

    async def _line_response(
        self,
        line: SolventLine,
        *,
        can_view_price: bool,
        avg_prices: Mapping[UUID, Decimal | None] | None = None,
    ) -> SolventLineResponse:
        brand = await self.brands.get(line.brand_id)
        name_row = await self.names.get(line.solvent_name_id)
        units = await self._load_unit_codes([line.drum_unit_id])
        unit = units.get(line.drum_unit_id)
        unit_code = unit.code if unit else ""
        solvent_rate = self._display_decimal(line.solvent_rate) if can_view_price else None
        total_rate = self._display_decimal(line.total_rate) if can_view_price else None
        avg_price: Decimal | None = None
        if can_view_price:
            if avg_prices is not None:
                avg_price = avg_prices.get(line.id)
            else:
                avg_map = await self._avg_prices_by_line_ids([line.id])
                avg_price = avg_map.get(line.id)
        return SolventLineResponse(
            id=line.id,
            brand_id=line.brand_id,
            brand_name=brand.name if brand else "",
            solvent_name_id=line.solvent_name_id,
            name=name_row.name if name_row else "",
            drum_count=self._display_decimal(line.drum_count) or Decimal("0"),
            drum_qty=self._display_decimal(line.drum_qty) or Decimal("0"),
            drum_unit_id=line.drum_unit_id,
            drum_unit_code=unit_code,
            total_qty=self._display_decimal(line.total_qty) or Decimal("0"),
            solvent_rate=solvent_rate,
            total_rate=total_rate,
            avg_price_per_unit=avg_price,
            price_unit_code=unit_code if avg_price is not None else None,
            created_at=line.created_at,
            updated_at=line.updated_at,
        )

    async def _line_responses(
        self,
        line_rows: list[SolventLine],
        *,
        can_view_price: bool,
    ) -> list[SolventLineResponse]:
        avg_map: dict[UUID, Decimal | None] = {}
        if can_view_price and line_rows:
            avg_map = await self._avg_prices_by_line_ids([row.id for row in line_rows])
        return [
            await self._line_response(row, can_view_price=can_view_price, avg_prices=avg_map)
            for row in line_rows
        ]

    async def _sheet_response(self, sheet: SolventSheet, *, can_view_price: bool) -> SolventSheetResponse:
        company = await self._require_company(sheet.company_id)
        line_rows = await self.lines.list_for_sheet(sheet.id)
        lines = await self._line_responses(line_rows, can_view_price=can_view_price)
        return SolventSheetResponse(
            id=sheet.id,
            company_id=sheet.company_id,
            company_name=company.name,
            lines=lines,
            created_at=sheet.created_at,
            updated_at=sheet.updated_at,
        )

    # Colors

    async def list_codes(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        is_active: bool | None,
    ) -> tuple[list[SolventNameResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.names.list(page=page, common_filter=common_filter, filters=filters or None)
        return [SolventNameResponse.model_validate(row) for row in rows], total

    async def get_code(self, solvent_name_id: UUID) -> SolventNameResponse:
        row = await self.names.get(solvent_name_id)
        if row is None:
            raise ResourceNotFoundError("Solvent name not found")
        return SolventNameResponse.model_validate(row)

    @staticmethod
    def _name_snapshot(row: SolventName) -> dict[str, object]:
        return {
            "name": row.name,
            "is_active": row.is_active,
        }

    async def _sheet_audit_snapshot(self, sheet: SolventSheet) -> dict[str, object]:
        company = await self._require_company(sheet.company_id)
        line_rows = await self.lines.list_for_sheet(sheet.id)
        summaries: list[str] = []
        for line in line_rows:
            brand = await self.brands.get(line.brand_id)
            name_row = await self.names.get(line.solvent_name_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit_code = units.get(line.drum_unit_id)
            unit_code = unit_code.code if unit_code else ""
            brand_name = brand.name if brand else ""
            name_label = name_row.name if name_row else ""
            summaries.append(
                f"{brand_name} · {name_label}: "
                f"{jsonable_value(line.drum_count)} drums, "
                f"{jsonable_value(line.total_qty)} {unit_code}"
            )
        return {
            "company_name": company.name,
            "lines": summaries,
        }

    async def name_history(
        self,
        solvent_name_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        if await self.names.get(solvent_name_id) is None:
            raise ResourceNotFoundError("Solvent name not found")
        return await self.history.list_for_entity(
            entity_type="solvent_name",
            entity_id=solvent_name_id,
            page=page,
        )

    async def sheet_history(
        self,
        sheet_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        if await self.sheets.get(sheet_id) is None:
            raise ResourceNotFoundError("Solvent sheet not found")
        return await self.history.list_for_entity(
            entity_type="solvent_sheet",
            entity_id=sheet_id,
            page=page,
        )

    async def _line_history_context(
        self,
        line_id: UUID,
    ) -> tuple[SolventLine, SolventSheet, Company, str, str, str]:
        line = await self.lines.get(line_id)
        if line is None:
            raise ResourceNotFoundError("Solvent line not found")
        sheet = await self.sheets.get(line.solvent_sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Solvent sheet not found")
        company = await self._require_company(sheet.company_id)
        brand = await self.brands.get(line.brand_id)
        name_row = await self.names.get(line.solvent_name_id)
        units = await self._load_unit_codes([line.drum_unit_id])
        unit_code = units.get(line.drum_unit_id)
        return (
            line,
            sheet,
            company,
            brand.name if brand else "",
            name_row.name if name_row else "",
            unit_code.code if unit_code else "",
        )

    async def line_history(
        self,
        line_id: UUID,
        *,
        page: PageParams,
        permissions: frozenset[str],
    ) -> tuple[list[DrumLineHistoryEntry], int]:
        line, sheet, company, _brand, _code, unit_code = await self._line_history_context(line_id)
        can_view_price = self._can_view_price(permissions)
        movements, total = await self.movements.list_for_line(line_id, page=page)
        user_ids = [uid for uid in (m.created_by for m in movements) if uid is not None]
        users_by_id: dict[UUID, User] = {}
        for user_id in dict.fromkeys(user_ids):
            user = await self.session.get(User, user_id)
            if user is not None:
                users_by_id[user_id] = user

        entries: list[DrumLineHistoryEntry] = []
        for movement in movements:
            user = None
            if movement.created_by and movement.created_by in users_by_id:
                actor = users_by_id[movement.created_by]
                user = AuditLogUserSummary(id=actor.id, name=actor.name)
            rate = self._display_decimal(movement.solvent_rate) if can_view_price else None
            entries.append(
                DrumLineHistoryEntry(
                    id=movement.id,
                    timestamp=movement.created_at,
                    action=movement.direction,
                    user=user,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    drums=self._display_decimal(movement.drums),
                    quantity=self._display_decimal(movement.quantity),
                    quantity_unit_code=unit_code or None,
                    price_per_unit=rate,
                    price_unit_code=unit_code or None if rate is not None else None,
                    note=movement.note,
                ),
            )
        return entries, total

    async def line_history_summary(
        self,
        line_id: UUID,
        *,
        permissions: frozenset[str],
    ) -> DrumLineHistorySummary:
        line, sheet, company, brand_name, code, unit_code = await self._line_history_context(line_id)
        can_view_price = self._can_view_price(permissions)
        last_in = await self.movements.last_stock_in(line_id)
        last_price = None
        last_date = None
        last_drums = None
        price_unit_code = unit_code or None
        if last_in is not None:
            last_date = last_in.movement_date
            last_drums = self._display_decimal(last_in.drums)
            if can_view_price:
                last_price = self._display_decimal(last_in.solvent_rate)
        stats_map = await self.movements.purchase_price_stats_by_line_ids([line_id])
        avg_price = self._display_decimal(compute_avg_price(stats_map.get(line_id)))
        return DrumLineHistorySummary(
            line_id=line.id,
            sheet_id=sheet.id,
            company_id=company.id,
            company_name=company.name,
            brand_name=brand_name,
            line_label=code,
            drums_on_hand=self._display_decimal(line.drum_count) or Decimal("0"),
            total_qty=self._display_decimal(line.total_qty) or Decimal("0"),
            quantity_unit_code=unit_code,
            last_purchase_price=last_price,
            last_purchase_price_unit_code=price_unit_code if last_price is not None else None,
            last_purchase_date=last_date,
            last_purchase_drums=last_drums,
            avg_price_per_unit=avg_price if can_view_price else None,
            price_unit_code=price_unit_code if can_view_price and avg_price is not None else None,
        )

    async def create_code(
        self,
        payload: SolventNameCreate,
        *,
        actor_user_id: UUID,
    ) -> SolventNameResponse:
        async with transaction(self.session):
            try:
                row = await self.names.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("A solvent name with this name already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="solvent_name",
                entity_id=row.id,
                new_values=self._name_snapshot(row),
            )
            return SolventNameResponse.model_validate(row)

    async def update_code(
        self,
        solvent_name_id: UUID,
        payload: SolventNameUpdate,
        *,
        actor_user_id: UUID,
    ) -> SolventNameResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self.names.get(solvent_name_id)
            if existing is None:
                raise ResourceNotFoundError("Solvent name not found")
            old = self._name_snapshot(existing)
            try:
                updated = await self.names.update(solvent_name_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A solvent name with this name already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Solvent name not found")
            new = self._name_snapshot(updated)
            if audit_field_changes(old, new):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="solvent_name",
                    entity_id=updated.id,
                    old_values=old,
                    new_values=new,
                )
            return SolventNameResponse.model_validate(updated)

    async def delete_code(
        self,
        solvent_name_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> SolventNameResponse:
        async with transaction(self.session):
            if await self.names.count_lines(solvent_name_id) > 0:
                raise ValidationError("Cannot delete a name that is used on solvent lines")
            existing = await self.names.get(solvent_name_id)
            if existing is None:
                raise ResourceNotFoundError("Solvent name not found")
            deleted = await self.names.soft_delete(solvent_name_id)
            if deleted is None:
                raise ResourceNotFoundError("Solvent name not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="solvent_name",
                entity_id=existing.id,
                old_values=self._name_snapshot(existing),
            )
            return SolventNameResponse.model_validate(deleted)

    async def name_usage(self, solvent_name_id: UUID, *, permissions: frozenset[str]) -> SolventNameUsageResponse:
        name_row = await self.names.get(solvent_name_id)
        if name_row is None:
            raise ResourceNotFoundError("Solvent name not found")
        can_view_price = self._can_view_price(permissions)
        line_rows = await self.lines.list_for_code(solvent_name_id)
        avg_map = (
            await self._avg_prices_by_line_ids([line.id for line in line_rows])
            if can_view_price
            else {}
        )
        companies_with_stock: set[UUID] = set()
        usage_lines: list[SolventNameUsageLine] = []
        for line in line_rows:
            sheet = await self.sheets.get(line.solvent_sheet_id)
            if sheet is None:
                continue
            company = await self._require_company(sheet.company_id)
            brand = await self.brands.get(line.brand_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit = units.get(line.drum_unit_id)
            unit_code = unit.code if unit else ""
            drums = line.drum_count or Decimal("0")
            qty = line.total_qty or Decimal("0")
            if drums > 0 or qty > 0:
                companies_with_stock.add(sheet.company_id)
            avg_price = avg_map.get(line.id) if can_view_price else None
            usage_lines.append(
                SolventNameUsageLine(
                    solvent_line_id=line.id,
                    solvent_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    brand_id=line.brand_id,
                    brand_name=brand.name if brand else "",
                    drum_count=self._display_decimal(drums) or Decimal("0"),
                    drum_qty=self._display_decimal(line.drum_qty) or Decimal("0"),
                    drum_unit_code=unit_code,
                    total_qty=self._display_decimal(qty) or Decimal("0"),
                    solvent_rate=self._display_decimal(line.solvent_rate) if can_view_price else None,
                    total_rate=self._display_decimal(line.total_rate) if can_view_price else None,
                    avg_price_per_unit=avg_price,
                    price_unit_code=unit_code if avg_price is not None else None,
                )
            )
        return SolventNameUsageResponse(
            solvent_name=SolventNameResponse.model_validate(name_row),
            companies_with_stock=len(companies_with_stock),
            lines=usage_lines,
        )

    # Brands

    async def list_brands(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        is_active: bool | None,
    ) -> tuple[list[SolventBrandResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.brands.list(page=page, common_filter=common_filter, filters=filters or None)
        return [SolventBrandResponse.model_validate(row) for row in rows], total

    async def get_brand(self, brand_id: UUID) -> SolventBrandResponse:
        row = await self.brands.get(brand_id)
        if row is None:
            raise ResourceNotFoundError("Solvent brand not found")
        return SolventBrandResponse.model_validate(row)

    async def create_brand(self, payload: SolventBrandCreate) -> SolventBrandResponse:
        async with transaction(self.session):
            try:
                row = await self.brands.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("A solvent brand with this name already exists") from exc
            return SolventBrandResponse.model_validate(row)

    async def update_brand(self, brand_id: UUID, payload: SolventBrandUpdate) -> SolventBrandResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            try:
                updated = await self.brands.update(brand_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A solvent brand with this name already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Solvent brand not found")
            return SolventBrandResponse.model_validate(updated)

    async def delete_brand(self, brand_id: UUID) -> SolventBrandResponse:
        async with transaction(self.session):
            if await self.brands.count_lines(brand_id) > 0:
                raise ValidationError("Cannot delete a brand that is used on solvent lines")
            deleted = await self.brands.soft_delete(brand_id)
            if deleted is None:
                raise ResourceNotFoundError("Solvent brand not found")
            return SolventBrandResponse.model_validate(deleted)

    # Sheets and lines

    async def list_line_items(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
        permissions: frozenset[str],
    ) -> tuple[list[SolventLineListItem], int]:
        line_rows, total = await self.lines.list_inventory(
            page=page,
            common_filter=common_filter,
            company_id=company_id,
        )
        can_view_price = self._can_view_price(permissions)
        avg_map = await self._avg_prices_by_line_ids([line.id for line in line_rows]) if can_view_price else {}
        sheet_cache: dict[UUID, SolventSheet] = {}
        company_cache: dict[UUID, Company] = {}
        items: list[SolventLineListItem] = []
        for line in line_rows:
            sheet = sheet_cache.get(line.solvent_sheet_id)
            if sheet is None:
                sheet = await self.sheets.get(line.solvent_sheet_id)
                if sheet is None:
                    continue
                sheet_cache[line.solvent_sheet_id] = sheet
            company = company_cache.get(sheet.company_id)
            if company is None:
                company = await self._require_company(sheet.company_id)
                company_cache[sheet.company_id] = company
            line_resp = await self._line_response(
                line,
                can_view_price=can_view_price,
                avg_prices=avg_map,
            )
            items.append(
                SolventLineListItem(
                    solvent_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    **line_resp.model_dump(),
                )
            )
        return items, total

    async def list_sheets(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
    ) -> tuple[list[SolventSheetListItem], int]:
        filters: dict[str, object] = {}
        if company_id is not None:
            filters["company_id"] = company_id
        rows, total = await self.sheets.list(page=page, common_filter=common_filter, filters=filters or None)
        items: list[SolventSheetListItem] = []
        for sheet in rows:
            company = await self._require_company(sheet.company_id)
            line_rows = await self.lines.list_for_sheet(sheet.id)
            total_drums = sum((line.drum_count or Decimal("0") for line in line_rows), Decimal("0"))
            total_qty = sum((line.total_qty or Decimal("0") for line in line_rows), Decimal("0"))
            items.append(
                SolventSheetListItem(
                    id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    line_count=len(line_rows),
                    total_drums=self._display_decimal(total_drums) or Decimal("0"),
                    total_qty=self._display_decimal(total_qty) or Decimal("0"),
                    created_at=sheet.created_at,
                    updated_at=sheet.updated_at,
                )
            )
        return items, total

    async def get_sheet(self, sheet_id: UUID, *, permissions: frozenset[str]) -> SolventSheetResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Solvent sheet not found")
        return await self._sheet_response(sheet, can_view_price=self._can_view_price(permissions))

    async def create_sheet(
        self,
        payload: SolventSheetCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> SolventSheetResponse:
        await self._require_company(payload.company_id)
        existing = await self.sheets.get_by_company(payload.company_id)
        can_view_price = self._can_view_price(permissions)
        async with transaction(self.session):
            if existing is not None:
                await self.sheets.update(existing.id, {"updated_by": actor_user_id})
                if payload.lines:
                    await self._sync_lines(
                        existing,
                        payload.lines,
                        actor_user_id=actor_user_id,
                        can_view_price=can_view_price,
                        is_create=True,
                    )
                refreshed = await self.sheets.get(existing.id)
                assert refreshed is not None
                new_snapshot = await self._sheet_audit_snapshot(refreshed)
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="solvent_sheet",
                    entity_id=refreshed.id,
                    new_values=new_snapshot,
                )
                return await self._sheet_response(refreshed, can_view_price=can_view_price)

            sheet = await self.sheets.create(
                {"company_id": payload.company_id, "created_by": actor_user_id, "updated_by": actor_user_id}
            )
            if payload.lines:
                await self._sync_lines(
                    sheet,
                    payload.lines,
                    actor_user_id=actor_user_id,
                    can_view_price=can_view_price,
                    is_create=True,
                )
            refreshed = await self.sheets.get(sheet.id)
            assert refreshed is not None
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="solvent_sheet",
                entity_id=refreshed.id,
                new_values=await self._sheet_audit_snapshot(refreshed),
            )
            return await self._sheet_response(refreshed, can_view_price=can_view_price)

    async def update_sheet(
        self,
        sheet_id: UUID,
        payload: SolventSheetUpdate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> SolventSheetResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Solvent sheet not found")
        can_view_price = self._can_view_price(permissions)
        async with transaction(self.session):
            old_snapshot = await self._sheet_audit_snapshot(sheet)
            await self.sheets.update(sheet_id, {"updated_by": actor_user_id})
            if payload.lines is not None:
                await self._sync_lines(
                    sheet,
                    payload.lines,
                    actor_user_id=actor_user_id,
                    can_view_price=can_view_price,
                    is_create=False,
                )
            refreshed = await self.sheets.get(sheet_id)
            assert refreshed is not None
            new_snapshot = await self._sheet_audit_snapshot(refreshed)
            if audit_field_changes(old_snapshot, new_snapshot):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="solvent_sheet",
                    entity_id=refreshed.id,
                    old_values=old_snapshot,
                    new_values=new_snapshot,
                )
            return await self._sheet_response(refreshed, can_view_price=can_view_price)

    async def delete_sheet(self, sheet_id: UUID, *, actor_user_id: UUID) -> SolventSheetResponse:
        async with transaction(self.session):
            sheet = await self.sheets.get(sheet_id)
            if sheet is None:
                raise ResourceNotFoundError("Solvent sheet not found")
            old_snapshot = await self._sheet_audit_snapshot(sheet)
            line_rows = await self.lines.list_for_sheet(sheet_id)
            for line in line_rows:
                await self.lines.soft_delete(line.id)
            deleted = await self.sheets.soft_delete(sheet_id)
            assert deleted is not None
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="solvent_sheet",
                entity_id=sheet.id,
                old_values=old_snapshot,
            )
            return await self._sheet_response(deleted, can_view_price=True)

    @staticmethod
    def _find_line_by_brand_name(
        lines: list[SolventLine],
        brand_id: UUID,
        solvent_name_id: UUID,
    ) -> SolventLine | None:
        for line in lines:
            if line.brand_id == brand_id and line.solvent_name_id == solvent_name_id:
                return line
        return None

    async def _increment_solvent_line(
        self,
        line: SolventLine,
        item: SolventLineUpsert,
        *,
        drum_unit_id: UUID,
        incoming_qty: Decimal,
        actor_user_id: UUID,
        today: date,
    ) -> SolventLine:
        old_drums = line.drum_count or Decimal("0")
        old_qty = line.total_qty or Decimal("0")
        add_drums = item.drum_count or Decimal("0")
        add_qty = incoming_qty
        new_drums = old_drums + add_drums
        new_qty = old_qty + add_qty
        rate = item.solvent_rate if item.solvent_rate is not None else line.solvent_rate
        _, total_rate = self._line_totals(new_drums, item.drum_qty, rate)
        if add_drums > 0 or add_qty > 0:
            await self.movements.create(
                {
                    "solvent_line_id": line.id,
                    "movement_date": today,
                    "direction": MaterialMovementDirection.IN.value,
                    "drums": add_drums,
                    "quantity": add_qty,
                    "created_by": actor_user_id,
                    "solvent_rate": item.solvent_rate,
                }
            )
        updated = await self.lines.update(
            line.id,
            {
                "brand_id": item.brand_id,
                "solvent_name_id": item.solvent_name_id,
                "drum_count": new_drums,
                "drum_qty": item.drum_qty,
                "drum_unit_id": drum_unit_id,
                "total_qty": new_qty,
                "solvent_rate": rate,
                "total_rate": total_rate,
            },
        )
        assert updated is not None
        return updated

    async def _sync_lines(
        self,
        sheet: SolventSheet,
        payloads: list[SolventLineUpsert],
        *,
        actor_user_id: UUID,
        can_view_price: bool,
        is_create: bool,
    ) -> None:
        default_unit = await self._default_kg_unit_id()
        existing = {row.id: row for row in await self.lines.list_for_sheet(sheet.id)}
        sheet_lines = list(existing.values())
        seen_ids: set[UUID] = set()
        today = date.today()

        for item in payloads:
            drum_unit_id = item.drum_unit_id or default_unit
            await self._require_unit(drum_unit_id)
            await self._require_brand_name(item.brand_id, item.solvent_name_id)
            if item.solvent_rate is not None and not can_view_price:
                raise ValidationError("You do not have permission to set solvent rate")

            total_qty, total_rate = self._line_totals(item.drum_count, item.drum_qty, item.solvent_rate)

            if item.id is None:
                matched = self._find_line_by_brand_name(
                    sheet_lines,
                    item.brand_id,
                    item.solvent_name_id,
                )
                if matched is not None:
                    updated = await self._increment_solvent_line(
                        matched,
                        item,
                        drum_unit_id=drum_unit_id,
                        incoming_qty=total_qty,
                        actor_user_id=actor_user_id,
                        today=today,
                    )
                    existing[updated.id] = updated
                    sheet_lines = list(existing.values())
                    seen_ids.add(updated.id)
                    continue
                try:
                    line = await self.lines.create(
                        {
                            "solvent_sheet_id": sheet.id,
                            "brand_id": item.brand_id,
                            "solvent_name_id": item.solvent_name_id,
                            "drum_count": item.drum_count,
                            "drum_qty": item.drum_qty,
                            "drum_unit_id": drum_unit_id,
                            "total_qty": total_qty,
                            "solvent_rate": item.solvent_rate,
                            "total_rate": total_rate,
                        }
                    )
                except IntegrityError as exc:
                    raced = self._find_line_by_brand_name(
                        await self.lines.list_for_sheet(sheet.id),
                        item.brand_id,
                        item.solvent_name_id,
                    )
                    if raced is None:
                        raise DuplicateResourceError(
                            "This brand and code combination already exists on the sheet"
                        ) from exc
                    updated = await self._increment_solvent_line(
                        raced,
                        item,
                        drum_unit_id=drum_unit_id,
                        incoming_qty=total_qty,
                        actor_user_id=actor_user_id,
                        today=today,
                    )
                    existing[updated.id] = updated
                    sheet_lines = list(existing.values())
                    seen_ids.add(updated.id)
                    continue
                existing[line.id] = line
                sheet_lines = list(existing.values())
                seen_ids.add(line.id)
                await self.movements.create(
                    {
                        "solvent_line_id": line.id,
                        "movement_date": today,
                        "direction": MaterialMovementDirection.OPENING.value,
                        "drums": item.drum_count,
                        "quantity": total_qty,
                        "created_by": actor_user_id,
                        "solvent_rate": item.solvent_rate,
                    }
                )
                continue

            seen_ids.add(item.id)
            line = existing.get(item.id)
            if line is None or line.solvent_sheet_id != sheet.id:
                raise ValidationError("Invalid line id for this sheet")

            old_drums = line.drum_count or Decimal("0")
            old_qty = line.total_qty or Decimal("0")
            if item.drum_count < old_drums or total_qty < old_qty:
                raise ValidationError("Use stock out to reduce drums or quantity on hand")

            drum_delta = item.drum_count - old_drums
            qty_delta = total_qty - old_qty
            if drum_delta > 0 or qty_delta > 0:
                await self.movements.create(
                    {
                        "solvent_line_id": line.id,
                        "movement_date": today,
                        "direction": MaterialMovementDirection.IN.value,
                        "drums": drum_delta,
                        "quantity": qty_delta,
                        "created_by": actor_user_id,
                        "solvent_rate": item.solvent_rate,
                    }
                )

            try:
                await self.lines.update(
                    line.id,
                    {
                        "brand_id": item.brand_id,
                        "solvent_name_id": item.solvent_name_id,
                        "drum_count": item.drum_count,
                        "drum_qty": item.drum_qty,
                        "drum_unit_id": drum_unit_id,
                        "total_qty": total_qty,
                        "solvent_rate": item.solvent_rate,
                        "total_rate": total_rate,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "This brand and code combination already exists on the sheet"
                ) from exc

        if not is_create:
            for line_id, line in existing.items():
                if line_id in seen_ids:
                    continue
                if (line.drum_count or Decimal("0")) > 0 or (line.total_qty or Decimal("0")) > 0:
                    raise ValidationError("Remove stock before deleting a line")
                await self.lines.soft_delete(line_id)

    async def _require_unit(self, unit_id: UUID) -> InventoryUnit:
        unit = await self.units.get(unit_id)
        if unit is None:
            raise ResourceNotFoundError("Unit not found")
        return unit

    async def _require_brand_name(self, brand_id: UUID, solvent_name_id: UUID) -> None:
        brand = await self.brands.get(brand_id)
        if brand is None:
            raise ResourceNotFoundError("Solvent brand not found")
        name_row = await self.names.get(solvent_name_id)
        if name_row is None:
            raise ResourceNotFoundError("Solvent name not found")

    async def stock_out(
        self,
        sheet_id: UUID,
        payload: SolventStockOutCreate,
        *,
        actor_user_id: UUID,
    ) -> SolventLineResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Solvent sheet not found")
        line = await self.lines.get(payload.solvent_line_id)
        if line is None or line.solvent_sheet_id != sheet.id:
            raise ResourceNotFoundError("Solvent line not found")

        movement_date = payload.movement_date or date.today()
        async with transaction(self.session):
            current_drums = line.drum_count or Decimal("0")
            current_qty = line.total_qty or Decimal("0")
            new_drums = current_drums - payload.drums
            new_qty = current_qty - payload.quantity
            if new_drums < 0 or new_qty < 0:
                raise InsufficientStockError(
                    "Insufficient stock for this stock out",
                    details={
                        "available_drums": str(current_drums),
                        "available_quantity": str(current_qty),
                    },
                )
            _, total_rate = self._line_totals(new_drums, line.drum_qty or Decimal("0"), line.solvent_rate)
            updated = await self.lines.update(
                line.id,
                {
                    "drum_count": new_drums,
                    "total_qty": new_qty,
                    "total_rate": total_rate,
                },
            )
            assert updated is not None
            line = updated

            await self.movements.create(
                {
                    "solvent_line_id": line.id,
                    "movement_date": movement_date,
                    "direction": MaterialMovementDirection.OUT.value,
                    "drums": payload.drums,
                    "quantity": payload.quantity,
                    "note": payload.note,
                    "created_by": actor_user_id,
                    "solvent_rate": line.solvent_rate,
                }
            )
            brand = await self.brands.get(line.brand_id)
            name_row = await self.names.get(line.solvent_name_id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="solvent_sheet",
                entity_id=sheet.id,
                new_values={
                    "event_kind": "stock_out",
                    "line": f"{brand.name if brand else ''} · {name_row.name if name_row else ''}",
                    "drums_out": jsonable_value(payload.drums),
                    "quantity_out": jsonable_value(payload.quantity),
                    "note": payload.note,
                },
            )
            return await self._line_response(line, can_view_price=True)

    async def day_report(
        self,
        *,
        start_date: date,
        end_date: date,
        permissions: frozenset[str],
    ) -> list[SolventDayReportRow]:
        can_view_price = self._can_view_price(permissions)
        active_lines = await self.lines.list_active_lines()
        if not active_lines:
            return []

        day_totals = await self.movements.day_totals(start_date, end_date)
        rows: list[SolventDayReportRow] = []

        for line in active_lines:
            in_d, in_q, out_d, out_q = day_totals.get(
                line.id, (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
            )
            closing_drums, closing_qty = await self.movements.sum_through_date(line.id, end_date)
            if (
                in_d == 0
                and in_q == 0
                and out_d == 0
                and out_q == 0
                and closing_drums == 0
                and closing_qty == 0
            ):
                continue

            sheet = await self.sheets.get(line.solvent_sheet_id)
            if sheet is None:
                continue
            company = await self._require_company(sheet.company_id)
            brand = await self.brands.get(line.brand_id)
            name_row = await self.names.get(line.solvent_name_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit = units.get(line.drum_unit_id)

            rows.append(
                SolventDayReportRow(
                    solvent_line_id=line.id,
                    solvent_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    brand_id=line.brand_id,
                    brand_name=brand.name if brand else "",
                    solvent_name_id=line.solvent_name_id,
                    name=name_row.name if name_row else "",
                    drum_unit_code=unit.code if unit else "",
                    in_drums=self._display_decimal(in_d) or Decimal("0"),
                    in_qty=self._display_decimal(in_q) or Decimal("0"),
                    out_drums=self._display_decimal(out_d) or Decimal("0"),
                    out_qty=self._display_decimal(out_q) or Decimal("0"),
                    closing_drums=self._display_decimal(closing_drums) or Decimal("0"),
                    closing_qty=self._display_decimal(closing_qty) or Decimal("0"),
                    solvent_rate=self._display_decimal(line.solvent_rate) if can_view_price else None,
                )
            )
        rows.sort(key=lambda row: (row.company_name, row.brand_name, row.name))
        return rows
