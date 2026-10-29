"""Cylinder returns business logic."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter, audit_field_changes
from app.common.services.entity_history import EntityHistoryEntry, EntityHistoryService
from app.core.enums import AuditAction, INVENTORY_MODULE, JobStatus
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.identity.models import Company
from app.inventory.jobs.models import Job
from app.inventory.jobs.repository import CylinderReturnRepository, JobRepository
from app.inventory.jobs.schemas import CylinderReturnCreate, CylinderReturnResponse, CylinderReturnUpdate
from sqlalchemy import select


class CylinderReturnService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CylinderReturnRepository(session)
        self.job_repo = JobRepository(session)
        self.audit = AuditWriter(session)
        self.history = EntityHistoryService(session)

    async def list_returns(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        company_id: UUID | None,
        job_id: UUID | None,
    ) -> tuple[list[CylinderReturnResponse], int]:
        filters: dict[str, object] = {}
        if company_id is not None:
            filters["company_id"] = company_id
        if job_id is not None:
            filters["job_id"] = job_id
        rows, total = await self.repo.list(page=page, common_filter=common_filter, filters=filters or None)
        return [await self._to_response(row) for row in rows], total

    async def get_return(self, return_id: UUID) -> CylinderReturnResponse:
        row = await self._require(return_id)
        return await self._to_response(row)

    async def create_return(
        self,
        payload: CylinderReturnCreate,
        *,
        actor_user_id: UUID,
    ) -> CylinderReturnResponse:
        job = await self.job_repo.get(payload.job_id)
        if job is None:
            raise ValidationError("Job not found")
        if job.status == JobStatus.RETURNED.value:
            raise ValidationError("Job is already returned")
        if job.company_id != payload.company_id:
            raise ValidationError("Customer must match the job company")
        existing = await self.repo.get_by_job(payload.job_id)
        if existing is not None:
            raise DuplicateResourceError("A return already exists for this job")
        async with transaction(self.session):
            return_number = await self.repo.next_return_number()
            try:
                row = await self.repo.create(
                    {
                        "return_number": return_number,
                        "job_id": payload.job_id,
                        "company_id": payload.company_id,
                        "remarks": payload.remarks,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    }
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("Return number conflict; retry") from exc
            job.status = JobStatus.RETURNED.value
            job.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="cylinder_return",
                entity_id=row.id,
                new_values={
                    "return_number": row.return_number,
                    "job_id": str(row.job_id),
                    "company_id": str(row.company_id),
                },
            )
            return await self._to_response(row)

    async def update_return(
        self,
        return_id: UUID,
        payload: CylinderReturnUpdate,
        *,
        actor_user_id: UUID,
    ) -> CylinderReturnResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            row = await self._require(return_id)
            old = {
                "company_id": str(row.company_id),
                "remarks": row.remarks,
            }
            if "company_id" in values and values["company_id"] is not None:
                job = await self.job_repo.get(row.job_id)
                if job is not None and job.company_id != values["company_id"]:
                    raise ValidationError("Customer must match the job company")
            values["updated_by"] = actor_user_id
            updated = await self.repo.update(return_id, values)
            if updated is None:
                raise ResourceNotFoundError("Cylinder return not found")
            new = {
                "company_id": str(updated.company_id),
                "remarks": updated.remarks,
            }
            if audit_field_changes(old, new):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="cylinder_return",
                    entity_id=updated.id,
                    old_values=old,
                    new_values=new,
                )
            return await self._to_response(updated)

    async def delete_return(
        self,
        return_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> CylinderReturnResponse:
        async with transaction(self.session):
            row = await self._require(return_id)
            response = await self._to_response(row)
            job = await self.job_repo.get(row.job_id)
            deleted = await self.repo.soft_delete(return_id)
            if deleted is None:
                raise ResourceNotFoundError("Cylinder return not found")
            if job is not None and job.status == JobStatus.RETURNED.value:
                job.status = JobStatus.ACTIVE.value
                job.updated_by = actor_user_id
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="cylinder_return",
                entity_id=row.id,
                old_values={"return_number": row.return_number},
            )
            return response

    async def return_history(
        self,
        return_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        await self._require(return_id)
        return await self.history.list_for_entity(
            entity_type="cylinder_return",
            entity_id=return_id,
            page=page,
        )

    async def _require(self, return_id: UUID):
        from app.inventory.jobs.models import CylinderReturn

        row = await self.repo.get(return_id)
        if row is None:
            raise ResourceNotFoundError("Cylinder return not found")
        return row

    async def _to_response(self, row) -> CylinderReturnResponse:
        company = await self.session.scalar(
            select(Company).where(Company.id == row.company_id, Company.deleted_at.is_(None))
        )
        job = await self.job_repo.get(row.job_id)
        related = [
            RelatedDocumentRef(
                document_type="job",
                document_id=row.job_id,
                document_number=job.job_number if job else "",
                status=job.status if job else "",
                relationship="source",
            )
        ]
        return CylinderReturnResponse(
            id=row.id,
            return_number=row.return_number,
            job_id=row.job_id,
            job_number=job.job_number if job else "",
            company_id=row.company_id,
            company_name=company.name if company else "",
            remarks=row.remarks,
            related_documents=related,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
