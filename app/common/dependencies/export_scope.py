"""Export row scope: filtered list criteria vs entire module."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, Query

ExportScope = Literal["filtered", "all"]


def get_export_scope(
    export_scope: Annotated[
        ExportScope,
        Query(
            description=(
                "filtered: all rows matching list query filters; "
                "all: entire module (permissions still apply)."
            ),
        ),
    ] = "filtered",
) -> ExportScope:
    return export_scope


ExportScopeQuery = Annotated[ExportScope, Depends(get_export_scope)]


def is_full_module_export(scope: ExportScope) -> bool:
    return scope == "all"
