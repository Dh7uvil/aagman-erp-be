"""Request and response schemas for user table column preferences."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExportFormat = Literal["csv", "xlsx"]


class TablePreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_columns: list[str] = Field(min_length=1, max_length=50)
    column_order: list[str] = Field(min_length=1, max_length=50)


class TableExportPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_visible_columns: list[str] = Field(min_length=1, max_length=50)
    export_column_order: list[str] = Field(min_length=1, max_length=50)
    export_format: ExportFormat | None = None


class TablePreferenceResponse(BaseModel):
    table_key: str
    visible_columns: list[str]
    column_order: list[str]
    is_default: bool
    export_visible_columns: list[str]
    export_column_order: list[str]
    export_format: ExportFormat | None = None
    export_is_default: bool
