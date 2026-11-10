from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.table_preferences.models import UserTablePreference


class UserTablePreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, table_key: str) -> UserTablePreference | None:
        result = await self.session.execute(
            select(UserTablePreference).where(
                UserTablePreference.user_id == user_id,
                UserTablePreference.table_key == table_key,
            ),
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: UUID,
        table_key: str,
        *,
        visible_columns: list[str],
        column_order: list[str],
    ) -> UserTablePreference:
        row = await self.get(user_id, table_key)
        if row is None:
            row = UserTablePreference(
                user_id=user_id,
                table_key=table_key,
                visible_columns=visible_columns,
                column_order=column_order,
            )
            self.session.add(row)
        else:
            row.visible_columns = visible_columns
            row.column_order = column_order
        await self.session.flush()
        return row

    async def upsert_export(
        self,
        user_id: UUID,
        table_key: str,
        *,
        visible_columns: list[str],
        column_order: list[str],
        export_visible_columns: list[str],
        export_column_order: list[str],
        export_format: str | None,
    ) -> UserTablePreference:
        row = await self.get(user_id, table_key)
        if row is None:
            entry_visible = visible_columns
            entry_order = column_order
            row = UserTablePreference(
                user_id=user_id,
                table_key=table_key,
                visible_columns=entry_visible,
                column_order=entry_order,
            )
            self.session.add(row)
        row.export_visible_columns = export_visible_columns
        row.export_column_order = export_column_order
        row.export_format = export_format
        await self.session.flush()
        return row

    async def clear_export(self, user_id: UUID, table_key: str) -> None:
        row = await self.get(user_id, table_key)
        if row is None:
            return
        row.export_visible_columns = None
        row.export_column_order = None
        row.export_format = None
        await self.session.flush()

    async def delete(self, user_id: UUID, table_key: str) -> None:
        await self.session.execute(
            delete(UserTablePreference).where(
                UserTablePreference.user_id == user_id,
                UserTablePreference.table_key == table_key,
            ),
        )
