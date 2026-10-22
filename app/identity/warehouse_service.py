"""Warehouse CRUD for the single-tenant identity slice."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter, audit_field_changes
from app.core.enums import AddressType, AuditAction, IDENTITY_MODULE
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.identity.models import Warehouse
from app.identity.org_repository import OrganizationRepository
from app.identity.org_service import OrganizationService
from app.identity.repository import WarehouseRepository
from app.identity.schemas import (
    AddressPayload,
    AddressResponse,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
    format_address_label,
)


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WarehouseRepository(session)
        self.org_repo = OrganizationRepository(session)
        self.org_service = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[WarehouseResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        return [item for item in await self._to_responses(list(rows))], total

    async def get(self, warehouse_id: UUID) -> WarehouseResponse:
        row = await self._require(warehouse_id)
        return (await self._to_responses([row]))[0]

    async def create(self, payload: WarehouseCreate, *, actor_user_id: UUID) -> WarehouseResponse:
        async with transaction(self.session):
            make_default = payload.is_default or (await self.repo.count() == 0)
            if make_default:
                await self.repo.clear_other_defaults()
            address_id = await self.org_service.upsert_address(
                None,
                payload.address,
                address_type=AddressType.WAREHOUSE,
            )
            try:
                row = await self.repo.create(
                    {
                        "code": payload.code,
                        "name": payload.name,
                        "phone": payload.phone,
                        "address_id": address_id,
                        "is_default": make_default,
                        "is_active": payload.is_active,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A warehouse with this code already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="warehouse",
                entity_id=row.id,
                new_values=await self._warehouse_snapshot(row),
            )
            return (await self._to_responses([row]))[0]

    async def update(
        self,
        warehouse_id: UUID,
        payload: WarehouseUpdate,
        *,
        actor_user_id: UUID,
    ) -> WarehouseResponse:
        values = payload.model_dump(exclude_unset=True)
        address_payload = values.pop("address", None)
        async with transaction(self.session):
            row = await self._require(warehouse_id)
            old_values = await self._warehouse_snapshot(row)
            if values.get("is_default") is True:
                await self.repo.clear_other_defaults(keep_id=row.id)
            if address_payload is not None:
                values["address_id"] = await self.org_service.upsert_address(
                    row.address_id,
                    AddressPayload.model_validate(address_payload),
                    address_type=AddressType.WAREHOUSE,
                )
            values["updated_by"] = actor_user_id
            try:
                updated = await self.repo.update(warehouse_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A warehouse with this code already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Warehouse not found")
            new_values = await self._warehouse_snapshot(updated)
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="warehouse",
                    entity_id=updated.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return (await self._to_responses([updated]))[0]

    async def delete(self, warehouse_id: UUID, *, actor_user_id: UUID) -> WarehouseResponse:
        async with transaction(self.session):
            row = await self._require(warehouse_id)
            if row.is_default and await self.repo.count() > 1:
                raise ValidationError("Assign another default warehouse before deleting this one")
            response = (await self._to_responses([row]))[0]
            deleted = await self.repo.soft_delete(warehouse_id)
            if deleted is None:
                raise ResourceNotFoundError("Warehouse not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="warehouse",
                entity_id=row.id,
                old_values=await self._warehouse_snapshot(row),
            )
            return response

    async def _require(self, warehouse_id: UUID) -> Warehouse:
        row = await self.repo.get(warehouse_id)
        if row is None:
            raise ResourceNotFoundError("Warehouse not found")
        return row

    async def _warehouse_snapshot(self, row: Warehouse) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "code": row.code,
            "name": row.name,
            "phone": row.phone,
            "is_default": row.is_default,
            "is_active": row.is_active,
        }
        if row.address_id is not None:
            address = await self.org_repo.get_address(row.address_id)
            if address is not None:
                snapshot["address"] = format_address_label(AddressResponse.model_validate(address))
        return snapshot

    async def _to_responses(self, rows: list[Warehouse]) -> list[WarehouseResponse]:
        address_ids = [row.address_id for row in rows if row.address_id is not None]
        addresses = await self.org_repo.get_addresses(address_ids)
        responses: list[WarehouseResponse] = []
        for row in rows:
            address = None
            if row.address_id is not None and row.address_id in addresses:
                address = AddressResponse.model_validate(addresses[row.address_id])
            responses.append(
                WarehouseResponse(
                    id=row.id,
                    code=row.code,
                    name=row.name,
                    phone=row.phone,
                    is_default=row.is_default,
                    is_active=row.is_active,
                    address=address,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return responses
