"""Inventory business logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter, audit_field_changes
from app.core.enums import (
    INVENTORY_MODULE,
    AuditAction,
    MaterialCategoryKind,
    MaterialMovementDirection,
)
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
from app.inventory.catalog import MATERIAL_VIEW_PRICE
from app.inventory.models import InventoryUnit, MaterialCategory, MaterialMovement
from app.inventory.pricing import compute_avg_price, merge_purchase_price_stats
from app.inventory.repository import (
    CategoryRepository,
    CompanyLookupRepository,
    MaterialHistoryRepository,
    MovementRepository,
    UnitLookupRepository,
    UnitRepository,
)
from app.inventory.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    DayReportRow,
    MaterialCreate,
    MaterialHistoryEntry,
    MaterialHistorySummary,
    MaterialResponse,
    MaterialUpdate,
    MicronCreate,
    MicronResponse,
    MicronUpdate,
    MovementCreate,
    MovementResponse,
    UnitCreate,
    UnitResponse,
    UnitUpdate,
)


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.units = UnitRepository(session)
        self.categories = CategoryRepository(session)
        self.unit_lookup = UnitLookupRepository(session)
        self.companies = CompanyLookupRepository(session)
        self.movements = MovementRepository(session)
        self.material_history_repo = MaterialHistoryRepository(session)
        self.audit = AuditWriter(session)

    @staticmethod
    def _can_view_price(permissions: frozenset[str]) -> bool:
        return has_permission(permissions, MATERIAL_VIEW_PRICE)

    _DISPLAY_QUANTUM = Decimal("0.01")

    @classmethod
    def _display_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(cls._DISPLAY_QUANTUM)

    @classmethod
    def _format_decimal(cls, value: Decimal) -> str:
        quantized = cls._display_decimal(value) or Decimal("0")
        return f"{quantized:.2f}"

    @classmethod
    def _size_label(cls, size: Decimal | None, unit_code: str) -> str:
        if size is None:
            return ""
        code = unit_code.strip()
        amount = cls._format_decimal(size)
        return f"{amount} {code}".strip() if code else amount

    async def _unit_by_code(self, code: str) -> InventoryUnit:
        row = await self.units.get_by_code(code)
        if row is None:
            raise ValidationError(
                f"Default unit '{code}' is not configured. Run bootstrap to seed inventory units.",
            )
        return row

    async def _require_unit(self, unit_id: UUID) -> InventoryUnit:
        row = await self.units.get(unit_id)
        if row is None:
            raise ResourceNotFoundError("Unit not found")
        return row

    async def _require_product(self, category_id: UUID) -> MaterialCategory:
        row = await self.categories.get(category_id)
        if row is None:
            raise ResourceNotFoundError("Product not found")
        if row.kind_enum != MaterialCategoryKind.PRODUCT:
            raise ValidationError("Expected a product")
        return row

    async def _require_micron(self, category_id: UUID) -> MaterialCategory:
        row = await self.categories.get(category_id)
        if row is None:
            raise ResourceNotFoundError("Micron not found")
        if row.kind_enum != MaterialCategoryKind.MICRON:
            raise ValidationError("Expected a micron")
        return row

    async def _require_sku(self, category_id: UUID) -> MaterialCategory:
        row = await self.categories.get(category_id)
        if row is None:
            raise ResourceNotFoundError("Material not found")
        if row.kind_enum != MaterialCategoryKind.SKU:
            raise ValidationError("Expected a material SKU")
        return row

    async def _require_company(self, company_id: UUID) -> Company:
        row = await self.session.get(Company, company_id)
        if row is None or row.deleted_at is not None:
            raise ValidationError("Company not found")
        return row

    async def _company_name_map(self, company_ids: list[UUID]) -> dict[UUID, str]:
        rows = await self.companies.companies_by_ids(company_ids)
        return {company_id: row.name for company_id, row in rows.items()}

    async def _category_response(self, row: MaterialCategory) -> CategoryResponse:
        company_name = ""
        if row.company_id:
            names = await self._company_name_map([row.company_id])
            company_name = names.get(row.company_id, "")
        return CategoryResponse(
            id=row.id,
            company_id=row.company_id,
            company_name=company_name,
            name=row.name,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _category_responses(self, rows: list[MaterialCategory]) -> list[CategoryResponse]:
        company_ids = [row.company_id for row in rows if row.company_id]
        names = await self._company_name_map(company_ids)
        return [
            CategoryResponse(
                id=row.id,
                company_id=row.company_id,
                company_name=names.get(row.company_id, "") if row.company_id else "",
                name=row.name,
                is_active=row.is_active,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def _sku_hierarchy(
        self,
        sku: MaterialCategory,
    ) -> tuple[MaterialCategory | None, MaterialCategory | None]:
        micron = await self.categories.get(sku.parent_id) if sku.parent_id else None
        product = None
        if micron and micron.parent_id:
            product = await self.categories.get(micron.parent_id)
        return micron, product

    @staticmethod
    def _apply_price_material(
        response: MaterialResponse,
        *,
        can_view_price: bool,
    ) -> MaterialResponse:
        if can_view_price:
            return response
        return response.model_copy(
            update={
                "price_per_unit": None,
                "price_unit_id": None,
                "price_unit_code": None,
                "avg_price_per_unit": None,
            },
        )

    @staticmethod
    def _apply_price_micron(
        response: MicronResponse,
        *,
        can_view_price: bool,
    ) -> MicronResponse:
        if can_view_price:
            return response
        return response.model_copy(update={"price_per_unit": None, "avg_price_per_unit": None})

    async def _micron_response(
        self,
        row: MaterialCategory,
        *,
        can_view_price: bool,
    ) -> MicronResponse:
        product = await self.categories.get(row.parent_id) if row.parent_id else None
        company_name = ""
        if product and product.company_id:
            names = await self._company_name_map([product.company_id])
            company_name = names.get(product.company_id, "")
        price_unit_code = ""
        if row.price_unit_id:
            units = await self.unit_lookup.get_units_by_ids([row.price_unit_id])
            unit = units.get(row.price_unit_id)
            price_unit_code = unit.code if unit else ""
        avg_prices = await self._avg_prices_by_micron_ids([row.id])
        response = MicronResponse(
            id=row.id,
            product_id=row.parent_id or row.id,
            product_name=product.name if product else "",
            company_id=product.company_id if product else None,
            company_name=company_name,
            name=row.name,
            price_per_unit=self._display_decimal(row.price_per_unit),
            price_unit_id=row.price_unit_id,
            price_unit_code=price_unit_code,
            avg_price_per_unit=avg_prices.get(row.id),
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        return self._apply_price_micron(response, can_view_price=can_view_price)

    async def _micron_responses(
        self,
        rows: list[MaterialCategory],
        *,
        can_view_price: bool,
    ) -> list[MicronResponse]:
        product_ids = [row.parent_id for row in rows if row.parent_id]
        products = await self.categories.get_by_ids(product_ids)
        company_ids = [p.company_id for p in products.values() if p.company_id]
        company_names = await self._company_name_map(company_ids)
        price_unit_ids = [row.price_unit_id for row in rows if row.price_unit_id]
        units = await self.unit_lookup.get_units_by_ids(price_unit_ids)
        avg_prices = await self._avg_prices_by_micron_ids([row.id for row in rows])
        result: list[MicronResponse] = []
        for row in rows:
            product = products.get(row.parent_id) if row.parent_id else None
            price_unit = units.get(row.price_unit_id) if row.price_unit_id else None
            product_company_id = product.company_id if product else None
            response = MicronResponse(
                id=row.id,
                product_id=row.parent_id or row.id,
                product_name=product.name if product else "",
                company_id=product_company_id,
                company_name=company_names.get(product_company_id, "")
                if product_company_id
                else "",
                name=row.name,
                price_per_unit=self._display_decimal(row.price_per_unit),
                price_unit_id=row.price_unit_id,
                price_unit_code=price_unit.code if price_unit else "",
                avg_price_per_unit=avg_prices.get(row.id),
                is_active=row.is_active,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            result.append(self._apply_price_micron(response, can_view_price=can_view_price))
        return result

    async def _avg_prices_by_micron_ids(
        self,
        micron_ids: list[UUID],
    ) -> dict[UUID, Decimal | None]:
        unique = list(dict.fromkeys(micron_ids))
        if not unique:
            return {}
        sku_by_micron = await self.categories.sku_ids_grouped_by_micron_ids(unique)
        all_sku_ids = [sku_id for sku_ids in sku_by_micron.values() for sku_id in sku_ids]
        stats_map = await self.movements.purchase_price_stats_by_category_ids(all_sku_ids)
        return {
            micron_id: self._display_decimal(
                compute_avg_price(
                    merge_purchase_price_stats(
                        [stats_map.get(sku_id) for sku_id in sku_by_micron.get(micron_id, [])],
                    ),
                ),
            )
            for micron_id in unique
        }

    async def _avg_prices_by_sku_ids(self, sku_ids: list[UUID]) -> dict[UUID, Decimal | None]:
        stats_map = await self.movements.purchase_price_stats_by_category_ids(sku_ids)
        return {
            sku_id: self._display_decimal(compute_avg_price(stats_map.get(sku_id)))
            for sku_id in sku_ids
        }

    async def _material_response(
        self,
        row: MaterialCategory,
        *,
        can_view_price: bool,
    ) -> MaterialResponse:
        micron, product = await self._sku_hierarchy(row)
        unit_ids = [uid for uid in (row.unit_id, row.size_unit_id) if uid]
        if micron and micron.price_unit_id:
            unit_ids.append(micron.price_unit_id)
        units = await self.unit_lookup.get_units_by_ids(unit_ids)
        unit = units.get(row.unit_id) if row.unit_id else None
        size_unit = units.get(row.size_unit_id) if row.size_unit_id else None
        price_unit = units.get(micron.price_unit_id) if micron and micron.price_unit_id else None
        size_val = self._display_decimal(row.size or Decimal("0")) or Decimal("0")
        size_code = size_unit.code if size_unit else ""
        company_id = product.company_id if product else None
        company_name = ""
        if company_id:
            names = await self._company_name_map([company_id])
            company_name = names.get(company_id, "")
        avg_prices = await self._avg_prices_by_sku_ids([row.id])
        response = MaterialResponse(
            id=row.id,
            company_id=company_id,
            company_name=company_name,
            product_id=product.id if product else row.id,
            product_name=product.name if product else "",
            micron_id=micron.id if micron else row.id,
            micron_name=micron.name if micron else "",
            size=size_val,
            size_unit_id=row.size_unit_id or row.id,
            size_unit_code=size_code,
            size_label=self._size_label(size_val, size_code),
            unit_id=row.unit_id,
            unit_code=unit.code if unit else "",
            unit_name=unit.name if unit else "",
            name=row.name,
            rolls_on_hand=self._display_decimal(row.rolls_on_hand or Decimal("0")) or Decimal("0"),
            total_kg=self._display_decimal(row.total_kg or Decimal("0")) or Decimal("0"),
            price_per_unit=self._display_decimal(micron.price_per_unit) if micron else None,
            price_unit_id=micron.price_unit_id if micron else None,
            price_unit_code=price_unit.code if price_unit else None,
            avg_price_per_unit=avg_prices.get(row.id),
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        return self._apply_price_material(response, can_view_price=can_view_price)

    async def _material_responses(
        self,
        rows: list[MaterialCategory],
        *,
        can_view_price: bool,
    ) -> list[MaterialResponse]:
        micron_ids = [row.parent_id for row in rows if row.parent_id]
        microns = await self.categories.get_by_ids(micron_ids)
        product_ids = [m.parent_id for m in microns.values() if m.parent_id]
        products = await self.categories.get_by_ids(product_ids)
        company_ids = [p.company_id for p in products.values() if p.company_id]
        company_names = await self._company_name_map(company_ids)
        unit_ids: list[UUID] = []
        for row in rows:
            if row.unit_id:
                unit_ids.append(row.unit_id)
            if row.size_unit_id:
                unit_ids.append(row.size_unit_id)
        for micron in microns.values():
            if micron.price_unit_id:
                unit_ids.append(micron.price_unit_id)
        units = await self.unit_lookup.get_units_by_ids(unit_ids)
        avg_prices = await self._avg_prices_by_sku_ids([row.id for row in rows])
        result: list[MaterialResponse] = []
        for row in rows:
            micron = microns.get(row.parent_id) if row.parent_id else None
            product = products.get(micron.parent_id) if micron and micron.parent_id else None
            unit = units.get(row.unit_id) if row.unit_id else None
            size_unit = units.get(row.size_unit_id) if row.size_unit_id else None
            price_unit = (
                units.get(micron.price_unit_id) if micron and micron.price_unit_id else None
            )
            size_code = size_unit.code if size_unit else ""
            size_val = self._display_decimal(row.size or Decimal("0")) or Decimal("0")
            company_id = product.company_id if product else None
            response = MaterialResponse(
                id=row.id,
                company_id=company_id,
                company_name=company_names.get(company_id, "") if company_id else "",
                product_id=product.id if product else row.id,
                product_name=product.name if product else "",
                micron_id=micron.id if micron else row.id,
                micron_name=micron.name if micron else "",
                size=size_val,
                size_unit_id=row.size_unit_id or row.id,
                size_unit_code=size_code,
                size_label=self._size_label(size_val, size_code),
                unit_id=row.unit_id,
                unit_code=unit.code if unit else "",
                unit_name=unit.name if unit else "",
                name=row.name,
                rolls_on_hand=self._display_decimal(row.rolls_on_hand or Decimal("0"))
                or Decimal("0"),
                total_kg=self._display_decimal(row.total_kg or Decimal("0")) or Decimal("0"),
                price_per_unit=self._display_decimal(micron.price_per_unit) if micron else None,
                price_unit_id=micron.price_unit_id if micron else None,
                price_unit_code=price_unit.code if price_unit else None,
                avg_price_per_unit=avg_prices.get(row.id),
                is_active=row.is_active,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            result.append(self._apply_price_material(response, can_view_price=can_view_price))
        return result

    @staticmethod
    def _assert_non_negative(rolls: Decimal, kg: Decimal) -> None:
        if rolls < 0 or kg < 0:
            raise InsufficientStockError(
                "Insufficient stock for this movement.",
                details={
                    "available_rolls": str(max(rolls, Decimal("0"))),
                    "available_kg": str(max(kg, Decimal("0"))),
                },
            )

    @staticmethod
    def _movement_delta(
        direction: MaterialMovementDirection, rolls: Decimal, kg: Decimal
    ) -> tuple[Decimal, Decimal]:
        if direction == MaterialMovementDirection.OUT:
            return -rolls, -kg
        return rolls, kg

    async def _movement_snapshot_fields(self, sku: MaterialCategory) -> dict[str, object]:
        micron, product = await self._sku_hierarchy(sku)
        return {
            "company_id": product.company_id if product else None,
            "price_per_unit": micron.price_per_unit if micron else None,
            "price_unit_id": micron.price_unit_id if micron else None,
        }

    async def _apply_movement_to_category(
        self,
        category: MaterialCategory,
        direction: MaterialMovementDirection,
        rolls: Decimal,
        kilograms: Decimal,
    ) -> None:
        delta_rolls, delta_kg = self._movement_delta(direction, rolls, kilograms)
        current_rolls = category.rolls_on_hand or Decimal("0")
        current_kg = category.total_kg or Decimal("0")
        new_rolls = current_rolls + delta_rolls
        new_kg = current_kg + delta_kg
        self._assert_non_negative(new_rolls, new_kg)
        category.rolls_on_hand = new_rolls
        category.total_kg = new_kg

    @staticmethod
    def _product_criteria():
        return [MaterialCategory.category_kind == MaterialCategoryKind.PRODUCT.value]

    @staticmethod
    def _micron_criteria():
        return [MaterialCategory.category_kind == MaterialCategoryKind.MICRON.value]

    @staticmethod
    def _sku_criteria():
        return [MaterialCategory.category_kind == MaterialCategoryKind.SKU.value]

    # Units

    async def list_units(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[UnitResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.units.list(
            page=page, common_filter=common_filter, filters=filters or None
        )
        return [UnitResponse.model_validate(row) for row in rows], total

    async def list_units_for_export(
        self,
        *,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> list[UnitResponse]:
        from app.common.export.fetch import assert_export_total, export_page

        rows, total = await self.list_units(
            page=export_page(),
            common_filter=common_filter,
            is_active=is_active,
        )
        assert_export_total(total)
        return rows

    async def get_unit(self, unit_id: UUID) -> UnitResponse:
        row = await self._require_unit(unit_id)
        return UnitResponse.model_validate(row)

    async def create_unit(self, payload: UnitCreate) -> UnitResponse:
        async with transaction(self.session):
            try:
                row = await self.units.create(payload.model_dump())
            except IntegrityError as exc:
                raise DuplicateResourceError("A unit with this code already exists") from exc
            return UnitResponse.model_validate(row)

    async def update_unit(self, unit_id: UUID, payload: UnitUpdate) -> UnitResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            try:
                updated = await self.units.update(unit_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A unit with this code already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Unit not found")
            return UnitResponse.model_validate(updated)

    async def delete_unit(self, unit_id: UUID) -> UnitResponse:
        async with transaction(self.session):
            deleted = await self.units.soft_delete(unit_id)
            if deleted is None:
                raise ResourceNotFoundError("Unit not found")
            return UnitResponse.model_validate(deleted)

    # Products

    async def list_categories(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
        roots_only: bool | None = True,
        company_id: UUID | None = None,
    ) -> tuple[list[CategoryResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        if company_id is not None:
            filters["company_id"] = company_id
        extra = self._product_criteria() if roots_only is not False else None
        rows, total = await self.categories.list(
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra,
        )
        return await self._category_responses(list(rows)), total

    async def get_category(self, category_id: UUID) -> CategoryResponse:
        row = await self._require_product(category_id)
        return await self._category_response(row)

    async def create_category(self, payload: CategoryCreate) -> CategoryResponse:
        await self._require_company(payload.company_id)
        async with transaction(self.session):
            try:
                row = await self.categories.create(
                    {
                        "name": payload.name,
                        "is_active": payload.is_active,
                        "parent_id": None,
                        "company_id": payload.company_id,
                        "category_kind": MaterialCategoryKind.PRODUCT.value,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A product with this name already exists for this company",
                ) from exc
            return await self._category_response(row)

    async def update_category(self, category_id: UUID, payload: CategoryUpdate) -> CategoryResponse:
        await self._require_product(category_id)
        values = payload.model_dump(exclude_unset=True)
        if payload.company_id is not None:
            await self._require_company(payload.company_id)
        async with transaction(self.session):
            try:
                updated = await self.categories.update(category_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A product with this name already exists for this company",
                ) from exc
            if updated is None:
                raise ResourceNotFoundError("Product not found")
            return await self._category_response(updated)

    async def delete_category(self, category_id: UUID) -> CategoryResponse:
        await self._require_product(category_id)
        child_count = await self.categories.count_active_children(
            category_id,
            category_kind=MaterialCategoryKind.MICRON,
        )
        if child_count > 0:
            raise ValidationError("Remove microns under this product before deleting it")
        async with transaction(self.session):
            deleted = await self.categories.soft_delete(category_id)
            if deleted is None:
                raise ResourceNotFoundError("Product not found")
            return await self._category_response(deleted)

    # Microns

    async def list_microns(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        product_id: UUID | None = None,
        is_active: bool | None = None,
        permissions: frozenset[str],
    ) -> tuple[list[MicronResponse], int]:
        filters: dict[str, object] = {}
        if product_id is not None:
            filters["parent_id"] = product_id
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.categories.list(
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=self._micron_criteria(),
        )
        can_view_price = self._can_view_price(permissions)
        return await self._micron_responses(list(rows), can_view_price=can_view_price), total

    async def get_micron(self, micron_id: UUID, *, permissions: frozenset[str]) -> MicronResponse:
        row = await self._require_micron(micron_id)
        return await self._micron_response(row, can_view_price=self._can_view_price(permissions))

    async def create_micron(
        self,
        payload: MicronCreate,
        *,
        permissions: frozenset[str],
    ) -> MicronResponse:
        can_view_price = self._can_view_price(permissions)
        if payload.price_per_unit is not None and not can_view_price:
            raise PermissionDeniedError("You do not have permission to set price")
        await self._require_product(payload.product_id)
        price_unit_id = payload.price_unit_id
        if price_unit_id is None:
            price_unit_id = (await self._unit_by_code("kg")).id
        else:
            await self._require_unit(price_unit_id)
        async with transaction(self.session):
            try:
                row = await self.categories.create(
                    {
                        "parent_id": payload.product_id,
                        "category_kind": MaterialCategoryKind.MICRON.value,
                        "name": payload.name,
                        "price_per_unit": payload.price_per_unit,
                        "price_unit_id": price_unit_id,
                        "is_active": payload.is_active,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A micron with this name already exists for this product",
                ) from exc
            return await self._micron_response(row, can_view_price=can_view_price)

    async def update_micron(
        self,
        micron_id: UUID,
        payload: MicronUpdate,
        *,
        permissions: frozenset[str],
    ) -> MicronResponse:
        can_view_price = self._can_view_price(permissions)
        values = payload.model_dump(exclude_unset=True)
        if "price_per_unit" in values and not can_view_price:
            raise PermissionDeniedError("You do not have permission to set price")
        if payload.price_unit_id is not None:
            await self._require_unit(payload.price_unit_id)
        await self._require_micron(micron_id)
        async with transaction(self.session):
            try:
                updated = await self.categories.update(micron_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A micron with this name already exists for this product",
                ) from exc
            if updated is None:
                raise ResourceNotFoundError("Micron not found")
            return await self._micron_response(updated, can_view_price=can_view_price)

    async def delete_micron(
        self, micron_id: UUID, *, permissions: frozenset[str]
    ) -> MicronResponse:
        await self._require_micron(micron_id)
        child_count = await self.categories.count_active_children(
            micron_id,
            category_kind=MaterialCategoryKind.SKU,
        )
        if child_count > 0:
            raise ValidationError("Remove materials under this micron before deleting it")
        async with transaction(self.session):
            deleted = await self.categories.soft_delete(micron_id)
            if deleted is None:
                raise ResourceNotFoundError("Micron not found")
            return await self._micron_response(
                deleted, can_view_price=self._can_view_price(permissions)
            )

    # SKUs

    async def _material_query_parts(
        self,
        *,
        parent_id: UUID | None = None,
        product_id: UUID | None = None,
        is_active: bool | None = None,
        size: Decimal | None = None,
        rolls: Decimal | None = None,
        kg_lt: Decimal | None = None,
        kg_gt: Decimal | None = None,
        company_id: UUID | None = None,
    ) -> tuple[dict[str, object], list] | None:
        filters: dict[str, object] = {}
        if parent_id is not None:
            filters["parent_id"] = parent_id
        if is_active is not None:
            filters["is_active"] = is_active
        extra = list(self._sku_criteria())
        if size is not None:
            extra.append(MaterialCategory.size == size)
        if rolls is not None:
            extra.append(MaterialCategory.rolls_on_hand == rolls)
        if kg_lt is not None:
            extra.append(MaterialCategory.total_kg < kg_lt)
        if kg_gt is not None:
            extra.append(MaterialCategory.total_kg > kg_gt)
        micron_ids_filter: list[UUID] | None = None
        if company_id is not None:
            product_ids = await self.categories.product_ids_for_company(company_id)
            if not product_ids:
                return None
            micron_ids_filter = await self.categories.micron_ids_for_products(product_ids)
            if not micron_ids_filter:
                return None
        if product_id is not None:
            micron_ids = await self.categories.micron_ids_for_product(product_id)
            if not micron_ids:
                return None
            if micron_ids_filter is not None:
                micron_ids = [mid for mid in micron_ids if mid in micron_ids_filter]
                if not micron_ids:
                    return None
            extra.append(MaterialCategory.parent_id.in_(micron_ids))
        elif micron_ids_filter is not None:
            extra.append(MaterialCategory.parent_id.in_(micron_ids_filter))
        return filters, extra

    async def list_materials(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        parent_id: UUID | None = None,
        product_id: UUID | None = None,
        is_active: bool | None = None,
        size: Decimal | None = None,
        rolls: Decimal | None = None,
        kg_lt: Decimal | None = None,
        kg_gt: Decimal | None = None,
        company_id: UUID | None = None,
        permissions: frozenset[str],
    ) -> tuple[list[MaterialResponse], int]:
        query = await self._material_query_parts(
            parent_id=parent_id,
            product_id=product_id,
            is_active=is_active,
            size=size,
            rolls=rolls,
            kg_lt=kg_lt,
            kg_gt=kg_gt,
            company_id=company_id,
        )
        if query is None:
            return [], 0
        filters, extra = query
        rows, total = await self.categories.list(
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra,
        )
        can_view_price = self._can_view_price(permissions)
        return await self._material_responses(list(rows), can_view_price=can_view_price), total

    async def list_materials_for_export(
        self,
        *,
        common_filter: BaseFilter | None = None,
        parent_id: UUID | None = None,
        product_id: UUID | None = None,
        is_active: bool | None = None,
        size: Decimal | None = None,
        rolls: Decimal | None = None,
        kg_lt: Decimal | None = None,
        kg_gt: Decimal | None = None,
        company_id: UUID | None = None,
        permissions: frozenset[str],
    ) -> list[MaterialResponse]:
        from app.common.export.fetch import assert_export_total, export_page

        query = await self._material_query_parts(
            parent_id=parent_id,
            product_id=product_id,
            is_active=is_active,
            size=size,
            rolls=rolls,
            kg_lt=kg_lt,
            kg_gt=kg_gt,
            company_id=company_id,
        )
        if query is None:
            return []
        filters, extra = query
        rows, total = await self.categories.list(
            page=export_page(),
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra,
        )
        assert_export_total(total)
        can_view_price = self._can_view_price(permissions)
        return await self._material_responses(list(rows), can_view_price=can_view_price)

    async def get_material(
        self, material_id: UUID, *, permissions: frozenset[str]
    ) -> MaterialResponse:
        row = await self._require_sku(material_id)
        return await self._material_response(row, can_view_price=self._can_view_price(permissions))

    async def create_material(
        self,
        payload: MaterialCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> MaterialResponse:
        can_view_price = self._can_view_price(permissions)
        await self._require_micron(payload.parent_id)
        if payload.unit_id is not None:
            await self._require_unit(payload.unit_id)
        size_unit_id = payload.size_unit_id
        if size_unit_id is None:
            size_unit_id = (await self._unit_by_code("mm")).id
        else:
            await self._require_unit(size_unit_id)
        size_unit = await self._require_unit(size_unit_id)
        display_name = payload.name or self._size_label(payload.size, size_unit.code)

        async with transaction(self.session):
            try:
                row = await self.categories.create(
                    {
                        "parent_id": payload.parent_id,
                        "category_kind": MaterialCategoryKind.SKU.value,
                        "unit_id": payload.unit_id,
                        "size": payload.size,
                        "size_unit_id": size_unit_id,
                        "name": display_name,
                        "rolls_on_hand": payload.opening_rolls,
                        "total_kg": payload.opening_kg,
                        "price_per_unit": None,
                        "is_active": payload.is_active,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A material with this size already exists under this micron",
                ) from exc

            if payload.opening_rolls > 0 or payload.opening_kg > 0:
                snapshot = await self._movement_snapshot_fields(row)
                await self.movements.create(
                    {
                        "category_id": row.id,
                        "movement_date": date.today(),
                        "direction": MaterialMovementDirection.OPENING.value,
                        "rolls": payload.opening_rolls,
                        "kilograms": payload.opening_kg,
                        "note": "Opening balance",
                        "created_by": actor_user_id,
                        **snapshot,
                    },
                )

            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="material",
                entity_id=row.id,
                new_values=await self._material_snapshot(row),
            )

            return await self._material_response(row, can_view_price=can_view_price)

    async def update_material(
        self,
        material_id: UUID,
        payload: MaterialUpdate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> MaterialResponse:
        can_view_price = self._can_view_price(permissions)
        values = payload.model_dump(exclude_unset=True)
        rolls_target = values.pop("rolls_on_hand", None)
        kg_target = values.pop("total_kg", None)
        if payload.parent_id is not None:
            await self._require_micron(payload.parent_id)
        if payload.unit_id is not None:
            await self._require_unit(payload.unit_id)
        if payload.size_unit_id is not None:
            await self._require_unit(payload.size_unit_id)

        sku = await self._require_sku(material_id)
        old_snapshot = await self._material_snapshot(sku)

        async with transaction(self.session):
            current_rolls = sku.rolls_on_hand or Decimal("0")
            current_kg = sku.total_kg or Decimal("0")
            rolls_delta = (
                (rolls_target - current_rolls) if rolls_target is not None else Decimal("0")
            )
            kg_delta = (kg_target - current_kg) if kg_target is not None else Decimal("0")

            rolls_dir: MaterialMovementDirection | None = None
            movement_rolls = Decimal("0")
            if rolls_target is not None and rolls_delta != 0:
                rolls_dir = (
                    MaterialMovementDirection.IN
                    if rolls_delta > 0
                    else MaterialMovementDirection.OUT
                )
                movement_rolls = abs(rolls_delta)

            kg_dir: MaterialMovementDirection | None = None
            movement_kg = Decimal("0")
            if kg_target is not None and kg_delta != 0:
                kg_dir = (
                    MaterialMovementDirection.IN if kg_delta > 0 else MaterialMovementDirection.OUT
                )
                movement_kg = abs(kg_delta)

            async def record_stock_adjustment(
                direction: MaterialMovementDirection,
                adj_rolls: Decimal,
                adj_kg: Decimal,
                note: str,
            ) -> None:
                await self._apply_movement_to_category(sku, direction, adj_rolls, adj_kg)
                movement_snapshot = await self._movement_snapshot_fields(sku)
                await self.movements.create(
                    {
                        "category_id": material_id,
                        "movement_date": date.today(),
                        "direction": direction.value,
                        "rolls": adj_rolls,
                        "kilograms": adj_kg,
                        "note": note,
                        "created_by": actor_user_id,
                        **movement_snapshot,
                    },
                )

            if rolls_dir is not None and kg_dir is not None:
                if rolls_dir == kg_dir:
                    note = "Stock updated from material"
                    await record_stock_adjustment(rolls_dir, movement_rolls, movement_kg, note)
                else:
                    await record_stock_adjustment(
                        rolls_dir,
                        movement_rolls,
                        Decimal("0"),
                        "Roll count updated from material",
                    )
                    await record_stock_adjustment(
                        kg_dir,
                        Decimal("0"),
                        movement_kg,
                        "Quantity updated from material",
                    )
            elif rolls_dir is not None:
                await record_stock_adjustment(
                    rolls_dir,
                    movement_rolls,
                    Decimal("0"),
                    "Roll count updated from material",
                )
            elif kg_dir is not None:
                await record_stock_adjustment(
                    kg_dir,
                    Decimal("0"),
                    movement_kg,
                    "Quantity updated from material",
                )

            try:
                updated = await self.categories.update(material_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A material with this size already exists under this micron",
                ) from exc
            if updated is None:
                raise ResourceNotFoundError("Material not found")
            new_snapshot = await self._material_snapshot(updated)
            if audit_field_changes(old_snapshot, new_snapshot):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="material",
                    entity_id=updated.id,
                    old_values=old_snapshot,
                    new_values=new_snapshot,
                )
            return await self._material_response(updated, can_view_price=can_view_price)

    async def delete_material(
        self,
        material_id: UUID,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> MaterialResponse:
        row = await self._require_sku(material_id)
        old_snapshot = await self._material_snapshot(row)
        async with transaction(self.session):
            deleted = await self.categories.soft_delete(material_id)
            if deleted is None:
                raise ResourceNotFoundError("Material not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="material",
                entity_id=row.id,
                old_values=old_snapshot,
            )
            return await self._material_response(
                deleted, can_view_price=self._can_view_price(permissions)
            )

    async def _material_snapshot(self, row: MaterialCategory) -> dict[str, object]:
        micron, product = await self._sku_hierarchy(row)
        company_name = ""
        if product and product.company_id:
            names = await self._company_name_map([product.company_id])
            company_name = names.get(product.company_id, "")
        unit_code = ""
        if row.unit_id:
            units = await self.unit_lookup.get_units_by_ids([row.unit_id])
            unit = units.get(row.unit_id)
            unit_code = unit.code if unit else ""
        size_code = ""
        if row.size_unit_id:
            units = await self.unit_lookup.get_units_by_ids([row.size_unit_id])
            size_unit = units.get(row.size_unit_id)
            size_code = size_unit.code if size_unit else ""
        return {
            "company_name": company_name,
            "product_name": product.name if product else "",
            "micron_name": micron.name if micron else "",
            "size": str(row.size) if row.size is not None else "",
            "size_unit_code": size_code,
            "name": row.name,
            "unit_code": unit_code,
            "is_active": row.is_active,
        }

    async def _history_movement_context(
        self,
        sku: MaterialCategory,
        movement: MaterialMovement,
    ) -> tuple[UUID | None, str, Decimal | None, str | None]:
        _micron, product = await self._sku_hierarchy(sku)
        company_id = movement.company_id
        if company_id is None and product:
            company_id = product.company_id
        company_name = ""
        if company_id:
            names = await self._company_name_map([company_id])
            company_name = names.get(company_id, "")

        # Use only values stored on the movement row. Current micron price must not
        # rewrite historical purchase prices in the ledger.
        price = movement.price_per_unit
        price_unit_id = movement.price_unit_id
        price_unit_code = ""
        if price_unit_id:
            units = await self.unit_lookup.get_units_by_ids([price_unit_id])
            unit = units.get(price_unit_id)
            price_unit_code = unit.code if unit else ""
        return company_id, company_name, self._display_decimal(price), price_unit_code or None

    async def material_history(
        self,
        material_id: UUID,
        *,
        page: PageParams,
        permissions: frozenset[str],
    ) -> tuple[list[MaterialHistoryEntry], int]:
        sku = await self._require_sku(material_id)
        can_view_price = self._can_view_price(permissions)
        refs, total = await self.material_history_repo.list_entry_refs(material_id, page=page)
        movement_ids = [entry_id for _kind, entry_id in refs]
        movements = await self.material_history_repo.get_movements_by_ids(movement_ids)
        user_ids = [
            uid
            for uid in (movement.created_by for movement in movements.values())
            if uid is not None
        ]
        users_by_id: dict[UUID, User] = {}
        if user_ids:
            unique_users = list(dict.fromkeys(user_ids))
            for user_id in unique_users:
                user = await self.session.get(User, user_id)
                if user is not None:
                    users_by_id[user_id] = user

        entries: list[MaterialHistoryEntry] = []
        for _kind, entry_id in refs:
            movement = movements.get(entry_id)
            if movement is None:
                continue
            company_id, company_name, price, price_code = await self._history_movement_context(
                sku,
                movement,
            )
            user = None
            if movement.created_by and movement.created_by in users_by_id:
                actor = users_by_id[movement.created_by]
                user = AuditLogUserSummary(id=actor.id, name=actor.name)
            entries.append(
                MaterialHistoryEntry(
                    id=movement.id,
                    timestamp=movement.created_at,
                    kind="stock",
                    action=movement.direction,
                    user=user,
                    company_id=company_id,
                    company_name=company_name,
                    rolls=self._display_decimal(movement.rolls),
                    kilograms=self._display_decimal(movement.kilograms),
                    price_per_unit=price if can_view_price else None,
                    price_unit_code=price_code if can_view_price else None,
                    note=movement.note,
                ),
            )
        return entries, total

    async def material_history_summary(
        self,
        material_id: UUID,
        *,
        permissions: frozenset[str],
    ) -> MaterialHistorySummary:
        sku = await self._require_sku(material_id)
        micron, product = await self._sku_hierarchy(sku)
        company_id = product.company_id if product else None
        company_name = ""
        if company_id:
            names = await self._company_name_map([company_id])
            company_name = names.get(company_id, "")
        size_code = ""
        if sku.size_unit_id:
            units = await self.unit_lookup.get_units_by_ids([sku.size_unit_id])
            size_unit = units.get(sku.size_unit_id)
            size_code = size_unit.code if size_unit else ""
        size_val = self._display_decimal(sku.size or Decimal("0")) or Decimal("0")
        price_unit_code: str | None = None
        if micron and micron.price_unit_id:
            units = await self.unit_lookup.get_units_by_ids([micron.price_unit_id])
            price_unit = units.get(micron.price_unit_id)
            price_unit_code = price_unit.code if price_unit else None
        can_view_price = self._can_view_price(permissions)
        avg_prices = await self._avg_prices_by_sku_ids([material_id])
        last = await self.movements.last_purchase_movement(material_id)
        last_price: Decimal | None = None
        last_price_code: str | None = None
        last_date: date | None = None
        last_rolls: Decimal | None = None
        if last is not None:
            _, _, last_price, last_price_code = await self._history_movement_context(sku, last)
            last_date = last.movement_date
            last_rolls = self._display_decimal(last.rolls)
        return MaterialHistorySummary(
            company_id=company_id,
            company_name=company_name,
            size_label=self._size_label(size_val, size_code),
            product_name=product.name if product else "",
            micron_name=micron.name if micron else "",
            rolls_on_hand=self._display_decimal(sku.rolls_on_hand or Decimal("0")) or Decimal("0"),
            total_kg=self._display_decimal(sku.total_kg or Decimal("0")) or Decimal("0"),
            last_purchase_price=last_price if can_view_price else None,
            last_purchase_price_unit_code=last_price_code if can_view_price else None,
            last_purchase_date=last_date,
            last_purchase_rolls=last_rolls,
            avg_price_per_unit=avg_prices.get(material_id) if can_view_price else None,
            price_unit_code=price_unit_code,
        )

    # Movements

    async def _movement_response(self, row: MaterialMovement) -> MovementResponse:
        sku = await self._require_sku(row.category_id)
        micron, product = await self._sku_hierarchy(sku)
        size_code = ""
        if sku.size_unit_id:
            units = await self.unit_lookup.get_units_by_ids([sku.size_unit_id])
            size_unit = units.get(sku.size_unit_id)
            size_code = size_unit.code if size_unit else ""
        created_by_name: str | None = None
        if row.created_by is not None:
            user = await self.session.get(User, row.created_by)
            created_by_name = user.name if user else None
        return MovementResponse(
            id=row.id,
            category_id=row.category_id,
            product_name=product.name if product else "",
            micron_name=micron.name if micron else "",
            size_label=self._size_label(sku.size, size_code),
            category_name=sku.name,
            parent_name=micron.name if micron else "",
            movement_date=row.movement_date,
            direction=MaterialMovementDirection(row.direction),
            rolls=self._display_decimal(row.rolls) or Decimal("0"),
            kilograms=self._display_decimal(row.kilograms) or Decimal("0"),
            note=row.note,
            created_by=row.created_by,
            created_by_name=created_by_name,
            created_at=row.created_at,
        )

    async def get_movement(self, movement_id: UUID) -> MovementResponse:
        row = await self.movements.get(movement_id)
        if row is None:
            raise ResourceNotFoundError("Movement not found")
        return await self._movement_response(row)

    async def list_movements(
        self,
        *,
        movement_date: date,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[list[MovementResponse], int]:
        rows, total = await self.movements.list_for_date(
            movement_date=movement_date,
            page=page,
            common_filter=common_filter,
        )
        return [await self._movement_response(row) for row in rows], total

    async def create_movement(
        self,
        payload: MovementCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> MovementResponse:
        if payload.rolls == 0 and payload.kilograms == 0:
            raise ValidationError("Enter at least one of rolls or kilograms")

        can_view_price = self._can_view_price(permissions)
        if (
            payload.price_per_unit is not None or payload.price_unit_id is not None
        ) and not can_view_price:
            raise ValidationError("You do not have permission to set purchase price")

        async with transaction(self.session):
            sku = await self._require_sku(payload.category_id)
            micron, _product = await self._sku_hierarchy(sku)
            movement_snapshot: dict[str, object]
            if (
                payload.direction == MaterialMovementDirection.IN
                and payload.price_per_unit is not None
                and can_view_price
            ):
                price_unit_id = payload.price_unit_id
                if price_unit_id is None and micron is not None:
                    price_unit_id = micron.price_unit_id
                if price_unit_id is not None:
                    await self._require_unit(price_unit_id)
                movement_snapshot = {
                    "company_id": _product.company_id if _product else None,
                    "price_per_unit": payload.price_per_unit,
                    "price_unit_id": price_unit_id,
                }
            else:
                movement_snapshot = await self._movement_snapshot_fields(sku)

            await self._apply_movement_to_category(
                sku,
                payload.direction,
                payload.rolls,
                payload.kilograms,
            )
            row = await self.movements.create(
                {
                    "category_id": payload.category_id,
                    "movement_date": payload.movement_date,
                    "direction": payload.direction.value,
                    "rolls": payload.rolls,
                    "kilograms": payload.kilograms,
                    "note": payload.note,
                    "created_by": actor_user_id,
                    **movement_snapshot,
                },
            )
            if (
                payload.direction == MaterialMovementDirection.IN
                and payload.price_per_unit is not None
                and can_view_price
                and micron is not None
            ):
                price_unit_id = movement_snapshot.get("price_unit_id")
                await self.categories.update(
                    micron.id,
                    {
                        "price_per_unit": payload.price_per_unit,
                        "price_unit_id": price_unit_id,
                    },
                )
            return await self._movement_response(row)

    async def delete_movement(self, movement_id: UUID) -> MovementResponse:
        async with transaction(self.session):
            row = await self.movements.get(movement_id)
            if row is None:
                raise ResourceNotFoundError("Movement not found")
            if row.direction == MaterialMovementDirection.OPENING.value:
                raise ValidationError("Opening balance movements cannot be deleted")

            sku = await self._require_sku(row.category_id)
            direction = MaterialMovementDirection(row.direction)
            reverse = (
                MaterialMovementDirection.IN
                if direction == MaterialMovementDirection.OUT
                else MaterialMovementDirection.OUT
            )
            await self._apply_movement_to_category(
                sku,
                reverse,
                row.rolls,
                row.kilograms,
            )
            deleted = await self.movements.soft_delete(movement_id)
            assert deleted is not None
            return await self._movement_response(deleted)

    async def day_report(
        self,
        *,
        start_date: date,
        end_date: date,
        permissions: frozenset[str],
    ) -> list[DayReportRow]:
        can_view_price = self._can_view_price(permissions)
        skus = await self.categories.list_active_skus()
        if not skus:
            return []

        day_totals = await self.movements.day_totals(start_date, end_date)
        micron_ids = [sku.parent_id for sku in skus if sku.parent_id]
        microns = await self.categories.get_by_ids(micron_ids)
        product_ids = [m.parent_id for m in microns.values() if m.parent_id]
        products = await self.categories.get_by_ids(product_ids)
        unit_ids: list[UUID] = []
        for sku in skus:
            if sku.unit_id:
                unit_ids.append(sku.unit_id)
            if sku.size_unit_id:
                unit_ids.append(sku.size_unit_id)
        for micron in microns.values():
            if micron.price_unit_id:
                unit_ids.append(micron.price_unit_id)
        units = await self.unit_lookup.get_units_by_ids(unit_ids)
        avg_prices = (
            await self._avg_prices_by_sku_ids([sku.id for sku in skus]) if can_view_price else {}
        )
        rows: list[DayReportRow] = []
        for sku in skus:
            micron = microns.get(sku.parent_id) if sku.parent_id else None
            product = products.get(micron.parent_id) if micron and micron.parent_id else None
            unit = units.get(sku.unit_id) if sku.unit_id else None
            size_unit = units.get(sku.size_unit_id) if sku.size_unit_id else None
            price_unit = (
                units.get(micron.price_unit_id) if micron and micron.price_unit_id else None
            )
            size_code = size_unit.code if size_unit else ""
            in_r, in_k, out_r, out_k = day_totals.get(
                sku.id,
                (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
            )
            closing_rolls, closing_kg = await self.movements.sum_through_date(sku.id, end_date)
            price = micron.price_per_unit if micron and can_view_price else None
            price_code = price_unit.code if price_unit and can_view_price else None
            size_val = self._display_decimal(sku.size or Decimal("0")) or Decimal("0")
            rows.append(
                DayReportRow(
                    category_id=sku.id,
                    product_id=product.id if product else sku.id,
                    product_name=product.name if product else "",
                    micron_id=micron.id if micron else sku.id,
                    micron_name=micron.name if micron else "",
                    size=size_val,
                    size_unit_code=size_code,
                    size_label=self._size_label(size_val, size_code),
                    category_name=sku.name,
                    parent_name=micron.name if micron else "",
                    unit_code=unit.code if unit else "",
                    in_rolls=self._display_decimal(in_r) or Decimal("0"),
                    in_kg=self._display_decimal(in_k) or Decimal("0"),
                    out_rolls=self._display_decimal(out_r) or Decimal("0"),
                    out_kg=self._display_decimal(out_k) or Decimal("0"),
                    closing_rolls=self._display_decimal(closing_rolls) or Decimal("0"),
                    closing_kg=self._display_decimal(closing_kg) or Decimal("0"),
                    price_per_unit=self._display_decimal(price),
                    price_unit_code=price_code,
                    avg_price_per_unit=avg_prices.get(sku.id) if can_view_price else None,
                ),
            )
        return rows

    async def materials_day_report_for_export(
        self,
        *,
        start_date: date,
        end_date: date,
        permissions: frozenset[str],
    ) -> list[DayReportRow]:
        from app.common.export.fetch import assert_export_total

        rows = await self.day_report(
            start_date=start_date,
            end_date=end_date,
            permissions=permissions,
        )
        assert_export_total(len(rows))
        return rows
