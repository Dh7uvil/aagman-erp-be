"""Adhesive inventory business logic."""

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
from app.inventory.catalog import ADHESIVE_VIEW_PRICE
from app.inventory.adhesives.models import AdhesiveBrand, AdhesiveCode, AdhesiveLine, AdhesiveMovement, AdhesiveSheet
from app.inventory.adhesives.repository import (
    AdhesiveBrandRepository,
    AdhesiveCodeRepository,
    AdhesiveLineRepository,
    AdhesiveMovementRepository,
    AdhesiveSheetRepository,
)
from app.inventory.adhesives.schemas import (
    AdhesiveBrandCreate,
    AdhesiveBrandResponse,
    AdhesiveBrandUpdate,
    AdhesiveCodeCreate,
    AdhesiveCodeResponse,
    AdhesiveCodeUpdate,
    AdhesiveCodeUsageLine,
    AdhesiveCodeUsageResponse,
    AdhesiveDayReportRow,
    AdhesiveLineResponse,
    AdhesiveLineUpsert,
    AdhesiveSheetCreate,
    AdhesiveLineListItem,
    AdhesiveSheetListItem,
    AdhesiveSheetResponse,
    AdhesiveSheetUpdate,
    AdhesiveStockOutCreate,
)
from app.inventory.models import InventoryUnit
from app.inventory.pricing import compute_avg_price
from app.inventory.repository import UnitRepository
from app.inventory.schemas import DrumLineHistoryEntry, DrumLineHistorySummary

