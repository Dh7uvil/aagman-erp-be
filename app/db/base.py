"""Declarative base and model registry."""

from sqlalchemy.orm import DeclarativeBase

from app.db.mixins import (
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Base(DeclarativeBase):
    pass


class TimestampedModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __abstract__ = True


class SoftDeleteModel(SoftDeleteMixin, TimestampedModel):
    __abstract__ = True


import app.common.models.audit_log as _audit_log  # noqa: E402, F401
import app.common.table_preferences.models as _table_preferences  # noqa: E402, F401
import app.identity.models as _identity_models  # noqa: E402, F401
import app.inventory.models as _inventory_models  # noqa: E402, F401
import app.inventory.jobs.models as _inventory_jobs_models  # noqa: E402, F401
