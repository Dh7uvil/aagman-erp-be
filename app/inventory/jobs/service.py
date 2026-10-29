"""Jobs business logic."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
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
from app.core.enums import AuditAction, INVENTORY_MODULE, JobStatus
from app.core.exceptions import (
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.identity.models import Company, User
from app.integrations.storage import get_optional_storage
from app.inventory.catalog import (
    JOB_CHALLAN_CREATE,
    JOB_CHALLAN_DELETE,
    JOB_CHALLAN_READ,
    JOB_CHALLAN_UPDATE,
    JOB_IMAGE_CREATE,
    JOB_IMAGE_DELETE,
    JOB_IMAGE_READ,
    JOB_IMAGE_UPDATE,
    JOB_VIEW_PRICE,
)
from app.inventory.jobs import storage as job_storage
from app.inventory.jobs.models import Job, JobPause
from app.inventory.jobs.repository import (
    CylinderReturnRepository,
    JobRepository,
    load_colors,
    load_cylinders,
    load_pauses,
    replace_colors,
    replace_cylinders,
)
from app.common.utils.time import utcnow
from app.inventory.jobs.schemas import (
    JOB_FILE_SLOTS,
    JobCreate,
    JobFileMeta,
    JobListItem,
    JobPauseRequest,
    JobPauseResponse,
    JobResponse,
    JobUpdate,
)

JOB_ALLOWED_MIME = (MIME_JPEG, MIME_PNG, MIME_WEBP, MIME_PDF)

_SLOT_READ = {"job_image": JOB_IMAGE_READ, "challan": JOB_CHALLAN_READ}
_SLOT_CREATE = {"job_image": JOB_IMAGE_CREATE, "challan": JOB_CHALLAN_CREATE}
_SLOT_UPDATE = {"job_image": JOB_IMAGE_UPDATE, "challan": JOB_CHALLAN_UPDATE}
_SLOT_DELETE = {"job_image": JOB_IMAGE_DELETE, "challan": JOB_CHALLAN_DELETE}


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = JobRepository(session)
        self.returns_repo = CylinderReturnRepository(session)
        self.audit = AuditWriter(session)
        self.history = EntityHistoryService(session)
        self.storage = get_optional_storage()
        self.settings = get_settings()

    @staticmethod
    def _can_view_price(permissions: frozenset[str]) -> bool:
        return has_permission(permissions, JOB_VIEW_PRICE)

    async def list_jobs(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        status: JobStatus | None,
        company_id: UUID | None,
        include_closed: bool,
        permissions: frozenset[str],
    ) -> tuple[list[JobListItem], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status.value
        if company_id is not None:
            filters["company_id"] = company_id
        extra: list[ColumnElement[bool]] = []
        if status is None and not include_closed:
            extra.append(Job.status.in_([JobStatus.ACTIVE.value, JobStatus.RESUMED.value]))
        rows, total = await self.repo.list(
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        company_names = await self._company_names({row.company_id for row in rows})
        can_view_price = self._can_view_price(permissions)
        items = [
            JobListItem(
                id=row.id,
                job_number=row.job_number,
                company_id=row.company_id,
                company_name=company_names.get(row.company_id, ""),
                product_name=row.product_name,
                cylinder_count=row.cylinder_count,
                color_count=row.color_count,
                pet_size=row.pet_size,
                cylinder_cost=row.cylinder_cost if can_view_price else None,
                cylinder_location=row.cylinder_location,
                status=JobStatus(row.status),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
        return items, total

    async def get_job(self, job_id: UUID, *, permissions: frozenset[str]) -> JobResponse:
        row = await self._require_job(job_id)
        return await self._to_response(row, permissions=permissions, include_children=True)

    async def create_job(
        self,
        payload: JobCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> JobResponse:
        if payload.cylinder_cost is not None and not self._can_view_price(permissions):
            raise PermissionDeniedError("You do not have permission to set cylinder cost")
        await self._require_company(payload.company_id)
        async with transaction(self.session):
            job_number = await self.repo.next_job_number()
            values: dict[str, object] = {
                "job_number": job_number,
                "company_id": payload.company_id,
                "product_name": payload.product_name,
                "cylinder_count": payload.cylinder_count,
                "color_count": payload.color_count,
                "pet_size": payload.pet_size,
                "cylinder_cost": payload.cylinder_cost,
                "cylinder_location": payload.cylinder_location,
                "remarks": payload.remarks,
                "status": payload.status.value,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            }
            try:
                row = await self.repo.create(values)
            except IntegrityError as exc:
                raise DuplicateResourceError("Job number conflict; retry") from exc
            await replace_cylinders(
                self.session,
                row.id,
                [{"width": c.width, "circumference": c.circumference} for c in payload.cylinders],
            )
            if payload.colors:
                await replace_colors(
                    self.session,
                    row.id,
                    [{"name": c.name.strip()} for c in payload.colors],
                )
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="job",
                entity_id=row.id,
                new_values=await self._job_snapshot(row),
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def update_job(
        self,
        job_id: UUID,
        payload: JobUpdate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> JobResponse:
        values = payload.model_dump(exclude_unset=True)
        cylinders = values.pop("cylinders", None)
        colors = values.pop("colors", None)
        if "cylinder_cost" in values and not self._can_view_price(permissions):
            raise PermissionDeniedError("You do not have permission to set cylinder cost")
        if "status" in values and values["status"] is not None:
            status_value = values["status"]
            values["status"] = (
                status_value.value if isinstance(status_value, JobStatus) else str(status_value)
            )
        if "company_id" in values and values["company_id"] is not None:
            await self._require_company(values["company_id"])
        async with transaction(self.session):
            row = await self._require_job(job_id)
            if row.status == JobStatus.RETURNED.value:
                raise ValidationError("Returned jobs cannot be edited")
            old_snapshot = await self._job_snapshot(row)
            if cylinders is not None:
                count = values.get("cylinder_count", row.cylinder_count)
                if len(cylinders) != count:
                    raise ValidationError("cylinders length must match cylinder_count")
                values["cylinder_count"] = count
            if colors is not None:
                count = values.get("color_count", row.color_count or len(colors))
                if count is not None and len(colors) != count:
                    raise ValidationError("colors length must match color_count")
            values["updated_by"] = actor_user_id
            updated = await self.repo.update(job_id, values)
            if updated is None:
                raise ResourceNotFoundError("Job not found")
            if cylinders is not None:
                await replace_cylinders(
                    self.session,
                    job_id,
                    [{"width": c["width"], "circumference": c["circumference"]} for c in cylinders],
                )
            if colors is not None:
                await replace_colors(
                    self.session,
                    job_id,
                    [{"name": str(c["name"]).strip()} for c in colors],
                )
            new_snapshot = await self._job_snapshot(updated)
            if audit_field_changes(old_snapshot, new_snapshot):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="job",
                    entity_id=updated.id,
                    old_values=old_snapshot,
                    new_values=new_snapshot,
                )
            return await self._to_response(updated, permissions=permissions, include_children=True)

    async def delete_job(self, job_id: UUID, *, actor_user_id: UUID) -> JobResponse:
        async with transaction(self.session):
            row = await self._require_job(job_id)
            response = await self._to_response(
                row,
                permissions=frozenset(),
                include_children=True,
            )
            deleted = await self.repo.soft_delete(job_id)
            if deleted is None:
                raise ResourceNotFoundError("Job not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="job",
                entity_id=row.id,
                old_values=await self._job_snapshot(row),
            )
            return response

    async def pause_job(
        self,
        job_id: UUID,
        payload: JobPauseRequest,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> JobResponse:
        async with transaction(self.session):
            row = await self._require_job(job_id)
            if row.status == JobStatus.RETURNED.value:
                raise ValidationError("Returned jobs cannot be paused")
            if row.status == JobStatus.COMPLETED.value:
                raise ValidationError("Completed jobs cannot be paused")
            try:
                self.session.add(
                    JobPause(
                        job_id=job_id,
                        paused_at=utcnow(),
                        paused_by=actor_user_id,
                        pause_remarks=payload.pause_remarks,
                    )
                )
                row.status = JobStatus.PAUSED.value
                row.updated_by = actor_user_id
                await self.session.flush()
            except IntegrityError as exc:
                raise ValidationError("Job is already paused") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="job",
                entity_id=row.id,
                new_values={"event_kind": "pause", "pause_remarks": payload.pause_remarks},
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def resume_job(
        self,
        job_id: UUID,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> JobResponse:
        async with transaction(self.session):
            row = await self._require_job(job_id)
            if row.status != JobStatus.PAUSED.value:
                raise ValidationError("Job is not paused")
            pause_row = await self.session.scalar(
                select(JobPause)
                .where(JobPause.job_id == job_id, JobPause.resumed_at.is_(None))
                .limit(1)
            )
            if pause_row is None:
                raise ValidationError("No open pause record found")
            now = utcnow()
            pause_row.resumed_at = now
            pause_row.resumed_by = actor_user_id
            row.status = JobStatus.RESUMED.value
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="job",
                entity_id=row.id,
                new_values={"event_kind": "resume"},
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def upload_file(
        self,
        job_id: UUID,
        slot: str,
        *,
        filename: str | None,
        content: bytes,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> JobResponse:
        if slot not in JOB_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        row = await self._require_job(job_id)
        has_file = self._slot_has_file(row, slot)
        required = _SLOT_UPDATE[slot] if has_file else _SLOT_CREATE[slot]
        if not has_permission(permissions, required):
            raise PermissionDeniedError("You do not have permission to upload this file")
        validated = validate_upload(
            content,
            filename=filename,
            max_upload_size_mb=self.settings.max_upload_size_mb,
            allowed_mime_types=JOB_ALLOWED_MIME,
        )
        async with transaction(self.session):
            row = await self._require_job(job_id)
            new_key = (
                job_storage.build_job_file_object_key(
                    job_id=job_id, slot=slot, filename=validated.filename
                )
                if self.storage is None
                else job_storage.build_job_file_object_key(
                    job_id=job_id, slot=slot, filename=validated.filename
                )
            )
            self._set_slot(row, slot, new_key, validated)
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            if self.storage is not None:
                await self.storage.upload(
                    key=new_key,
                    body=validated.content,
                    content_type=validated.content_type,
                )
            else:
                job_storage.write_job_file(new_key, validated.content)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="job",
                entity_id=row.id,
                new_values={
                    "event_kind": "attachment",
                    "slot": slot,
                    "original_filename": validated.filename,
                    "storage_key": new_key,
                },
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def read_file(self, job_id: UUID, slot: str, *, permissions: frozenset[str]) -> tuple[bytes, str]:
        if slot not in JOB_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        if not has_permission(permissions, _SLOT_READ[slot]):
            raise PermissionDeniedError("You do not have permission to view this file")
        row = await self._require_job(job_id)
        key = self._slot_storage_key(row, slot)
        if not key:
            raise ResourceNotFoundError("File not found")
        if self.storage is not None:
            body, content_type = await self.storage.download(key=key)
            return body, content_type
        return job_storage.read_job_file(key)

    async def delete_file(
        self,
        job_id: UUID,
        slot: str,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> JobResponse:
        if slot not in JOB_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        if not has_permission(permissions, _SLOT_DELETE[slot]):
            raise PermissionDeniedError("You do not have permission to delete this file")
        async with transaction(self.session):
            row = await self._require_job(job_id)
            key = self._slot_storage_key(row, slot)
            if not key:
                raise ResourceNotFoundError("File not found")
            filename = self._slot_filename(row, slot)
            self._clear_slot(row, slot)
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            # Keep blob on disk; audit storage_key serves history previews after removal.
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="job",
                entity_id=row.id,
                new_values={
                    "event_kind": "attachment",
                    "slot": slot,
                    "original_filename": filename,
                    "storage_key": key,
                    "deleted": True,
                },
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def read_history_attachment(
        self,
        job_id: UUID,
        audit_log_id: UUID,
        *,
        permissions: frozenset[str],
    ) -> tuple[bytes, str]:
        from app.common.models.audit_log import AuditLog

        result = await self.session.execute(
            select(AuditLog).where(AuditLog.id == audit_log_id)
        )
        row = result.scalar_one_or_none()
        if row is None or row.entity_type != "job" or row.entity_id != job_id:
            raise ResourceNotFoundError("Attachment not found")
        new_values = row.new_values or {}
        if new_values.get("event_kind") != "attachment":
            raise ResourceNotFoundError("Attachment not found")
        slot = str(new_values.get("slot") or "")
        if slot not in JOB_FILE_SLOTS:
            raise ResourceNotFoundError("Attachment not found")
        if not has_permission(permissions, _SLOT_READ[slot]):
            raise PermissionDeniedError("You do not have permission to view this file")
        storage_key = new_values.get("storage_key")
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise ResourceNotFoundError("Attachment not found")
        key = storage_key.strip()
        prefix = f"jobs/{job_id}/"
        if not key.startswith(prefix):
            raise ResourceNotFoundError("Attachment not found")
        if self.storage is not None:
            return await self.storage.download(key=key)
        return job_storage.read_job_file(key)

    async def job_history(
        self,
        job_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        await self._require_job(job_id)
        return await self.history.list_for_entity(
            entity_type="job",
            entity_id=job_id,
            page=page,
        )

    async def _require_job(self, job_id: UUID) -> Job:
        row = await self.repo.get(job_id)
        if row is None:
            raise ResourceNotFoundError("Job not found")
        return row

    async def _require_company(self, company_id: UUID) -> Company:
        result = await self.session.execute(
            select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ValidationError("Company not found")
        return row

    async def _company_names(self, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(select(Company).where(Company.id.in_(ids)))
        return {row.id: row.name for row in result.scalars().all()}

    async def _user_names(self, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(select(User).where(User.id.in_(ids)))
        return {row.id: row.name for row in result.scalars().all()}

    async def _job_snapshot(self, row: Job) -> dict[str, object]:
        return {
            "job_number": row.job_number,
            "company_id": str(row.company_id),
            "product_name": row.product_name,
            "cylinder_count": row.cylinder_count,
            "color_count": row.color_count,
            "pet_size": row.pet_size,
            "cylinder_cost": jsonable_value(row.cylinder_cost),
            "cylinder_location": row.cylinder_location,
            "remarks": row.remarks,
            "status": row.status,
        }

    async def _related_documents(self, row: Job) -> list[RelatedDocumentRef]:
        related: list[RelatedDocumentRef] = []
        cylinder_return = await self.returns_repo.get_by_job(row.id)
        if cylinder_return is not None:
            related.append(
                RelatedDocumentRef(
                    document_type="cylinder_return",
                    document_id=cylinder_return.id,
                    document_number=cylinder_return.return_number,
                    status="active",
                    relationship="return",
                )
            )
        return related

    async def _to_response(
        self,
        row: Job,
        *,
        permissions: frozenset[str],
        include_children: bool,
    ) -> JobResponse:
        company_names = await self._company_names({row.company_id})
        cylinders = await load_cylinders(self.session, row.id) if include_children else []
        colors = await load_colors(self.session, row.id) if include_children else []
        pauses = await load_pauses(self.session, row.id) if include_children else []
        user_ids = {
            uid
            for pause in pauses
            for uid in (pause.paused_by, pause.resumed_by)
            if uid is not None
        }
        user_names = await self._user_names(user_ids)
        can_view_price = self._can_view_price(permissions)
        job_image = (
            self._file_meta(row, "job_image")
            if has_permission(permissions, JOB_IMAGE_READ)
            else None
        )
        challan = (
            self._file_meta(row, "challan")
            if has_permission(permissions, JOB_CHALLAN_READ)
            else None
        )
        return JobResponse(
            id=row.id,
            job_number=row.job_number,
            company_id=row.company_id,
            company_name=company_names.get(row.company_id, ""),
            product_name=row.product_name,
            cylinder_count=row.cylinder_count,
            color_count=row.color_count,
            pet_size=row.pet_size,
            cylinder_cost=row.cylinder_cost if can_view_price else None,
            cylinder_location=row.cylinder_location,
            remarks=row.remarks,
            status=JobStatus(row.status),
            cylinders=cylinders,
            colors=colors,
            pauses=[
                JobPauseResponse(
                    id=p.id,
                    paused_at=p.paused_at,
                    paused_by=p.paused_by,
                    paused_by_name=user_names.get(p.paused_by) if p.paused_by else None,
                    pause_remarks=p.pause_remarks,
                    resumed_at=p.resumed_at,
                    resumed_by=p.resumed_by,
                    resumed_by_name=user_names.get(p.resumed_by) if p.resumed_by else None,
                )
                for p in pauses
            ],
            job_image=job_image,
            challan=challan,
            related_documents=await self._related_documents(row),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _slot_storage_key(row: Job, slot: str) -> str | None:
        if slot == "job_image":
            return row.job_image_storage_key
        return row.challan_storage_key

    @staticmethod
    def _slot_filename(row: Job, slot: str) -> str | None:
        if slot == "job_image":
            return row.job_image_filename
        return row.challan_filename

    @staticmethod
    def _slot_has_file(row: Job, slot: str) -> bool:
        return bool(JobService._slot_storage_key(row, slot))

    @staticmethod
    def _file_meta(row: Job, slot: str) -> JobFileMeta | None:
        key = JobService._slot_storage_key(row, slot)
        if not key:
            return None
        if slot == "job_image":
            return JobFileMeta(
                filename=row.job_image_filename,
                content_type=row.job_image_content_type,
                size_bytes=row.job_image_size_bytes,
            )
        return JobFileMeta(
            filename=row.challan_filename,
            content_type=row.challan_content_type,
            size_bytes=row.challan_size_bytes,
        )

    @staticmethod
    def _set_slot(row: Job, slot: str, key: str, validated: Any) -> None:
        if slot == "job_image":
            row.job_image_storage_key = key
            row.job_image_filename = validated.filename
            row.job_image_content_type = validated.content_type
            row.job_image_size_bytes = validated.size_bytes
            return
        row.challan_storage_key = key
        row.challan_filename = validated.filename
        row.challan_content_type = validated.content_type
        row.challan_size_bytes = validated.size_bytes

    @staticmethod
    def _clear_slot(row: Job, slot: str) -> None:
        if slot == "job_image":
            row.job_image_storage_key = None
            row.job_image_filename = None
            row.job_image_content_type = None
            row.job_image_size_bytes = None
            return
        row.challan_storage_key = None
        row.challan_filename = None
        row.challan_content_type = None
        row.challan_size_bytes = None