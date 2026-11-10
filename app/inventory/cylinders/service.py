"""Jobs business logic."""

from __future__ import annotations

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
from app.common.utils.time import utcnow
from app.core.config import get_settings
from app.core.enums import INVENTORY_MODULE, AuditAction, CylinderStatus
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
    CYLINDER_CHALLAN_CREATE,
    CYLINDER_CHALLAN_DELETE,
    CYLINDER_CHALLAN_READ,
    CYLINDER_CHALLAN_UPDATE,
    CYLINDER_IMAGE_CREATE,
    CYLINDER_IMAGE_DELETE,
    CYLINDER_IMAGE_READ,
    CYLINDER_IMAGE_UPDATE,
    CYLINDER_VIEW_PRICE,
)
from app.inventory.cylinders import storage as cylinder_storage
from app.inventory.cylinders.export_fields import total_cylinder_cost as compute_total_cylinder_cost
from app.inventory.cylinders.models import Cylinder, CylinderPause
from app.inventory.cylinders.repository import (
    CylinderRepository,
    CylinderReturnRepository,
    load_colors,
    load_cylinders,
    load_pauses,
    replace_colors,
    replace_cylinders,
)
from app.inventory.cylinders.schemas import (
    CYLINDER_FILE_SLOTS,
    CylinderCreate,
    CylinderFileMeta,
    CylinderListItem,
    CylinderPauseRequest,
    CylinderPauseResponse,
    CylinderResponse,
    CylinderResumeRequest,
    CylinderUpdate,
)

JOB_ALLOWED_MIME = (MIME_JPEG, MIME_PNG, MIME_WEBP, MIME_PDF)

_SLOT_READ = {"cylinder_image": CYLINDER_IMAGE_READ, "challan": CYLINDER_CHALLAN_READ}
_SLOT_CREATE = {"cylinder_image": CYLINDER_IMAGE_CREATE, "challan": CYLINDER_CHALLAN_CREATE}
_SLOT_UPDATE = {"cylinder_image": CYLINDER_IMAGE_UPDATE, "challan": CYLINDER_CHALLAN_UPDATE}
_SLOT_DELETE = {"cylinder_image": CYLINDER_IMAGE_DELETE, "challan": CYLINDER_CHALLAN_DELETE}


class CylinderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CylinderRepository(session)
        self.returns_repo = CylinderReturnRepository(session)
        self.audit = AuditWriter(session)
        self.history = EntityHistoryService(session)
        self.storage = get_optional_storage()
        self.settings = get_settings()

    @staticmethod
    def _can_view_price(permissions: frozenset[str]) -> bool:
        return has_permission(permissions, CYLINDER_VIEW_PRICE)

    async def list_cylinders(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        status: CylinderStatus | None,
        company_id: UUID | None,
        include_closed: bool,
        permissions: frozenset[str],
    ) -> tuple[list[CylinderListItem], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status.value
        if company_id is not None:
            filters["company_id"] = company_id
        extra: list[ColumnElement[bool]] = []
        if status is None and not include_closed:
            extra.append(
                Cylinder.status.in_(
                    [
                        CylinderStatus.ACTIVE.value,
                        CylinderStatus.COMPLETED.value,
                    ]
                )
            )
        rows, total = await self.repo.list(
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        company_names = await self._company_names({row.company_id for row in rows})
        can_view_price = self._can_view_price(permissions)
        can_view_image = has_permission(permissions, CYLINDER_IMAGE_READ)
        items = [
            CylinderListItem(
                id=row.id,
                cylinder_number=row.cylinder_number,
                company_id=row.company_id,
                company_name=company_names.get(row.company_id, ""),
                product_name=row.product_name,
                cylinder_count=row.cylinder_count,
                color_count=row.color_count,
                pet_size=row.pet_size,
                cylinder_cost=row.cylinder_cost if can_view_price else None,
                total_cylinder_cost=(
                    compute_total_cylinder_cost(row.cylinder_cost, row.cylinder_count)
                    if can_view_price
                    else None
                ),
                cylinder_location=row.cylinder_location,
                status=CylinderStatus(row.status),
                cylinder_image=(self._file_meta(row, "cylinder_image") if can_view_image else None),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
        return items, total

    async def list_cylinders_for_export(
        self,
        *,
        common_filter: BaseFilter | None,
        status: CylinderStatus | None,
        company_id: UUID | None,
        include_closed: bool,
        permissions: frozenset[str],
    ) -> list[CylinderListItem]:
        from app.common.export.fetch import assert_export_total, export_page

        rows, total = await self.list_cylinders(
            page=export_page(),
            common_filter=common_filter,
            status=status,
            company_id=company_id,
            include_closed=include_closed,
            permissions=permissions,
        )
        assert_export_total(total)
        return rows

    async def get_cylinder(
        self, cylinder_id: UUID, *, permissions: frozenset[str]
    ) -> CylinderResponse:
        row = await self._require_cylinder(cylinder_id)
        return await self._to_response(row, permissions=permissions, include_children=True)

    async def create_cylinder(
        self,
        payload: CylinderCreate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> CylinderResponse:
        if payload.cylinder_cost is not None and not self._can_view_price(permissions):
            raise PermissionDeniedError("You do not have permission to set cylinder cost")
        await self._require_company(payload.company_id)
        async with transaction(self.session):
            cylinder_number = await self.repo.next_cylinder_number()
            values: dict[str, object] = {
                "cylinder_number": cylinder_number,
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
                raise DuplicateResourceError("Cylinder number conflict; retry") from exc
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
                entity_type="cylinder",
                entity_id=row.id,
                new_values=await self._cylinder_snapshot(row),
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def update_cylinder(
        self,
        cylinder_id: UUID,
        payload: CylinderUpdate,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> CylinderResponse:
        values = payload.model_dump(exclude_unset=True)
        cylinders = values.pop("cylinders", None)
        colors = values.pop("colors", None)
        if "cylinder_cost" in values and not self._can_view_price(permissions):
            raise PermissionDeniedError("You do not have permission to set cylinder cost")
        if "status" in values and values["status"] is not None:
            status_value = values["status"]
            values["status"] = (
                status_value.value
                if isinstance(status_value, CylinderStatus)
                else str(status_value)
            )
        if "company_id" in values and values["company_id"] is not None:
            await self._require_company(values["company_id"])
        async with transaction(self.session):
            row = await self._require_cylinder(cylinder_id)
            if row.status == CylinderStatus.RETURNED.value:
                raise ValidationError("Returned cylinders cannot be edited")
            old_snapshot = await self._cylinder_snapshot(row)
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
            updated = await self.repo.update(cylinder_id, values)
            if updated is None:
                raise ResourceNotFoundError("Cylinder not found")
            if cylinders is not None:
                await replace_cylinders(
                    self.session,
                    cylinder_id,
                    [{"width": c["width"], "circumference": c["circumference"]} for c in cylinders],
                )
            if colors is not None:
                await replace_colors(
                    self.session,
                    cylinder_id,
                    [{"name": str(c["name"]).strip()} for c in colors],
                )
            new_snapshot = await self._cylinder_snapshot(updated)
            if audit_field_changes(old_snapshot, new_snapshot):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=INVENTORY_MODULE,
                    entity_type="cylinder",
                    entity_id=updated.id,
                    old_values=old_snapshot,
                    new_values=new_snapshot,
                )
            return await self._to_response(updated, permissions=permissions, include_children=True)

    async def delete_cylinder(self, cylinder_id: UUID, *, actor_user_id: UUID) -> CylinderResponse:
        async with transaction(self.session):
            row = await self._require_cylinder(cylinder_id)
            response = await self._to_response(
                row,
                permissions=frozenset(),
                include_children=True,
            )
            deleted = await self.repo.soft_delete(cylinder_id)
            if deleted is None:
                raise ResourceNotFoundError("Cylinder not found")
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="cylinder",
                entity_id=row.id,
                old_values=await self._cylinder_snapshot(row),
            )
            return response

    async def pause_cylinder(
        self,
        cylinder_id: UUID,
        payload: CylinderPauseRequest,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> CylinderResponse:
        async with transaction(self.session):
            row = await self._require_cylinder(cylinder_id)
            if row.status == CylinderStatus.RETURNED.value:
                raise ValidationError("Returned cylinders cannot be paused")
            if row.status == CylinderStatus.COMPLETED.value:
                raise ValidationError("Completed cylinders cannot be paused")
            try:
                self.session.add(
                    CylinderPause(
                        cylinder_id=cylinder_id,
                        paused_at=utcnow(),
                        paused_by=actor_user_id,
                        pause_remarks=payload.pause_remarks,
                    )
                )
                row.status = CylinderStatus.PAUSED.value
                row.updated_by = actor_user_id
                await self.session.flush()
            except IntegrityError as exc:
                raise ValidationError("Cylinder is already paused") from exc
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="cylinder",
                entity_id=row.id,
                new_values={"event_kind": "pause", "pause_remarks": payload.pause_remarks},
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def resume_cylinder(
        self,
        cylinder_id: UUID,
        payload: CylinderResumeRequest,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> CylinderResponse:
        async with transaction(self.session):
            row = await self._require_cylinder(cylinder_id)
            if row.status != CylinderStatus.PAUSED.value:
                raise ValidationError("Cylinder is not paused")
            pause_row = await self.session.scalar(
                select(CylinderPause)
                .where(CylinderPause.cylinder_id == cylinder_id, CylinderPause.resumed_at.is_(None))
                .limit(1)
            )
            if pause_row is None:
                raise ValidationError("No open pause record found")
            now = utcnow()
            pause_row.resumed_at = now
            pause_row.resumed_by = actor_user_id
            pause_row.resume_remarks = payload.resume_remarks
            row.status = CylinderStatus.ACTIVE.value
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="cylinder",
                entity_id=row.id,
                new_values={"event_kind": "resume", "resume_remarks": payload.resume_remarks},
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def upload_file(
        self,
        cylinder_id: UUID,
        slot: str,
        *,
        filename: str | None,
        content: bytes,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> CylinderResponse:
        if slot not in CYLINDER_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        row = await self._require_cylinder(cylinder_id)
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
            row = await self._require_cylinder(cylinder_id)
            new_key = (
                cylinder_storage.build_cylinder_file_object_key(
                    cylinder_id=cylinder_id, slot=slot, filename=validated.filename
                )
                if self.storage is None
                else cylinder_storage.build_cylinder_file_object_key(
                    cylinder_id=cylinder_id, slot=slot, filename=validated.filename
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
                cylinder_storage.write_cylinder_file(new_key, validated.content)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="cylinder",
                entity_id=row.id,
                new_values={
                    "event_kind": "attachment",
                    "slot": slot,
                    "original_filename": validated.filename,
                    "storage_key": new_key,
                },
            )
            return await self._to_response(row, permissions=permissions, include_children=True)

    async def read_file(
        self, cylinder_id: UUID, slot: str, *, permissions: frozenset[str]
    ) -> tuple[bytes, str]:
        if slot not in CYLINDER_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        if not has_permission(permissions, _SLOT_READ[slot]):
            raise PermissionDeniedError("You do not have permission to view this file")
        row = await self._require_cylinder(cylinder_id)
        key = self._slot_storage_key(row, slot)
        if not key:
            raise ResourceNotFoundError("File not found")
        if self.storage is not None:
            body, content_type = await self.storage.download(key=key)
            return body, content_type
        return cylinder_storage.read_cylinder_file(key)

    async def delete_file(
        self,
        cylinder_id: UUID,
        slot: str,
        *,
        actor_user_id: UUID,
        permissions: frozenset[str],
    ) -> CylinderResponse:
        if slot not in CYLINDER_FILE_SLOTS:
            raise ValidationError("Invalid file slot")
        if not has_permission(permissions, _SLOT_DELETE[slot]):
            raise PermissionDeniedError("You do not have permission to delete this file")
        async with transaction(self.session):
            row = await self._require_cylinder(cylinder_id)
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
                entity_type="cylinder",
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
        cylinder_id: UUID,
        audit_log_id: UUID,
        *,
        permissions: frozenset[str],
    ) -> tuple[bytes, str]:
        from app.common.models.audit_log import AuditLog

        result = await self.session.execute(select(AuditLog).where(AuditLog.id == audit_log_id))
        row = result.scalar_one_or_none()
        if row is None or row.entity_type != "cylinder" or row.entity_id != cylinder_id:
            raise ResourceNotFoundError("Attachment not found")
        new_values = row.new_values or {}
        if new_values.get("event_kind") != "attachment":
            raise ResourceNotFoundError("Attachment not found")
        slot = str(new_values.get("slot") or "")
        if slot not in CYLINDER_FILE_SLOTS:
            raise ResourceNotFoundError("Attachment not found")
        if not has_permission(permissions, _SLOT_READ[slot]):
            raise PermissionDeniedError("You do not have permission to view this file")
        storage_key = new_values.get("storage_key")
        if not isinstance(storage_key, str) or not storage_key.strip():
            raise ResourceNotFoundError("Attachment not found")
        key = storage_key.strip()
        prefix = f"cylinders/{cylinder_id}/"
        if not key.startswith(prefix):
            raise ResourceNotFoundError("Attachment not found")
        if self.storage is not None:
            return await self.storage.download(key=key)
        return cylinder_storage.read_cylinder_file(key)

    async def cylinder_history(
        self,
        cylinder_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        await self._require_cylinder(cylinder_id)
        return await self.history.list_for_entity(
            entity_type="cylinder",
            entity_id=cylinder_id,
            page=page,
        )

    async def _require_cylinder(self, cylinder_id: UUID) -> Cylinder:
        row = await self.repo.get(cylinder_id)
        if row is None:
            raise ResourceNotFoundError("Cylinder not found")
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

    async def _cylinder_snapshot(self, row: Cylinder) -> dict[str, object]:
        company_names = await self._company_names({row.company_id})
        return {
            "cylinder_number": row.cylinder_number,
            "company_name": company_names.get(row.company_id, ""),
            "product_name": row.product_name,
            "cylinder_count": row.cylinder_count,
            "color_count": row.color_count,
            "pet_size": row.pet_size,
            "cylinder_cost": jsonable_value(row.cylinder_cost),
            "cylinder_location": row.cylinder_location,
            "remarks": row.remarks,
            "status": row.status,
        }

    async def _related_documents(self, row: Cylinder) -> list[RelatedDocumentRef]:
        related: list[RelatedDocumentRef] = []
        cylinder_return = await self.returns_repo.get_by_cylinder(row.id)
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
        row: Cylinder,
        *,
        permissions: frozenset[str],
        include_children: bool,
    ) -> CylinderResponse:
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
        cylinder_image = (
            self._file_meta(row, "cylinder_image")
            if has_permission(permissions, CYLINDER_IMAGE_READ)
            else None
        )
        challan = (
            self._file_meta(row, "challan")
            if has_permission(permissions, CYLINDER_CHALLAN_READ)
            else None
        )
        return CylinderResponse(
            id=row.id,
            cylinder_number=row.cylinder_number,
            company_id=row.company_id,
            company_name=company_names.get(row.company_id, ""),
            product_name=row.product_name,
            cylinder_count=row.cylinder_count,
            color_count=row.color_count,
            pet_size=row.pet_size,
            cylinder_cost=row.cylinder_cost if can_view_price else None,
            cylinder_location=row.cylinder_location,
            remarks=row.remarks,
            status=CylinderStatus(row.status),
            cylinders=cylinders,
            colors=colors,
            pauses=[
                CylinderPauseResponse(
                    id=p.id,
                    paused_at=p.paused_at,
                    paused_by=p.paused_by,
                    paused_by_name=user_names.get(p.paused_by) if p.paused_by else None,
                    pause_remarks=p.pause_remarks,
                    resumed_at=p.resumed_at,
                    resumed_by=p.resumed_by,
                    resumed_by_name=user_names.get(p.resumed_by) if p.resumed_by else None,
                    resume_remarks=p.resume_remarks,
                )
                for p in pauses
            ],
            cylinder_image=cylinder_image,
            challan=challan,
            related_documents=await self._related_documents(row),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _slot_storage_key(row: Cylinder, slot: str) -> str | None:
        if slot == "cylinder_image":
            return row.cylinder_image_storage_key
        return row.challan_storage_key

    @staticmethod
    def _slot_filename(row: Cylinder, slot: str) -> str | None:
        if slot == "cylinder_image":
            return row.cylinder_image_filename
        return row.challan_filename

    @staticmethod
    def _slot_has_file(row: Cylinder, slot: str) -> bool:
        return bool(CylinderService._slot_storage_key(row, slot))

    @staticmethod
    def _file_meta(row: Cylinder, slot: str) -> CylinderFileMeta | None:
        key = CylinderService._slot_storage_key(row, slot)
        if not key:
            return None
        if slot == "cylinder_image":
            return CylinderFileMeta(
                filename=row.cylinder_image_filename,
                content_type=row.cylinder_image_content_type,
                size_bytes=row.cylinder_image_size_bytes,
            )
        return CylinderFileMeta(
            filename=row.challan_filename,
            content_type=row.challan_content_type,
            size_bytes=row.challan_size_bytes,
        )

    @staticmethod
    def _set_slot(row: Cylinder, slot: str, key: str, validated: Any) -> None:
        if slot == "cylinder_image":
            row.cylinder_image_storage_key = key
            row.cylinder_image_filename = validated.filename
            row.cylinder_image_content_type = validated.content_type
            row.cylinder_image_size_bytes = validated.size_bytes
            return
        row.challan_storage_key = key
        row.challan_filename = validated.filename
        row.challan_content_type = validated.content_type
        row.challan_size_bytes = validated.size_bytes

    @staticmethod
    def _clear_slot(row: Cylinder, slot: str) -> None:
        if slot == "cylinder_image":
            row.cylinder_image_storage_key = None
            row.cylinder_image_filename = None
            row.cylinder_image_content_type = None
            row.cylinder_image_size_bytes = None
            return
        row.challan_storage_key = None
        row.challan_filename = None
        row.challan_content_type = None
        row.challan_size_bytes = None
