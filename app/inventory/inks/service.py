"""Ink inventory business logic."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import UploadFile
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
from app.core.config import get_settings
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
from app.identity.models import Company
from app.integrations.storage import get_optional_storage
from app.inventory.catalog import (
    INK_IMAGE_CREATE,
    INK_IMAGE_DELETE,
    INK_IMAGE_READ,
    INK_IMAGE_UPDATE,
    INK_VIEW_PRICE,
)
from app.inventory.inks import storage as ink_storage
from app.inventory.inks.models import InkBrand, InkColor, InkLine, InkMovement, InkSheet
from app.inventory.inks.repository import (
    InkBrandRepository,
    InkColorRepository,
    InkLineRepository,
    InkMovementRepository,
    InkSheetRepository,
)
from app.inventory.inks.schemas import (
    INK_FILE_SLOTS,
    InkBrandCreate,
    InkBrandResponse,
    InkBrandUpdate,
    InkColorCreate,
    InkColorResponse,
    InkColorUpdate,
    InkColorUsageLine,
    InkColorUsageResponse,
    InkDayReportRow,
    InkFileMeta,
    InkLineResponse,
    InkLineUpsert,
    InkSheetCreate,
    InkLineListItem,
    InkSheetListItem,
    InkSheetResponse,
    InkSheetUpdate,
    InkStockOutCreate,
)
from app.inventory.models import InventoryUnit
from app.inventory.repository import UnitRepository

INK_ALLOWED_MIME = (MIME_JPEG, MIME_PNG, MIME_WEBP, MIME_PDF)

_SLOT_READ = {"product_image": INK_IMAGE_READ, "ink_image": INK_IMAGE_READ}
_SLOT_CREATE = {"product_image": INK_IMAGE_CREATE, "ink_image": INK_IMAGE_CREATE}
_SLOT_UPDATE = {"product_image": INK_IMAGE_UPDATE, "ink_image": INK_IMAGE_UPDATE}
_SLOT_DELETE = {"product_image": INK_IMAGE_DELETE, "ink_image": INK_IMAGE_DELETE}


class InkService:
    _DISPLAY_SCALE = Decimal("0.01")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.colors = InkColorRepository(session)
        self.brands = InkBrandRepository(session)
        self.sheets = InkSheetRepository(session)
        self.lines = InkLineRepository(session)
        self.movements = InkMovementRepository(session)
        self.units = UnitRepository(session)
        self.storage = get_optional_storage()
        self.settings = get_settings()
        self.audit = AuditWriter(session)
        self.history = EntityHistoryService(session)

    @classmethod
    def _display_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(cls._DISPLAY_SCALE, rounding=ROUND_HALF_UP)

    @staticmethod
    def _can_view_price(permissions: frozenset[str]) -> bool:
        return has_permission(permissions, INK_VIEW_PRICE)

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
    def _line_totals(drum_count: Decimal, drum_qty: Decimal, ink_rate: Decimal | None) -> tuple[Decimal, Decimal | None]:
        total_qty = drum_count * drum_qty
        total_rate = (total_qty * ink_rate) if ink_rate is not None else None
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

    async def _line_response(self, line: InkLine, *, can_view_price: bool) -> InkLineResponse:
        brand = await self.brands.get(line.brand_id)
        color = await self.colors.get(line.color_id)
        units = await self._load_unit_codes([line.drum_unit_id])
        unit = units.get(line.drum_unit_id)
        ink_rate = self._display_decimal(line.ink_rate) if can_view_price else None
        total_rate = self._display_decimal(line.total_rate) if can_view_price else None
        return InkLineResponse(
            id=line.id,
            brand_id=line.brand_id,
            brand_name=brand.name if brand else "",
            color_id=line.color_id,
            color_name=color.name if color else "",
            hex_code=color.hex_code if color else None,
            drum_count=self._display_decimal(line.drum_count) or Decimal("0"),
            drum_qty=self._display_decimal(line.drum_qty) or Decimal("0"),
            drum_unit_id=line.drum_unit_id,
            drum_unit_code=unit.code if unit else "",
            total_qty=self._display_decimal(line.total_qty) or Decimal("0"),
            ink_rate=ink_rate,
            total_rate=total_rate,
            created_at=line.created_at,
            updated_at=line.updated_at,
        )

    def _file_meta(self, sheet: InkSheet, slot: str) -> InkFileMeta | None:
        if slot == "product_image":
            if not sheet.product_image_filename:
                return None
            return InkFileMeta(
                filename=sheet.product_image_filename,
                content_type=sheet.product_image_content_type or "",
                size_bytes=int(sheet.product_image_size_bytes or 0),
            )
        if not sheet.ink_image_filename:
            return None
        return InkFileMeta(
            filename=sheet.ink_image_filename,
            content_type=sheet.ink_image_content_type or "",
            size_bytes=int(sheet.ink_image_size_bytes or 0),
        )

    async def _sheet_response(self, sheet: InkSheet, *, can_view_price: bool) -> InkSheetResponse:
        company = await self._require_company(sheet.company_id)
        line_rows = await self.lines.list_for_sheet(sheet.id)
        lines = [await self._line_response(row, can_view_price=can_view_price) for row in line_rows]
        return InkSheetResponse(
            id=sheet.id,
            company_id=sheet.company_id,
            company_name=company.name,
            lines=lines,
            product_image=self._file_meta(sheet, "product_image"),
            ink_image=self._file_meta(sheet, "ink_image"),
            created_at=sheet.created_at,
            updated_at=sheet.updated_at,
        )

    # Colors

    async def list_colors(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        is_active: bool | None,
    ) -> tuple[list[InkColorResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.colors.list(page=page, common_filter=common_filter, filters=filters or None)
        return [InkColorResponse.model_validate(row) for row in rows], total

    async def get_color(self, color_id: UUID) -> InkColorResponse:
        row = await self.colors.get(color_id)
        if row is None:
            raise ResourceNotFoundError("Ink color not found")
        return InkColorResponse.model_validate(row)

    @staticmethod
    def _color_snapshot(row: InkColor) -> dict[str, object]:
        return {
            "name": row.name,
            "hex_code": row.hex_code,
            "is_active": row.is_active,
        }

    async def _sheet_audit_snapshot(self, sheet: InkSheet) -> dict[str, object]:
        company = await self._require_company(sheet.company_id)
        line_rows = await self.lines.list_for_sheet(sheet.id)
        summaries: list[str] = []
        for line in line_rows:
            brand = await self.brands.get(line.brand_id)
            color = await self.colors.get(line.color_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit_code = units.get(line.drum_unit_id)
            unit_code = unit_code.code if unit_code else ""
            brand_name = brand.name if brand else ""
            color_name = color.name if color else ""
            summaries.append(
                f"{brand_name} · {color_name}: "
                f"{jsonable_value(line.drum_count)} drums, "
                f"{jsonable_value(line.total_qty)} {unit_code}"
            )
        return {
            "company_name": company.name,
            "lines": summaries,
        }

    async def color_history(
        self,
        color_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        if await self.colors.get(color_id) is None:
            raise ResourceNotFoundError("Ink color not found")
        return await self.history.list_for_entity(
            entity_type="ink_color",
            entity_id=color_id,
            page=page,
        )

    async def sheet_history(
        self,
        sheet_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        if await self.sheets.get(sheet_id) is None:
            raise ResourceNotFoundError("Ink sheet not found")
        return await self.history.list_for_entity(
            entity_type="ink_sheet",
            entity_id=sheet_id,
            page=page,
        )

    async def create_color(
        self,
        payload: InkColorCreate,
        *,
        actor_user_id: UUID,
    ) -> InkColorResponse:
        async with transaction(self.session):
            try:
                row = await self.colors.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("An ink color with this name already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="ink_color",
                entity_id=row.id,
                new_values=self._color_snapshot(row),
            )
            return InkColorResponse.model_validate(row)

    async def update_color(
        self,
        color_id: UUID,
        payload: InkColorUpdate,
        *,
        actor_user_id: UUID,
    ) -> InkColorResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self.colors.get(color_id)
            if existing is None:
                raise ResourceNotFoundError("Ink color not found")
            old = self._color_snapshot(existing)
            try:
                updated = await self.colors.update(color_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("An ink color with this name already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Ink color not found")
            new = self._color_snapshot(updated)
            if audit_field_changes(old, new):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="ink_color",
                    entity_id=updated.id,
                    old_values=old,
                    new_values=new,
                )
            return InkColorResponse.model_validate(updated)

    async def delete_color(
        self,
        color_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> InkColorResponse:
        async with transaction(self.session):
            if await self.colors.count_lines(color_id) > 0:
                raise ValidationError("Cannot delete a color that is used on ink lines")
            existing = await self.colors.get(color_id)
            if existing is None:
                raise ResourceNotFoundError("Ink color not found")
            deleted = await self.colors.soft_delete(color_id)
            if deleted is None:
                raise ResourceNotFoundError("Ink color not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="ink_color",
                entity_id=existing.id,
                old_values=self._color_snapshot(existing),
            )
            return InkColorResponse.model_validate(deleted)

    async def color_usage(self, color_id: UUID, *, permissions: frozenset[str]) -> InkColorUsageResponse:
        color = await self.colors.get(color_id)
        if color is None:
            raise ResourceNotFoundError("Ink color not found")
        can_view_price = self._can_view_price(permissions)
        line_rows = await self.lines.list_for_color(color_id)
        companies_with_stock: set[UUID] = set()
        usage_lines: list[InkColorUsageLine] = []
        for line in line_rows:
            sheet = await self.sheets.get(line.ink_sheet_id)
            if sheet is None:
                continue
            company = await self._require_company(sheet.company_id)
            brand = await self.brands.get(line.brand_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit = units.get(line.drum_unit_id)
            drums = line.drum_count or Decimal("0")
            qty = line.total_qty or Decimal("0")
            if drums > 0 or qty > 0:
                companies_with_stock.add(sheet.company_id)
            usage_lines.append(
                InkColorUsageLine(
                    ink_line_id=line.id,
                    ink_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    brand_id=line.brand_id,
                    brand_name=brand.name if brand else "",
                    drum_count=self._display_decimal(drums) or Decimal("0"),
                    drum_qty=self._display_decimal(line.drum_qty) or Decimal("0"),
                    drum_unit_code=unit.code if unit else "",
                    total_qty=self._display_decimal(qty) or Decimal("0"),
                    ink_rate=self._display_decimal(line.ink_rate) if can_view_price else None,
                    total_rate=self._display_decimal(line.total_rate) if can_view_price else None,
                )
            )
        return InkColorUsageResponse(
            color=InkColorResponse.model_validate(color),
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
    ) -> tuple[list[InkBrandResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.brands.list(page=page, common_filter=common_filter, filters=filters or None)
        return [InkBrandResponse.model_validate(row) for row in rows], total

    async def create_brand(self, payload: InkBrandCreate) -> InkBrandResponse:
        async with transaction(self.session):
            try:
                row = await self.brands.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("An ink brand with this name already exists") from exc
            return InkBrandResponse.model_validate(row)

    async def update_brand(self, brand_id: UUID, payload: InkBrandUpdate) -> InkBrandResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            try:
                updated = await self.brands.update(brand_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("An ink brand with this name already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Ink brand not found")
            return InkBrandResponse.model_validate(updated)

    async def delete_brand(self, brand_id: UUID) -> InkBrandResponse:
        async with transaction(self.session):
            if await self.brands.count_lines(brand_id) > 0:
                raise ValidationError("Cannot delete a brand that is used on ink lines")
            deleted = await self.brands.soft_delete(brand_id)
            if deleted is None:
                raise ResourceNotFoundError("Ink brand not found")
            return InkBrandResponse.model_validate(deleted)

    # Sheets and lines

    async def list_line_items(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
        permissions: frozenset[str],
    ) -> tuple[list[InkLineListItem], int]:
        line_rows, total = await self.lines.list_inventory(
            page=page,
            common_filter=common_filter,
            company_id=company_id,
        )
        can_view_price = self._can_view_price(permissions)
        sheet_cache: dict[UUID, InkSheet] = {}
        company_cache: dict[UUID, Company] = {}
        items: list[InkLineListItem] = []
        for line in line_rows:
            sheet = sheet_cache.get(line.ink_sheet_id)
            if sheet is None:
                sheet = await self.sheets.get(line.ink_sheet_id)
                if sheet is None:
                    continue
                sheet_cache[line.ink_sheet_id] = sheet
            company = company_cache.get(sheet.company_id)
            if company is None:
                company = await self._require_company(sheet.company_id)
                company_cache[sheet.company_id] = company
            line_resp = await self._line_response(line, can_view_price=can_view_price)
            items.append(
                InkLineListItem(
                    ink_sheet_id=sheet.id,
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
    ) -> tuple[list[InkSheetListItem], int]:
        filters: dict[str, object] = {}
        if company_id is not None:
            filters["company_id"] = company_id
        rows, total = await self.sheets.list(page=page, common_filter=common_filter, filters=filters or None)
        items: list[InkSheetListItem] = []
        for sheet in rows:
            company = await self._require_company(sheet.company_id)
            line_rows = await self.lines.list_for_sheet(sheet.id)
            total_drums = sum((line.drum_count or Decimal("0") for line in line_rows), Decimal("0"))
            total_qty = sum((line.total_qty or Decimal("0") for line in line_rows), Decimal("0"))
            items.append(
                InkSheetListItem(
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

    async def get_sheet(self, sheet_id: UUID, *, permissions: frozenset[str]) -> InkSheetResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Ink sheet not found")
        return await self._sheet_response(sheet, can_view_price=self._can_view_price(permissions))

    async def create_sheet(
        self,
        payload: InkSheetCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> InkSheetResponse:
        await self._require_company(payload.company_id)
        existing = await self.sheets.get_by_company(payload.company_id)
        if existing is not None:
            raise DuplicateResourceError(
                "An ink sheet already exists for this company",
                details={"existing_id": str(existing.id)},
            )
        can_view_price = self._can_view_price(permissions)
        async with transaction(self.session):
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
                entity_type="ink_sheet",
                entity_id=refreshed.id,
                new_values=await self._sheet_audit_snapshot(refreshed),
            )
            return await self._sheet_response(refreshed, can_view_price=can_view_price)

    async def update_sheet(
        self,
        sheet_id: UUID,
        payload: InkSheetUpdate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> InkSheetResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Ink sheet not found")
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
                    entity_type="ink_sheet",
                    entity_id=refreshed.id,
                    old_values=old_snapshot,
                    new_values=new_snapshot,
                )
            return await self._sheet_response(refreshed, can_view_price=can_view_price)

    async def delete_sheet(self, sheet_id: UUID, *, actor_user_id: UUID) -> InkSheetResponse:
        async with transaction(self.session):
            sheet = await self.sheets.get(sheet_id)
            if sheet is None:
                raise ResourceNotFoundError("Ink sheet not found")
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
                entity_type="ink_sheet",
                entity_id=sheet.id,
                old_values=old_snapshot,
            )
            return await self._sheet_response(deleted, can_view_price=True)

    async def _sync_lines(
        self,
        sheet: InkSheet,
        payloads: list[InkLineUpsert],
        *,
        actor_user_id: UUID,
        can_view_price: bool,
        is_create: bool,
    ) -> None:
        default_unit = await self._default_kg_unit_id()
        existing = {row.id: row for row in await self.lines.list_for_sheet(sheet.id)}
        seen_ids: set[UUID] = set()
        today = date.today()

        for item in payloads:
            drum_unit_id = item.drum_unit_id or default_unit
            await self._require_unit(drum_unit_id)
            await self._require_brand_color(item.brand_id, item.color_id)
            if item.ink_rate is not None and not can_view_price:
                raise ValidationError("You do not have permission to set ink rate")

            total_qty, total_rate = self._line_totals(item.drum_count, item.drum_qty, item.ink_rate)

            if item.id is None:
                try:
                    line = await self.lines.create(
                        {
                            "ink_sheet_id": sheet.id,
                            "brand_id": item.brand_id,
                            "color_id": item.color_id,
                            "drum_count": item.drum_count,
                            "drum_qty": item.drum_qty,
                            "drum_unit_id": drum_unit_id,
                            "total_qty": total_qty,
                            "ink_rate": item.ink_rate,
                            "total_rate": total_rate,
                        }
                    )
                except IntegrityError as exc:
                    raise DuplicateResourceError(
                        "This brand and color combination already exists on the sheet"
                    ) from exc
                await self.movements.create(
                    {
                        "ink_line_id": line.id,
                        "movement_date": today,
                        "direction": MaterialMovementDirection.OPENING.value,
                        "drums": item.drum_count,
                        "quantity": total_qty,
                        "created_by": actor_user_id,
                        "ink_rate": item.ink_rate,
                    }
                )
                continue

            seen_ids.add(item.id)
            line = existing.get(item.id)
            if line is None or line.ink_sheet_id != sheet.id:
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
                        "ink_line_id": line.id,
                        "movement_date": today,
                        "direction": MaterialMovementDirection.IN.value,
                        "drums": drum_delta,
                        "quantity": qty_delta,
                        "created_by": actor_user_id,
                        "ink_rate": item.ink_rate,
                    }
                )

            try:
                await self.lines.update(
                    line.id,
                    {
                        "brand_id": item.brand_id,
                        "color_id": item.color_id,
                        "drum_count": item.drum_count,
                        "drum_qty": item.drum_qty,
                        "drum_unit_id": drum_unit_id,
                        "total_qty": total_qty,
                        "ink_rate": item.ink_rate,
                        "total_rate": total_rate,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "This brand and color combination already exists on the sheet"
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

    async def _require_brand_color(self, brand_id: UUID, color_id: UUID) -> None:
        brand = await self.brands.get(brand_id)
        if brand is None:
            raise ResourceNotFoundError("Ink brand not found")
        color = await self.colors.get(color_id)
        if color is None:
            raise ResourceNotFoundError("Ink color not found")

    async def stock_out(
        self,
        sheet_id: UUID,
        payload: InkStockOutCreate,
        *,
        actor_user_id: UUID,
    ) -> InkLineResponse:
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Ink sheet not found")
        line = await self.lines.get(payload.ink_line_id)
        if line is None or line.ink_sheet_id != sheet.id:
            raise ResourceNotFoundError("Ink line not found")

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
            _, total_rate = self._line_totals(new_drums, line.drum_qty or Decimal("0"), line.ink_rate)
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
                    "ink_line_id": line.id,
                    "movement_date": movement_date,
                    "direction": MaterialMovementDirection.OUT.value,
                    "drums": payload.drums,
                    "quantity": payload.quantity,
                    "note": payload.note,
                    "created_by": actor_user_id,
                    "ink_rate": line.ink_rate,
                }
            )
            brand = await self.brands.get(line.brand_id)
            color = await self.colors.get(line.color_id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="ink_sheet",
                entity_id=sheet.id,
                new_values={
                    "event_kind": "stock_out",
                    "line": f"{brand.name if brand else ''} · {color.name if color else ''}",
                    "drums_out": jsonable_value(payload.drums),
                    "quantity_out": jsonable_value(payload.quantity),
                    "note": payload.note,
                },
            )
            return await self._line_response(line, can_view_price=True)

    async def day_report(
        self,
        *,
        report_date: date,
        permissions: frozenset[str],
    ) -> list[InkDayReportRow]:
        can_view_price = self._can_view_price(permissions)
        active_lines = await self.lines.list_active_lines()
        if not active_lines:
            return []

        day_totals = await self.movements.day_totals(report_date)
        rows: list[InkDayReportRow] = []

        for line in active_lines:
            in_d, in_q, out_d, out_q = day_totals.get(
                line.id, (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
            )
            closing_drums, closing_qty = await self.movements.sum_through_date(line.id, report_date)
            if (
                in_d == 0
                and in_q == 0
                and out_d == 0
                and out_q == 0
                and closing_drums == 0
                and closing_qty == 0
            ):
                continue

            sheet = await self.sheets.get(line.ink_sheet_id)
            if sheet is None:
                continue
            company = await self._require_company(sheet.company_id)
            brand = await self.brands.get(line.brand_id)
            color = await self.colors.get(line.color_id)
            units = await self._load_unit_codes([line.drum_unit_id])
            unit = units.get(line.drum_unit_id)

            rows.append(
                InkDayReportRow(
                    ink_line_id=line.id,
                    ink_sheet_id=sheet.id,
                    company_id=sheet.company_id,
                    company_name=company.name,
                    brand_id=line.brand_id,
                    brand_name=brand.name if brand else "",
                    color_id=line.color_id,
                    color_name=color.name if color else "",
                    hex_code=color.hex_code if color else None,
                    drum_unit_code=unit.code if unit else "",
                    in_drums=self._display_decimal(in_d) or Decimal("0"),
                    in_qty=self._display_decimal(in_q) or Decimal("0"),
                    out_drums=self._display_decimal(out_d) or Decimal("0"),
                    out_qty=self._display_decimal(out_q) or Decimal("0"),
                    closing_drums=self._display_decimal(closing_drums) or Decimal("0"),
                    closing_qty=self._display_decimal(closing_qty) or Decimal("0"),
                    ink_rate=self._display_decimal(line.ink_rate) if can_view_price else None,
                )
            )
        rows.sort(key=lambda row: (row.company_name, row.brand_name, row.color_name))
        return rows

    # Files

    def _assert_file_permission(self, permissions: frozenset[str], slot: str, action: str) -> None:
        mapping = {
            "read": _SLOT_READ,
            "create": _SLOT_CREATE,
            "update": _SLOT_UPDATE,
            "delete": _SLOT_DELETE,
        }[action]
        perm = mapping.get(slot)
        if perm is None or not has_permission(permissions, perm):
            raise PermissionDeniedError("You do not have permission to manage this file")

    async def upload_file(
        self,
        sheet_id: UUID,
        slot: str,
        upload: UploadFile,
        *,
        actor_user_id: UUID | None = None,
        permissions: frozenset[str],
    ) -> InkSheetResponse:
        if slot not in INK_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Ink sheet not found")
        has_existing = self._slot_has_file(sheet, slot)
        self._assert_file_permission(permissions, slot, "update" if has_existing else "create")
        raw = await upload.read()
        validated = validate_upload(
            raw,
            filename=upload.filename,
            max_upload_size_mb=self.settings.max_upload_size_mb,
            allowed_mime_types=INK_ALLOWED_MIME,
        )
        new_key = f"inks/{sheet_id}/{slot}/{uuid.uuid4().hex}"

        async with transaction(self.session):
            sheet = await self.sheets.get(sheet_id)
            if sheet is None:
                raise ResourceNotFoundError("Ink sheet not found")
            if self.storage is not None:
                await self.storage.put(new_key, validated.content, validated.content_type)
            else:
                ink_storage.write_ink_file(new_key, validated.content)
            old_key = self._slot_storage_key(sheet, slot)
            self._apply_file_meta(
                sheet,
                slot,
                new_key,
                validated.filename,
                validated.content_type,
                validated.size_bytes,
            )
            await self.session.flush()
            if old_key and old_key != new_key:
                if self.storage is not None:
                    await self.storage.delete(old_key)
                else:
                    ink_storage.delete_ink_file(old_key)
            if actor_user_id is not None:
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="ink_sheet",
                    entity_id=sheet.id,
                    new_values={
                        "event_kind": "attachment",
                        "slot": slot,
                        "original_filename": validated.filename,
                        "storage_key": new_key,
                    },
                )
        return await self._sheet_response(sheet, can_view_price=self._can_view_price(permissions))

    async def read_file(
        self,
        sheet_id: UUID,
        slot: str,
        *,
        permissions: frozenset[str],
    ) -> tuple[bytes, str]:
        if slot not in INK_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        self._assert_file_permission(permissions, slot, "read")
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Ink sheet not found")
        key = self._slot_storage_key(sheet, slot)
        if not key:
            raise ResourceNotFoundError("File not found")
        if self.storage is not None:
            return await self.storage.get(key)
        return ink_storage.read_ink_file(key)

    async def read_history_attachment(
        self,
        sheet_id: UUID,
        audit_log_id: UUID,
        *,
        permissions: frozenset[str],
    ) -> tuple[bytes, str]:
        from app.common.models.audit_log import AuditLog

        result = await self.session.execute(
            select(AuditLog).where(AuditLog.id == audit_log_id)
        )
        row = result.scalar_one_or_none()
        if row is None or row.entity_type != "ink_sheet" or row.entity_id != sheet_id:
            raise ResourceNotFoundError("Attachment not found")
        new_values = row.new_values or {}
        if new_values.get("event_kind") != "attachment":
            raise ResourceNotFoundError("Attachment not found")
        slot = str(new_values.get("slot") or "")
        if slot not in INK_FILE_SLOTS:
            raise ResourceNotFoundError("Attachment not found")
        self._assert_file_permission(permissions, slot, "read")
        storage_key = new_values.get("storage_key")
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise ResourceNotFoundError("Attachment not found")
        key = storage_key.strip()
        prefix = f"inks/{sheet_id}/"
        if not key.startswith(prefix):
            raise ResourceNotFoundError("Attachment not found")
        if self.storage is not None:
            return await self.storage.get(key)
        return ink_storage.read_ink_file(key)

    async def delete_file(
        self,
        sheet_id: UUID,
        slot: str,
        *,
        actor_user_id: UUID | None = None,
        permissions: frozenset[str],
    ) -> InkSheetResponse:
        if slot not in INK_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        self._assert_file_permission(permissions, slot, "delete")
        sheet = await self.sheets.get(sheet_id)
        if sheet is None:
            raise ResourceNotFoundError("Ink sheet not found")
        async with transaction(self.session):
            key = self._slot_storage_key(sheet, slot)
            filename = (
                sheet.product_image_filename if slot == "product_image" else sheet.ink_image_filename
            )
            self._clear_file_meta(sheet, slot)
            await self.session.flush()
            if key and self.storage is not None:
                await self.storage.delete(key)
            elif key:
                ink_storage.delete_ink_file(key)
            if actor_user_id is not None and key:
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="ink_sheet",
                    entity_id=sheet.id,
                    new_values={
                        "event_kind": "attachment",
                        "slot": slot,
                        "original_filename": filename,
                        "storage_key": key,
                        "deleted": True,
                    },
                )
        return await self._sheet_response(sheet, can_view_price=True)

    @staticmethod
    def _slot_storage_key(row: InkSheet, slot: str) -> str | None:
        if slot == "product_image":
            return row.product_image_storage_key
        return row.ink_image_storage_key

    @staticmethod
    def _slot_has_file(row: InkSheet, slot: str) -> bool:
        return bool(InkService._slot_storage_key(row, slot))

    @staticmethod
    def _apply_file_meta(
        row: InkSheet,
        slot: str,
        key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> None:
        if slot == "product_image":
            row.product_image_storage_key = key
            row.product_image_filename = filename
            row.product_image_content_type = content_type
            row.product_image_size_bytes = size_bytes
            return
        row.ink_image_storage_key = key
        row.ink_image_filename = filename
        row.ink_image_content_type = content_type
        row.ink_image_size_bytes = size_bytes

    @staticmethod
    def _clear_file_meta(row: InkSheet, slot: str) -> None:
        if slot == "product_image":
            row.product_image_storage_key = None
            row.product_image_filename = None
            row.product_image_content_type = None
            row.product_image_size_bytes = None
            return
        row.ink_image_storage_key = None
        row.ink_image_filename = None
        row.ink_image_content_type = None
        row.ink_image_size_bytes = None
