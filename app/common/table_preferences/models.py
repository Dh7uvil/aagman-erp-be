"""User table column preference ORM model."""

from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedModel


class UserTablePreference(TimestampedModel):
    __tablename__ = "user_table_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "table_key", name="uq_user_table_preferences_user_table"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_key: Mapped[str] = mapped_column(String(100), nullable=False)
    visible_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    column_order: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