class AdhesiveService:
    _DISPLAY_SCALE = Decimal("0.01")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.codes = AdhesiveCodeRepository(session)
        self.brands = AdhesiveBrandRepository(session)
        self.sheets = AdhesiveSheetRepository(session)
        self.lines = AdhesiveLineRepository(session)
        self.movements = AdhesiveMovementRepository(session)
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
        return has_permission(permissions, ADHESIVE_VIEW_PRICE)

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
    def _line_totals(drum_count: Decimal, drum_qty: Decimal, adhesive_rate: Decimal | None) -> tuple[Decimal, Decimal | None]:
        total_qty = drum_count * drum_qty
        total_rate = (total_qty * adhesive_rate) if adhesive_rate is not None else None
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
        line: AdhesiveLine,
        *,
        can_view_price: bool,
        avg_prices: Mapping[UUID, Decimal | None] | None = None,
    ) -> AdhesiveLineResponse:
        brand = await self.brands.get(line.brand_id)
        code_row = await self.codes.get(line.adhesive_code_id)
        units = await self._load_unit_codes([line.drum_unit_id])
        unit = units.get(line.drum_unit_id)
        unit_code = unit.code if unit else ""
        adhesive_rate = self._display_decimal(line.adhesive_rate) if can_view_price else None
        total_rate = self._display_decimal(line.total_rate) if can_view_price else None
        avg_price: Decimal | None = None
        if can_view_price:
            if avg_prices is not None:
                avg_price = avg_prices.get(line.id)
            else:
                avg_map = await self._avg_prices_by_line_ids([line.id])
                avg_price = avg_map.get(line.id)
        return AdhesiveLineResponse(
            id=line.id,
            brand_id=line.brand_id,
            brand_name=brand.name if brand else "",
            adhesive_code_id=line.adhesive_code_id,
            code=code_row.code if code_row else "",
            drum_count=self._display_decimal(line.drum_count) or Decimal("0"),
            drum_qty=self._display_decimal(line.drum_qty) or Decimal("0"),
            drum_unit_id=line.drum_unit_id,
            drum_unit_code=unit_code,
            total_qty=self._display_decimal(line.total_qty) or Decimal("0"),
            adhesive_rate=adhesive_rate,
            total_rate=total_rate,
            avg_price_per_unit=avg_price,
            price_unit_code=unit_code if avg_price is not None else None,
            created_at=line.created_at,
            updated_at=line.updated_at,
        )

    async def _line_responses(
        self,
        line_rows: list[AdhesiveLine],
        *,
        can_view_price: bool,
    ) -> list[AdhesiveLineResponse]:
        avg_map: dict[UUID, Decimal | None] = {}
        if can_view_price and line_rows:
            avg_map = await self._avg_prices_by_line_ids([row.id for row in line_rows])
        return [
            await self._line_response(row, can_view_price=can_view_price, avg_prices=avg_map)
            for row in line_rows
        ]

    async def _sheet_response(self, sheet: AdhesiveSheet, *, can_view_price: bool) -> AdhesiveSheetResponse:
        company = await self._require_company(sheet.company_id)
        line_rows = await self.lines.list_for_sheet(sheet.id)
        lines = await self._line_responses(line_rows, can_view_price=can_view_price)
        return AdhesiveSheetResponse(
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
    ) -> tuple[list[AdhesiveCodeResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.codes.list(page=page, common_filter=common_filter, filters=filters or None)
        return [AdhesiveCodeResponse.model_validate(row) for row in rows], total

    async def get_code(self, adhesive_code_id: UUID) -> AdhesiveCodeResponse:
        row = await self.codes.get(adhesive_code_id)
        if row is None:
            raise ResourceNotFoundError("Adhesive code not found")
        return AdhesiveCodeResponse.model_validate(row)

    @staticmethod
    def _code_snapshot(row: AdhesiveCode) -> dict[str, object]:
        return {
            "code": row.code,
            "is_active": row.is_active,
        }

    async def _sheet_audit_snapshot(self, sheet: AdhesiveSheet) -> dict[str, object]:
        company = await self._require_company(sheet.company_id)
        line_rows = await self.lines.list_for_sheet(sheet.id)
        summaries: list[str] = []
        for line in line_rows:
            brand = await self.brands.get(line.brand_id)
            code_row = await self.codes.get(line.adhesive_code_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit_code = units.get(line.drum_unit_id)
            unit_code = unit_code.code if unit_code else ""
            brand_name = brand.name if brand else ""
            code_label = code_row.code if code_row else ""
            summaries.append(
                f"{brand_name} · {code_label}: "
                f"{jsonable_value(line.drum_count)} drums, "
                f"{jsonable_value(line.total_qty)} {unit_code}"
            )
        return {
            "company_name": company.name,
            "lines": summaries,
        }

    async def code_history(
        self,
        adhesive_code_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        if await self.codes.get(adhesive_code_id) is None:
            raise ResourceNotFoundError("Adhesive code not found")
        return await self.history.list_for_entity(
            entity_type="adhesive_code",
            entity_id=adhesive_code_id,
            page=page,
        )

    async def sheet_history(
        self,
        sheet_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        if await self.sheets.get(sheet_id) is None:
            raise ResourceNotFoundError("Adhesive sheet not found")
        return await self.history.list_for_entity(
            entity_type="adhesive_sheet",
            entity_id=sheet_id,
            page=page,
        )

    async def _line_history_context(
        self,
        line_id: UUID,
    ) -> tuple[AdhesiveLine, AdhesiveSheet, Company, str, str, str]:
        line = await self.lines.get(line_id)
        if line is None:
            raise ResourceNotFoundError("Adhesive line not found")
        sheet = await self.sheets.get(line.adhesive_sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Adhesive sheet not found")
        company = await self._require_company(sheet.company_id)
        brand = await self.brands.get(line.brand_id)
        code_row = await self.codes.get(line.adhesive_code_id)
        units = await self._load_unit_codes([line.drum_unit_id])
        unit_code = units.get(line.drum_unit_id)
        return (
            line,
            sheet,
            company,
            brand.name if brand else "",
            code_row.code if code_row else "",
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
            rate = self._display_decimal(movement.adhesive_rate) if can_view_price else None
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
                last_price = self._display_decimal(last_in.adhesive_rate)
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
        payload: AdhesiveCodeCreate,
        *,
        actor_user_id: UUID,
    ) -> AdhesiveCodeResponse:
        async with transaction(self.session):
            try:
                row = await self.codes.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("An adhesive code with this code already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="adhesive_code",
                entity_id=row.id,
                new_values=self._code_snapshot(row),
            )
            return AdhesiveCodeResponse.model_validate(row)

    async def update_code(
        self,
        adhesive_code_id: UUID,
        payload: AdhesiveCodeUpdate,
        *,
        actor_user_id: UUID,
    ) -> AdhesiveCodeResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self.codes.get(adhesive_code_id)
            if existing is None:
                raise ResourceNotFoundError("Adhesive code not found")
            old = self._code_snapshot(existing)
            try:
                updated = await self.codes.update(adhesive_code_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("An adhesive code with this code already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Adhesive code not found")
            new = self._code_snapshot(updated)
            if audit_field_changes(old, new):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="adhesive_code",
                    entity_id=updated.id,
                    old_values=old,
                    new_values=new,
                )
            return AdhesiveCodeResponse.model_validate(updated)

    async def delete_code(
        self,
        adhesive_code_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> AdhesiveCodeResponse:
        async with transaction(self.session):
            if await self.codes.count_lines(adhesive_code_id) > 0:
                raise ValidationError("Cannot delete a code that is used on adhesive lines")
            existing = await self.codes.get(adhesive_code_id)
            if existing is None:
                raise ResourceNotFoundError("Adhesive code not found")
            deleted = await self.codes.soft_delete(adhesive_code_id)
            if deleted is None:
                raise ResourceNotFoundError("Adhesive code not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="adhesive_code",
                entity_id=existing.id,
                old_values=self._code_snapshot(existing),
            )
            return AdhesiveCodeResponse.model_validate(deleted)

    async def code_usage(self, adhesive_code_id: UUID, *, permissions: frozenset[str]) -> AdhesiveCodeUsageResponse:
        code_row = await self.codes.get(adhesive_code_id)
        if code_row is None:
            raise ResourceNotFoundError("Adhesive code not found")
        can_view_price = self._can_view_price(permissions)
        line_rows = await self.lines.list_for_code(adhesive_code_id)
        avg_map = (
            await self._avg_prices_by_line_ids([line.id for line in line_rows])
            if can_view_price
            else {}
        )
        companies_with_stock: set[UUID] = set()
        usage_lines: list[AdhesiveCodeUsageLine] = []
        for line in line_rows:
            sheet = await self.sheets.get(line.adhesive_sheet_id)
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
                AdhesiveCodeUsageLine(
                    adhesive_line_id=line.id,
                    adhesive_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    brand_id=line.brand_id,
                    brand_name=brand.name if brand else "",
                    drum_count=self._display_decimal(drums) or Decimal("0"),
                    drum_qty=self._display_decimal(line.drum_qty) or Decimal("0"),
                    drum_unit_code=unit_code,
                    total_qty=self._display_decimal(qty) or Decimal("0"),
                    adhesive_rate=self._display_decimal(line.adhesive_rate) if can_view_price else None,
                    total_rate=self._display_decimal(line.total_rate) if can_view_price else None,
                    avg_price_per_unit=avg_price,
                    price_unit_code=unit_code if avg_price is not None else None,
                )
            )
        return AdhesiveCodeUsageResponse(
            adhesive_code=AdhesiveCodeResponse.model_validate(code_row),
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
    ) -> tuple[list[AdhesiveBrandResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.brands.list(page=page, common_filter=common_filter, filters=filters or None)
        return [AdhesiveBrandResponse.model_validate(row) for row in rows], total

    async def get_brand(self, brand_id: UUID) -> AdhesiveBrandResponse:
        row = await self.brands.get(brand_id)
        if row is None:
            raise ResourceNotFoundError("Adhesive brand not found")
        return AdhesiveBrandResponse.model_validate(row)

    async def create_brand(self, payload: AdhesiveBrandCreate) -> AdhesiveBrandResponse:
        async with transaction(self.session):
            try:
                row = await self.brands.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("An adhesive brand with this name already exists") from exc
            return AdhesiveBrandResponse.model_validate(row)

    async def update_brand(self, brand_id: UUID, payload: AdhesiveBrandUpdate) -> AdhesiveBrandResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            try:
                updated = await self.brands.update(brand_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("An adhesive brand with this name already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Adhesive brand not found")
            return AdhesiveBrandResponse.model_validate(updated)

    async def delete_brand(self, brand_id: UUID) -> AdhesiveBrandResponse:
        async with transaction(self.session):
            if await self.brands.count_lines(brand_id) > 0:
                raise ValidationError("Cannot delete a brand that is used on adhesive lines")
            deleted = await self.brands.soft_delete(brand_id)
            if deleted is None:
                raise ResourceNotFoundError("Adhesive brand not found")
            return AdhesiveBrandResponse.model_validate(deleted)

    # Sheets and lines

    async def list_line_items(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
        permissions: frozenset[str],
    ) -> tuple[list[AdhesiveLineListItem], int]:
        line_rows, total = await self.lines.list_inventory(
            page=page,
            common_filter=common_filter,
            company_id=company_id,
        )
        can_view_price = self._can_view_price(permissions)
        avg_map = await self._avg_prices_by_line_ids([line.id for line in line_rows]) if can_view_price else {}
        sheet_cache: dict[UUID, AdhesiveSheet] = {}
        company_cache: dict[UUID, Company] = {}
        items: list[AdhesiveLineListItem] = []
        for line in line_rows:
            sheet = sheet_cache.get(line.adhesive_sheet_id)
            if sheet is None:
                sheet = await self.sheets.get(line.adhesive_sheet_id)
                if sheet is None:
                    continue
                sheet_cache[line.adhesive_sheet_id] = sheet
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
                AdhesiveLineListItem(
                    adhesive_sheet_id=sheet.id,
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
    ) -> tuple[list[AdhesiveSheetListItem], int]:
        filters: dict[str, object] = {}
        if company_id is not None:
            filters["company_id"] = company_id
        rows, total = await self.sheets.list(page=page, common_filter=common_filter, filters=filters or None)
        items: list[AdhesiveSheetListItem] = []
        for sheet in rows:
            company = await self._require_company(sheet.company_id)
            line_rows = await self.lines.list_for_sheet(sheet.id)
            total_drums = sum((line.drum_count or Decimal("0") for line in line_rows), Decimal("0"))
            total_qty = sum((line.total_qty or Decimal("0") for line in line_rows), Decimal("0"))
            items.append(
                AdhesiveSheetListItem(
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

    async def get_sheet(self, sheet_id: UUID, *, permissions: frozenset[str]) -> AdhesiveSheetResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Adhesive sheet not found")
        return await self._sheet_response(sheet, can_view_price=self._can_view_price(permissions))

    async def create_sheet(
        self,
        payload: AdhesiveSheetCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> AdhesiveSheetResponse:
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
                    entity_type="adhesive_sheet",
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
                entity_type="adhesive_sheet",
                entity_id=refreshed.id,
                new_values=await self._sheet_audit_snapshot(refreshed),
            )
            return await self._sheet_response(refreshed, can_view_price=can_view_price)

    async def update_sheet(
        self,
        sheet_id: UUID,
        payload: AdhesiveSheetUpdate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> AdhesiveSheetResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Adhesive sheet not found")
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
                    entity_type="adhesive_sheet",
                    entity_id=refreshed.id,
                    old_values=old_snapshot,
                    new_values=new_snapshot,
                )
            return await self._sheet_response(refreshed, can_view_price=can_view_price)

    async def delete_sheet(self, sheet_id: UUID, *, actor_user_id: UUID) -> AdhesiveSheetResponse:
        async with transaction(self.session):
            sheet = await self.sheets.get(sheet_id)
            if sheet is None:
                raise ResourceNotFoundError("Adhesive sheet not found")
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
                entity_type="adhesive_sheet",
                entity_id=sheet.id,
                old_values=old_snapshot,
            )
            return await self._sheet_response(deleted, can_view_price=True)

    @staticmethod
    def _find_line_by_brand_code(
        lines: list[AdhesiveLine],
        brand_id: UUID,
        adhesive_code_id: UUID,
    ) -> AdhesiveLine | None:
        for line in lines:
            if line.brand_id == brand_id and line.adhesive_code_id == adhesive_code_id:
                return line
        return None

    async def _increment_adhesive_line(
        self,
        line: AdhesiveLine,
        item: AdhesiveLineUpsert,
        *,
        drum_unit_id: UUID,
        incoming_qty: Decimal,
        actor_user_id: UUID,
        today: date,
    ) -> AdhesiveLine:
        old_drums = line.drum_count or Decimal("0")
        old_qty = line.total_qty or Decimal("0")
        add_drums = item.drum_count or Decimal("0")
        add_qty = incoming_qty
        new_drums = old_drums + add_drums
        new_qty = old_qty + add_qty
        rate = item.adhesive_rate if item.adhesive_rate is not None else line.adhesive_rate
        _, total_rate = self._line_totals(new_drums, item.drum_qty, rate)
        if add_drums > 0 or add_qty > 0:
            await self.movements.create(
                {
                    "adhesive_line_id": line.id,
                    "movement_date": today,
                    "direction": MaterialMovementDirection.IN.value,
                    "drums": add_drums,
                    "quantity": add_qty,
                    "created_by": actor_user_id,
                    "adhesive_rate": item.adhesive_rate,
                }
            )
        updated = await self.lines.update(
            line.id,
            {
                "brand_id": item.brand_id,
                "adhesive_code_id": item.adhesive_code_id,
                "drum_count": new_drums,
                "drum_qty": item.drum_qty,
                "drum_unit_id": drum_unit_id,
                "total_qty": new_qty,
                "adhesive_rate": rate,
                "total_rate": total_rate,
            },
        )
        assert updated is not None
        return updated

    async def _sync_lines(
        self,
        sheet: AdhesiveSheet,
        payloads: list[AdhesiveLineUpsert],
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
            await self._require_brand_code(item.brand_id, item.adhesive_code_id)
            if item.adhesive_rate is not None and not can_view_price:
                raise ValidationError("You do not have permission to set adhesive rate")

            total_qty, total_rate = self._line_totals(item.drum_count, item.drum_qty, item.adhesive_rate)

            if item.id is None:
                matched = self._find_line_by_brand_code(
                    sheet_lines,
                    item.brand_id,
                    item.adhesive_code_id,
                )
                if matched is not None:
                    updated = await self._increment_adhesive_line(
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
                            "adhesive_sheet_id": sheet.id,
                            "brand_id": item.brand_id,
                            "adhesive_code_id": item.adhesive_code_id,
                            "drum_count": item.drum_count,
                            "drum_qty": item.drum_qty,
                            "drum_unit_id": drum_unit_id,
                            "total_qty": total_qty,
                            "adhesive_rate": item.adhesive_rate,
                            "total_rate": total_rate,
                        }
                    )
                except IntegrityError as exc:
                    raced = self._find_line_by_brand_code(
                        await self.lines.list_for_sheet(sheet.id),
                        item.brand_id,
                        item.adhesive_code_id,
                    )
                    if raced is None:
                        raise DuplicateResourceError(
                            "This brand and code combination already exists on the sheet"
                        ) from exc
                    updated = await self._increment_adhesive_line(
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
                        "adhesive_line_id": line.id,
                        "movement_date": today,
                        "direction": MaterialMovementDirection.OPENING.value,
                        "drums": item.drum_count,
                        "quantity": total_qty,
                        "created_by": actor_user_id,
                        "adhesive_rate": item.adhesive_rate,
                    }
                )
                continue

            seen_ids.add(item.id)
            line = existing.get(item.id)
            if line is None or line.adhesive_sheet_id != sheet.id:
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
                        "adhesive_line_id": line.id,
                        "movement_date": today,
                        "direction": MaterialMovementDirection.IN.value,
                        "drums": drum_delta,
                        "quantity": qty_delta,
                        "created_by": actor_user_id,
                        "adhesive_rate": item.adhesive_rate,
                    }
                )

            try:
                await self.lines.update(
                    line.id,
                    {
                        "brand_id": item.brand_id,
                        "adhesive_code_id": item.adhesive_code_id,
                        "drum_count": item.drum_count,
                        "drum_qty": item.drum_qty,
                        "drum_unit_id": drum_unit_id,
                        "total_qty": total_qty,
                        "adhesive_rate": item.adhesive_rate,
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

    async def _require_brand_code(self, brand_id: UUID, adhesive_code_id: UUID) -> None:
        brand = await self.brands.get(brand_id)
        if brand is None:
            raise ResourceNotFoundError("Adhesive brand not found")
        color = await self.codes.get(adhesive_code_id)
        if color is None:
            raise ResourceNotFoundError("Adhesive code not found")

    async def stock_out(
        self,
        sheet_id: UUID,
        payload: AdhesiveStockOutCreate,
        *,
        actor_user_id: UUID,
    ) -> AdhesiveLineResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Adhesive sheet not found")
        line = await self.lines.get(payload.adhesive_line_id)
        if line is None or line.adhesive_sheet_id != sheet.id:
            raise ResourceNotFoundError("Adhesive line not found")

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
            _, total_rate = self._line_totals(new_drums, line.drum_qty or Decimal("0"), line.adhesive_rate)
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
                    "adhesive_line_id": line.id,
                    "movement_date": movement_date,
                    "direction": MaterialMovementDirection.OUT.value,
                    "drums": payload.drums,
                    "quantity": payload.quantity,
                    "note": payload.note,
                    "created_by": actor_user_id,
                    "adhesive_rate": line.adhesive_rate,
                }
            )
            brand = await self.brands.get(line.brand_id)
            code_row = await self.codes.get(line.adhesive_code_id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="adhesive_sheet",
                entity_id=sheet.id,
                new_values={
                    "event_kind": "stock_out",
                    "line": f"{brand.name if brand else ''} · {code_row.code if code_row else ''}",
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
    ) -> list[AdhesiveDayReportRow]:
        can_view_price = self._can_view_price(permissions)
        active_lines = await self.lines.list_active_lines()
        if not active_lines:
            return []

        day_totals = await self.movements.day_totals(start_date, end_date)
        rows: list[AdhesiveDayReportRow] = []

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

            sheet = await self.sheets.get(line.adhesive_sheet_id)
            if sheet is None:
                continue
            company = await self._require_company(sheet.company_id)
            brand = await self.brands.get(line.brand_id)
            code_row = await self.codes.get(line.adhesive_code_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit = units.get(line.drum_unit_id)

            rows.append(
                AdhesiveDayReportRow(
                    adhesive_line_id=line.id,
                    adhesive_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    brand_id=line.brand_id,
                    brand_name=brand.name if brand else "",
                    adhesive_code_id=line.adhesive_code_id,
                    code=code_row.code if code_row else "",
                    drum_unit_code=unit.code if unit else "",
                    in_drums=self._display_decimal(in_d) or Decimal("0"),
                    in_qty=self._display_decimal(in_q) or Decimal("0"),
                    out_drums=self._display_decimal(out_d) or Decimal("0"),
                    out_qty=self._display_decimal(out_q) or Decimal("0"),
                    closing_drums=self._display_decimal(closing_drums) or Decimal("0"),
                    closing_qty=self._display_decimal(closing_qty) or Decimal("0"),
                    adhesive_rate=self._display_decimal(line.adhesive_rate) if can_view_price else None,
                )
            )
        rows.sort(key=lambda row: (row.company_name, row.brand_name, row.code))
        return rows
