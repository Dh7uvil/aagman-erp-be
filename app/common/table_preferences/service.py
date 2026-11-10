from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.services.audit import AuditWriter
from app.common.table_preferences.catalog import get_table_catalog
from app.common.table_preferences.export_normalize import (
    merge_export_stored,
    validate_export_update,
)
from app.common.table_preferences.normalize import merge_stored, validate_update
from app.common.table_preferences.repository import UserTablePreferenceRepository
from app.common.table_preferences.schemas import (
    TableExportPreferenceUpdate,
    TablePreferenceResponse,
    TablePreferenceUpdate,
)
from app.core.enums import IDENTITY_MODULE, AuditAction
from app.core.exceptions import ResourceNotFoundError
from app.db.session import transaction


class TablePreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserTablePreferenceRepository(session)
        self.audit = AuditWriter(session)

    def _require_catalog(self, table_key: str):
        entry = get_table_catalog(table_key)
        if entry is None:
            raise ResourceNotFoundError("Unknown table")
        return entry

    def _export_fields(
        self,
        entry,
        *,
        row,
        permissions: frozenset[str],
        list_visible_columns: list[str] | None = None,
        list_column_order: list[str] | None = None,
    ) -> tuple[list[str], list[str], str | None, bool]:
        has_export = row is not None and (
            row.export_visible_columns is not None or row.export_column_order is not None
        )
        merged_export = merge_export_stored(
            entry,
            export_visible_columns=row.export_visible_columns if row else None,
            export_column_order=row.export_column_order if row else None,
            permissions=permissions,
            fallback_visible_columns=list_visible_columns,
            fallback_column_order=list_column_order,
        )
        export_format = row.export_format if row is not None else None
        return (
            merged_export.export_visible_columns,
            merged_export.export_column_order,
            export_format,
            not has_export,
        )

    def _default_response(
        self, table_key: str, permissions: frozenset[str]
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        list_visible = entry.default_visible(permissions)
        list_order = entry.default_order(permissions)
        export_visible, export_order, _, export_is_default = self._export_fields(
            entry,
            row=None,
            permissions=permissions,
            list_visible_columns=list_visible,
            list_column_order=list_order,
        )
        return TablePreferenceResponse(
            table_key=table_key,
            visible_columns=entry.default_visible(permissions),
            column_order=entry.default_order(permissions),
            is_default=True,
            export_visible_columns=export_visible,
            export_column_order=export_order,
            export_format=None,
            export_is_default=export_is_default,
        )

    def _to_response(
        self,
        table_key: str,
        entry,
        *,
        visible_columns: list[str],
        column_order: list[str],
        is_default: bool,
        row,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        export_visible, export_order, export_format, export_is_default = self._export_fields(
            entry,
            row=row,
            permissions=permissions,
            list_visible_columns=visible_columns,
            list_column_order=column_order,
        )
        return TablePreferenceResponse(
            table_key=table_key,
            visible_columns=visible_columns,
            column_order=column_order,
            is_default=is_default,
            export_visible_columns=export_visible,
            export_column_order=export_order,
            export_format=export_format,
            export_is_default=export_is_default,
        )

    async def get(
        self,
        user_id: UUID,
        table_key: str,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        row = await self.repo.get(user_id, table_key)
        if row is None:
            return self._default_response(table_key, permissions)
        merged = merge_stored(
            entry,
            visible_columns=row.visible_columns,
            column_order=row.column_order,
            permissions=permissions,
        )
        return self._to_response(
            table_key,
            entry,
            visible_columns=merged.visible_columns,
            column_order=merged.column_order,
            is_default=False,
            row=row,
            permissions=permissions,
        )

    async def upsert(
        self,
        user_id: UUID,
        table_key: str,
        payload: TablePreferenceUpdate,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        normalized = validate_update(
            entry,
            visible_columns=payload.visible_columns,
            column_order=payload.column_order,
            permissions=permissions,
        )
        try:
            async with transaction(self.session):
                await self.repo.upsert(
                    user_id,
                    table_key,
                    visible_columns=normalized.visible_columns,
                    column_order=normalized.column_order,
                )
                await self.audit.write(
                    user_id=user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user_table_preference",
                    entity_id=user_id,
                    new_values={"table_key": table_key},
                )
        except IntegrityError:
            async with transaction(self.session):
                await self.repo.upsert(
                    user_id,
                    table_key,
                    visible_columns=normalized.visible_columns,
                    column_order=normalized.column_order,
                )
        row = await self.repo.get(user_id, table_key)
        return self._to_response(
            table_key,
            entry,
            visible_columns=normalized.visible_columns,
            column_order=normalized.column_order,
            is_default=False,
            row=row,
            permissions=permissions,
        )

    async def upsert_export(
        self,
        user_id: UUID,
        table_key: str,
        payload: TableExportPreferenceUpdate,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        normalized = validate_export_update(
            entry,
            export_visible_columns=payload.export_visible_columns,
            export_column_order=payload.export_column_order,
            permissions=permissions,
        )
        list_defaults = merge_stored(
            entry,
            visible_columns=None,
            column_order=None,
            permissions=permissions,
        )
        existing = await self.repo.get(user_id, table_key)
        list_visible = (
            existing.visible_columns if existing is not None else list_defaults.visible_columns
        )
        list_order = existing.column_order if existing is not None else list_defaults.column_order
        async with transaction(self.session):
            await self.repo.upsert_export(
                user_id,
                table_key,
                visible_columns=list_visible,
                column_order=list_order,
                export_visible_columns=normalized.export_visible_columns,
                export_column_order=normalized.export_column_order,
                export_format=payload.export_format,
            )
        row = await self.repo.get(user_id, table_key)
        list_merged = merge_stored(
            entry,
            visible_columns=row.visible_columns if row else None,
            column_order=row.column_order if row else None,
            permissions=permissions,
        )
        return self._to_response(
            table_key,
            entry,
            visible_columns=list_merged.visible_columns,
            column_order=list_merged.column_order,
            is_default=False,
            row=row,
            permissions=permissions,
        )

    async def reset(
        self,
        user_id: UUID,
        table_key: str,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        self._require_catalog(table_key)
        async with transaction(self.session):
            await self.repo.delete(user_id, table_key)
            await self.audit.write(
                user_id=user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user_table_preference",
                entity_id=user_id,
                new_values={"table_key": table_key, "reset": True},
            )
        return self._default_response(table_key, permissions)

    async def reset_export(
        self,
        user_id: UUID,
        table_key: str,
        *,
        permissions: frozenset[str],
    ) -> TablePreferenceResponse:
        entry = self._require_catalog(table_key)
        async with transaction(self.session):
            await self.repo.clear_export(user_id, table_key)
        row = await self.repo.get(user_id, table_key)
        if row is None:
            return self._default_response(table_key, permissions)
        merged = merge_stored(
            entry,
            visible_columns=row.visible_columns,
            column_order=row.column_order,
            permissions=permissions,
        )
        return self._to_response(
            table_key,
            entry,
            visible_columns=merged.visible_columns,
            column_order=merged.column_order,
            is_default=False,
            row=row,
            permissions=permissions,
        )

    async def get_export_columns(
        self,
        user_id: UUID,
        table_key: str,
        *,
        permissions: frozenset[str],
    ) -> tuple[list[str], str | None]:
        """Return ordered visible export column keys and saved format."""

        response = await self.get(user_id, table_key, permissions=permissions)
        from app.common.export.resolve import ResolvedExportColumns, ordered_visible_keys

        resolved = ResolvedExportColumns(
            visible_keys=response.export_visible_columns,
            order=response.export_column_order,
        )
        return ordered_visible_keys(resolved), response.export_format
