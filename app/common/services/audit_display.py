"""Resolve audit log field values and entity labels to human-readable text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.services.audit import AuditFieldChange, audit_field_changes, jsonable_value
from app.identity.models import Branch, Company, Department, Role, Warehouse
from app.identity.org_repository import OrganizationRepository
from app.identity.schemas import AddressResponse, format_address_label
from app.inventory.adhesives.models import AdhesiveBrand, AdhesiveCode
from app.inventory.cylinders.models import Cylinder, CylinderReturn
from app.inventory.inks.models import InkBrand, InkColor
from app.inventory.models import InventoryUnit, MaterialCategory
from app.inventory.solvents.models import SolventBrand, SolventName

# field key -> (display label for the row, lookup kind)
_FK_FIELDS: dict[str, tuple[str, str]] = {
    "company_id": ("Company", "company"),
    "cylinder_id": ("Cylinder", "cylinder"),
    "branch_id": ("Branch", "branch"),
    "department_id": ("Department", "department"),
    "manager_id": ("Manager", "user"),
    "user_id": ("User", "user"),
    "role_id": ("Role", "role"),
    "warehouse_id": ("Warehouse", "warehouse"),
    "unit_id": ("Unit", "unit"),
    "size_unit_id": ("Size unit", "unit"),
    "price_unit_id": ("Price unit", "unit"),
    "drum_unit_id": ("Unit", "unit"),
    "color_id": ("Color", "ink_color"),
    "ink_color_id": ("Color", "ink_color"),
    "adhesive_code_id": ("Code", "adhesive_code"),
    "solvent_name_id": ("Name", "solvent_name"),
    "brand_id": ("Brand", "ink_brand"),
    "material_id": ("Material", "material"),
    "category_id": ("Category", "material"),
    "parent_id": ("Parent", "material"),
    "address_id": ("Address", "address"),
    "bill_to_address_id": ("Bill to address", "address"),
    "ship_to_address_id": ("Ship to address", "address"),
}

_ENTITY_LABEL_KEYS = (
    "return_number",
    "cylinder_number",
    "name",
    "company_name",
    "product_name",
    "code",
    "email",
)


def _parse_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return UUID(text)
    except ValueError:
        return None


def _collect_uuids(values: Mapping[str, object] | None, kinds: dict[str, set[UUID]]) -> None:
    if not values:
        return
    for field, (_, kind) in _FK_FIELDS.items():
        if field not in values:
            continue
        uid = _parse_uuid(values[field])
        if uid is not None:
            kinds.setdefault(kind, set()).add(uid)


class AuditDisplayService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.org = OrganizationRepository(session)
        self._cache: dict[str, dict[UUID, str]] = {}

    async def humanize_values(self, values: dict[str, object] | None) -> dict[str, object] | None:
        if not values:
            return values
        await self._ensure_loaded(values)
        out: dict[str, object] = {}
        for key, raw in values.items():
            if key in _FK_FIELDS:
                label, kind = _FK_FIELDS[key]
                uid = _parse_uuid(raw)
                if uid is not None:
                    resolved = self._cache.get(kind, {}).get(uid)
                    if resolved is not None:
                        out[label] = resolved
                        continue
                if raw is not None and str(raw).strip():
                    out[label] = jsonable_value(raw)
                continue
            out[key] = jsonable_value(raw)
        return out

    async def humanize_changes(
        self,
        old_values: dict[str, object] | None,
        new_values: dict[str, object] | None,
    ) -> list[AuditFieldChange]:
        kinds: dict[str, set[UUID]] = {}
        _collect_uuids(old_values, kinds)
        _collect_uuids(new_values, kinds)
        await self._load_kinds(kinds)
        old_h = await self.humanize_values(old_values) if old_values else {}
        new_h = await self.humanize_values(new_values) if new_values else {}
        return audit_field_changes(old_h or None, new_h or None)

    async def entity_label(
        self,
        *,
        entity_type: str,
        entity_id: UUID | None,
        old_values: dict[str, object] | None,
        new_values: dict[str, object] | None,
    ) -> str | None:
        for blob in (new_values, old_values):
            if not blob:
                continue
            for key in _ENTITY_LABEL_KEYS:
                val = blob.get(key)
                if val is not None and str(val).strip():
                    return str(val).strip()
        if entity_id is None:
            return None
        label = await self._label_for_entity(entity_type, entity_id)
        return label

    async def _ensure_loaded(self, values: Mapping[str, object]) -> None:
        kinds: dict[str, set[UUID]] = {}
        _collect_uuids(values, kinds)
        await self._load_kinds(kinds)

    async def _load_kinds(self, kinds: dict[str, set[UUID]]) -> None:
        if "company" in kinds and kinds["company"]:
            await self._load_companies(kinds["company"])
        if "cylinder" in kinds and kinds["cylinder"]:
            await self._load_cylinders(kinds["cylinder"])
        if "branch" in kinds and kinds["branch"]:
            await self._load_branches(kinds["branch"])
        if "department" in kinds and kinds["department"]:
            await self._load_departments(kinds["department"])
        if "user" in kinds and kinds["user"]:
            await self._load_users(kinds["user"])
        if "role" in kinds and kinds["role"]:
            await self._load_roles(kinds["role"])
        if "warehouse" in kinds and kinds["warehouse"]:
            await self._load_warehouses(kinds["warehouse"])
        if "unit" in kinds and kinds["unit"]:
            await self._load_units(kinds["unit"])
        if "ink_color" in kinds and kinds["ink_color"]:
            await self._load_ink_colors(kinds["ink_color"])
        if "ink_brand" in kinds and kinds["ink_brand"]:
            await self._load_ink_brands(kinds["ink_brand"])
        if "adhesive_code" in kinds and kinds["adhesive_code"]:
            await self._load_adhesive_codes(kinds["adhesive_code"])
        if "adhesive_brand" in kinds and kinds["adhesive_brand"]:
            await self._load_adhesive_brands(kinds["adhesive_brand"])
        if "solvent_name" in kinds and kinds["solvent_name"]:
            await self._load_solvent_names(kinds["solvent_name"])
        if "solvent_brand" in kinds and kinds["solvent_brand"]:
            await self._load_solvent_brands(kinds["solvent_brand"])
        if "material" in kinds and kinds["material"]:
            await self._load_materials(kinds["material"])
        if "address" in kinds and kinds["address"]:
            await self._load_addresses(kinds["address"])

    async def _label_for_entity(self, entity_type: str, entity_id: UUID) -> str | None:
        match entity_type:
            case "company":
                await self._load_companies({entity_id})
                return self._cache.get("company", {}).get(entity_id)
            case "cylinder":
                await self._load_cylinders({entity_id})
                return self._cache.get("cylinder", {}).get(entity_id)
            case "cylinder_return":
                result = await self.session.execute(
                    select(CylinderReturn.return_number).where(CylinderReturn.id == entity_id)
                )
                row = result.scalar_one_or_none()
                return str(row) if row else None
            case "user":
                await self._load_users({entity_id})
                return self._cache.get("user", {}).get(entity_id)
            case "branch":
                await self._load_branches({entity_id})
                return self._cache.get("branch", {}).get(entity_id)
            case "department":
                await self._load_departments({entity_id})
                return self._cache.get("department", {}).get(entity_id)
            case "warehouse":
                await self._load_warehouses({entity_id})
                return self._cache.get("warehouse", {}).get(entity_id)
            case "role":
                await self._load_roles({entity_id})
                return self._cache.get("role", {}).get(entity_id)
            case "material":
                await self._load_materials({entity_id})
                return self._cache.get("material", {}).get(entity_id)
            case "ink_color":
                await self._load_ink_colors({entity_id})
                return self._cache.get("ink_color", {}).get(entity_id)
            case "adhesive_code":
                await self._load_adhesive_codes({entity_id})
                return self._cache.get("adhesive_code", {}).get(entity_id)
            case "solvent_name":
                await self._load_solvent_names({entity_id})
                return self._cache.get("solvent_name", {}).get(entity_id)
            case "ink_sheet":
                from app.inventory.inks.models import InkSheet

                result = await self.session.execute(
                    select(InkSheet.company_id).where(InkSheet.id == entity_id)
                )
                company_id = result.scalar_one_or_none()
                if company_id is None:
                    return None
                await self._load_companies({company_id})
                name = self._cache.get("company", {}).get(company_id)
                return f"Ink sheet · {name}" if name else None
            case "adhesive_sheet":
                from app.inventory.adhesives.models import AdhesiveSheet

                result = await self.session.execute(
                    select(AdhesiveSheet.company_id).where(AdhesiveSheet.id == entity_id)
                )
                company_id = result.scalar_one_or_none()
                if company_id is None:
                    return None
                await self._load_companies({company_id})
                name = self._cache.get("company", {}).get(company_id)
                return f"Adhesive sheet · {name}" if name else None
            case "solvent_sheet":
                from app.inventory.solvents.models import SolventSheet

                result = await self.session.execute(
                    select(SolventSheet.company_id).where(SolventSheet.id == entity_id)
                )
                company_id = result.scalar_one_or_none()
                if company_id is None:
                    return None
                await self._load_companies({company_id})
                name = self._cache.get("company", {}).get(company_id)
                return f"Solvent sheet · {name}" if name else None
            case "organization":
                org = await self.org.get_organization()
                return org.name if org else None
            case _:
                return None

    async def _load_companies(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("company", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(Company).where(Company.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_cylinders(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("cylinder", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(Cylinder).where(Cylinder.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.cylinder_number

    async def _load_branches(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("branch", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(Branch).where(Branch.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_departments(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("department", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(Department).where(Department.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_users(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("user", {})
        missing = ids - cache.keys()
        if not missing:
            return
        users = await self.org.get_users_by_ids(list(missing))
        for uid, user in users.items():
            cache[uid] = user.name

    async def _load_roles(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("role", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(Role).where(Role.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_warehouses(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("warehouse", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(Warehouse).where(Warehouse.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_units(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("unit", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(
            select(InventoryUnit).where(InventoryUnit.id.in_(missing))
        )
        for row in result.scalars().all():
            cache[row.id] = row.code

    async def _load_ink_colors(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("ink_color", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(InkColor).where(InkColor.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_ink_brands(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("ink_brand", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(InkBrand).where(InkBrand.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_adhesive_codes(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("adhesive_code", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(
            select(AdhesiveCode).where(AdhesiveCode.id.in_(missing))
        )
        for row in result.scalars().all():
            cache[row.id] = row.code

    async def _load_adhesive_brands(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("adhesive_brand", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(
            select(AdhesiveBrand).where(AdhesiveBrand.id.in_(missing))
        )
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_solvent_names(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("solvent_name", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(select(SolventName).where(SolventName.id.in_(missing)))
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_solvent_brands(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("solvent_brand", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(
            select(SolventBrand).where(SolventBrand.id.in_(missing))
        )
        for row in result.scalars().all():
            cache[row.id] = row.name

    async def _load_materials(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("material", {})
        missing = ids - cache.keys()
        if not missing:
            return
        result = await self.session.execute(
            select(MaterialCategory).where(MaterialCategory.id.in_(missing))
        )
        for row in result.scalars().all():
            label = row.name or (str(row.size) if row.size is not None else str(row.id))
            cache[row.id] = label

    async def _load_addresses(self, ids: set[UUID]) -> None:
        cache = self._cache.setdefault("address", {})
        missing = ids - cache.keys()
        if not missing:
            return
        addresses = await self.org.get_addresses(list(missing))
        for address_id, address in addresses.items():
            label = format_address_label(AddressResponse.model_validate(address))
            if label:
                cache[address_id] = label

    async def preload_for_logs(self, rows: Sequence[object]) -> None:
        """Batch-load FK targets referenced across many audit rows."""
        kinds: dict[str, set[UUID]] = {}
        for row in rows:
            old = getattr(row, "old_values", None) or {}
            new = getattr(row, "new_values", None) or {}
            _collect_uuids(old, kinds)
            _collect_uuids(new, kinds)
            entity_id = getattr(row, "entity_id", None)
            entity_type = getattr(row, "entity_type", None)
            if entity_id and entity_type in (
                "company",
                "cylinder",
                "user",
                "ink_color",
                "adhesive_code",
                "solvent_name",
            ):
                kind_map = {
                    "company": "company",
                    "cylinder": "cylinder",
                    "user": "user",
                    "ink_color": "ink_color",
                    "adhesive_code": "adhesive_code",
                    "solvent_name": "solvent_name",
                }
                kinds.setdefault(kind_map[entity_type], set()).add(entity_id)
        await self._load_kinds(kinds)
