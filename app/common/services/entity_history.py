"""Read audit rows for a single entity."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.pagination import PageParams
from app.common.services.audit import audit_field_changes, jsonable_value
from app.identity.audit_repository import AuditLogRepository
from app.identity.models import User
from app.identity.schemas import AuditLogUserSummary


class EntityHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    timestamp: str
    user: AuditLogUserSummary | None = None
    action: str
    entity_type: str
    entity_id: UUID | None
    module: str
    kind: str = "edit"
    summary: str | None = None
    attachment_slot: str | None = None
    storage_key: str | None = None
    attachment_deleted: bool = False
    changes: list[dict[str, object]] = Field(default_factory=list)


class EntityHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditLogRepository(session)

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        page: PageParams,
    ) -> tuple[list[EntityHistoryEntry], int]:
        rows, total = await self.repo.list_logs(
            page=page,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        user_ids = {row.user_id for row in rows if row.user_id is not None}
        users_by_id: dict[UUID, User] = {}
        if user_ids:
            result = await self.repo.session.execute(select(User).where(User.id.in_(user_ids)))
            users_by_id = {user.id: user for user in result.scalars().all()}

        entries: list[EntityHistoryEntry] = []
        for row in rows:
            old_values = row.old_values or {}
            new_values = row.new_values or {}
            event_kind = new_values.get("event_kind") or old_values.get("event_kind")
            filename = new_values.get("original_filename") or old_values.get("original_filename")
            kind = "attachment" if event_kind == "attachment" or filename else "edit"
            summary = str(filename) if kind == "attachment" and filename else None
            attachment_slot = (
                str(new_values.get("slot") or old_values.get("slot") or "")
                if kind == "attachment"
                else None
            ) or None
            storage_key_raw = new_values.get("storage_key") or old_values.get("storage_key")
            storage_key = str(storage_key_raw).strip() if storage_key_raw else None
            attachment_deleted = bool(new_values.get("deleted")) if kind == "attachment" else False
            changes = audit_field_changes(old_values, new_values) if kind == "edit" else []
            user = None
            if row.user_id and row.user_id in users_by_id:
                user = AuditLogUserSummary(id=row.user_id, name=users_by_id[row.user_id].name)
            entries.append(
                EntityHistoryEntry(
                    id=row.id,
                    timestamp=row.created_at.isoformat(),
                    user=user,
                    action=row.action,
                    entity_type=row.entity_type,
                    entity_id=row.entity_id,
                    module=row.module,
                    kind=kind,
                    summary=summary,
                    attachment_slot=attachment_slot,
                    storage_key=storage_key,
                    attachment_deleted=attachment_deleted,
                    changes=[
                        {
                            "field": change["field"],
                            "old_value": jsonable_value(change["old_value"]),
                            "new_value": jsonable_value(change["new_value"]),
                        }
                        for change in changes
                    ],
                )
            )
        return entries, total
