"""Read APIs for the append-only audit trail."""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.models.audit_log import AuditLog
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import audit_field_changes
from app.core.exceptions import ResourceNotFoundError
from app.identity.audit_repository import AuditLogRepository
from app.identity.models import User
from app.identity.org_repository import OrganizationRepository
from app.identity.schemas import (
    AuditLogChange,
    AuditLogDetailResponse,
    AuditLogResponse,
    AuditLogSummaryResponse,
    AuditLogUserSummary,
)


class AuditLogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditLogRepository(session)
        self.org = OrganizationRepository(session)

    async def list_logs(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
        action: str | None = None,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
    ) -> tuple[list[AuditLogResponse], int]:
        rows, total = await self.repo.list_logs(
            page=page,
            common_filter=common_filter,
            module=module,
            action=action,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        user_ids = [row.user_id for row in rows if row.user_id is not None]
        users = await self.org.get_users_by_ids(user_ids)
        return [self._to_response(row, users) for row in rows], total

    async def summarize(self, *, common_filter: BaseFilter | None = None) -> AuditLogSummaryResponse:
        date_filter = None
        if common_filter is not None:
            date_filter = BaseFilter(
                date_from=common_filter.date_from,
                date_to=common_filter.date_to,
            )
        total_events, unique_users, failed_attempts, admin_actions = await self.repo.summarize(
            common_filter=date_filter,
        )
        return AuditLogSummaryResponse(
            total_events=total_events,
            unique_users=unique_users,
            failed_attempts=failed_attempts,
            admin_actions=admin_actions,
        )

    async def get_log(self, audit_log_id: UUID) -> AuditLogDetailResponse:
        row = await self.repo.get(audit_log_id)
        if row is None:
            raise ResourceNotFoundError("Audit log not found")
        users = await self.org.get_users_by_ids([row.user_id] if row.user_id else [])
        return self._to_detail_response(row, users)

    async def export_csv(
        self,
        *,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
        action: str | None = None,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
    ) -> str:
        rows = await self.repo.export_logs(
            common_filter=common_filter,
            module=module,
            action=action,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        users = await self.org.get_users_by_ids(
            [row.user_id for row in rows if row.user_id is not None],
        )
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "timestamp",
                "user",
                "email",
                "action",
                "module",
                "entity_type",
                "entity_id",
                "status",
                "ip_address",
                "user_agent",
                "old_values",
                "new_values",
            ],
        )
        writer.writeheader()
        for row in rows:
            user = users.get(row.user_id) if row.user_id is not None else None
            writer.writerow(
                {
                    "timestamp": row.created_at.isoformat(),
                    "user": user.name if user else "",
                    "email": user.email if user else "",
                    "action": row.action,
                    "module": row.module,
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id) if row.entity_id else "",
                    "status": row.status,
                    "ip_address": row.ip_address or "",
                    "user_agent": row.user_agent or "",
                    "old_values": _json_cell(row.old_values),
                    "new_values": _json_cell(row.new_values),
                }
            )
        return buffer.getvalue()

    @staticmethod
    def _to_response(row: AuditLog, users: dict[UUID, User]) -> AuditLogResponse:
        user = users.get(row.user_id) if row.user_id is not None else None
        user_summary = AuditLogUserSummary.model_validate(user) if user is not None else None
        return AuditLogResponse(
            id=row.id,
            timestamp=row.created_at,
            user=user_summary,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            module=row.module,
            ip_address=row.ip_address,
            status=row.status,
        )

    @classmethod
    def _to_detail_response(cls, row: AuditLog, users: dict[UUID, User]) -> AuditLogDetailResponse:
        base = cls._to_response(row, users)
        old_values = _json_object(row.old_values)
        new_values = _json_object(row.new_values)
        return AuditLogDetailResponse(
            **base.model_dump(),
            user_agent=row.user_agent,
            old_values=old_values,
            new_values=new_values,
            changes=[
                AuditLogChange(
                    field=change["field"],
                    old_value=change["old_value"],
                    new_value=change["new_value"],
                )
                for change in audit_field_changes(old_values, new_values)
            ],
        )


def _json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _json_cell(value: object) -> str:
    if value is None:
        return ""
    return json.dumps(value, default=str, sort_keys=True)
