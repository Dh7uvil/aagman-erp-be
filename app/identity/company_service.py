"""Company master CRUD for the single-tenant identity slice."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter, audit_field_changes
from app.core.enums import AddressType, AuditAction, IDENTITY_MODULE
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.identity.models import Company
from app.identity.org_repository import OrganizationRepository
from app.identity.org_service import OrganizationService
from app.identity.repository import CompanyRepository
from app.identity.schemas import (
    AddressPayload,
    AddressResponse,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
    format_address_label,
)


class CompanyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CompanyRepository(session)
        self.org_repo = OrganizationRepository(session)
        self.org_service = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[list[CompanyResponse], int]:
        rows, total = await self.repo.list(page=page, common_filter=common_filter)
        return [item for item in await self._to_responses(list(rows))], total

    async def get(self, company_id: UUID) -> CompanyResponse:
        row = await self._require(company_id)
        return (await self._to_responses([row]))[0]

    async def create(self, payload: CompanyCreate, *, actor_user_id: UUID) -> CompanyResponse:
        async with transaction(self.session):
            address_id = await self._upsert_address(None, payload.address, address_type=AddressType.COMPANY)
            bill_to_address_id = await self._upsert_address(
                None,
                payload.bill_to_address,
                address_type=AddressType.BILL_TO,
            )
            ship_to_address_id = await self._upsert_address(
                None,
                payload.ship_to_address,
                address_type=AddressType.SHIP_TO,
            )
            try:
                row = await self.repo.create(
                    {
                        "name": payload.name,
                        "email": payload.email,
                        "phone": payload.phone,
                        "address_id": address_id,
                        "bill_to_address_id": bill_to_address_id,
                        "ship_to_address_id": ship_to_address_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A company with this name already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="company",
                entity_id=row.id,
                new_values=await self._company_snapshot(row),
            )
            return (await self._to_responses([row]))[0]

    async def update(
        self,
        company_id: UUID,
        payload: CompanyUpdate,
        *,
        actor_user_id: UUID,
    ) -> CompanyResponse:
        values = payload.model_dump(exclude_unset=True)
        address_payload = values.pop("address", None)
        bill_to_payload = values.pop("bill_to_address", None)
        ship_to_payload = values.pop("ship_to_address", None)
        async with transaction(self.session):
            row = await self._require(company_id)
            old_values = await self._company_snapshot(row)
            if address_payload is not None:
                values["address_id"] = await self._upsert_address(
                    row.address_id,
                    AddressPayload.model_validate(address_payload),
                    address_type=AddressType.COMPANY,
                )
            if bill_to_payload is not None:
                values["bill_to_address_id"] = await self._upsert_address(
                    row.bill_to_address_id,
                    AddressPayload.model_validate(bill_to_payload),
                    address_type=AddressType.BILL_TO,
                )
            if ship_to_payload is not None:
                values["ship_to_address_id"] = await self._upsert_address(
                    row.ship_to_address_id,
                    AddressPayload.model_validate(ship_to_payload),
                    address_type=AddressType.SHIP_TO,
                )
            try:
                updated = await self.repo.update(company_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A company with this name already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Company not found")
            new_values = await self._company_snapshot(updated)
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="company",
                    entity_id=updated.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return (await self._to_responses([updated]))[0]

    async def delete(self, company_id: UUID, *, actor_user_id: UUID) -> CompanyResponse:
        async with transaction(self.session):
            row = await self._require(company_id)
            response = (await self._to_responses([row]))[0]
            deleted = await self.repo.soft_delete(company_id)
            if deleted is None:
                raise ResourceNotFoundError("Company not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="company",
                entity_id=row.id,
                old_values=await self._company_snapshot(row),
            )
            return response

    async def _upsert_address(
        self,
        current_id: UUID | None,
        payload: AddressPayload | None,
        *,
        address_type: AddressType,
    ) -> UUID | None:
        return await self.org_service.upsert_address(current_id, payload, address_type=address_type)

    async def _require(self, company_id: UUID) -> Company:
        row = await self.repo.get(company_id)
        if row is None:
            raise ResourceNotFoundError("Company not found")
        return row

    async def _address_label(self, address_id: UUID | None) -> str | None:
        if address_id is None:
            return None
        address = await self.org_repo.get_address(address_id)
        if address is None:
            return None
        return format_address_label(AddressResponse.model_validate(address))

    async def _company_snapshot(self, row: Company) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "name": row.name,
            "email": row.email,
            "phone": row.phone,
        }
        for key, address_id in (
            ("address", row.address_id),
            ("bill_to_address", row.bill_to_address_id),
            ("ship_to_address", row.ship_to_address_id),
        ):
            label = await self._address_label(address_id)
            if label is not None:
                snapshot[key] = label
        return snapshot

    async def _to_responses(self, rows: list[Company]) -> list[CompanyResponse]:
        address_ids: list[UUID] = []
        for row in rows:
            for address_id in (row.address_id, row.bill_to_address_id, row.ship_to_address_id):
                if address_id is not None:
                    address_ids.append(address_id)
        addresses = await self.org_repo.get_addresses(address_ids)

        def resolve(address_id: UUID | None) -> AddressResponse | None:
            if address_id is None or address_id not in addresses:
                return None
            return AddressResponse.model_validate(addresses[address_id])

        responses: list[CompanyResponse] = []
        for row in rows:
            responses.append(
                CompanyResponse(
                    id=row.id,
                    name=row.name,
                    email=row.email,
                    phone=row.phone,
                    address=resolve(row.address_id),
                    bill_to_address=resolve(row.bill_to_address_id),
                    ship_to_address=resolve(row.ship_to_address_id),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return responses
