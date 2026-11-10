"""Allowlists and defaults for list-table columns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PINNED_COLUMN_COUNT = 2
LOCKED_COLUMN_ID = "actions"

AggregateKind = Literal["sum"]

_AGGREGATE_SUM_KEYS = frozenset(
    {
        "rolls",
        "total_kg",
        "users_count",
        "cylinder_count",
        "cylinder_cost",
        "total_cylinder_cost",
        "drum_count",
        "drum_qty",
        "total_qty",
        "total_rate",
        "in_rolls",
        "in_kg",
        "out_rolls",
        "out_kg",
        "closing_rolls",
        "closing_kg",
        "in_drums",
        "in_qty",
        "out_drums",
        "out_qty",
        "closing_drums",
        "closing_qty",
    }
)


@dataclass(frozen=True, slots=True)
class TableColumnSpec:
    key: str
    default_visible: bool = True
    required_permission: str | None = None
    exportable: bool = True
    aggregate: AggregateKind | None = None


def col(
    key: str,
    *,
    default_visible: bool = True,
    required_permission: str | None = None,
    exportable: bool = True,
    aggregate: AggregateKind | None = None,
) -> TableColumnSpec:
    if aggregate is None and key in _AGGREGATE_SUM_KEYS:
        aggregate = "sum"
    return TableColumnSpec(
        key=key,
        default_visible=default_visible,
        required_permission=required_permission,
        exportable=exportable,
        aggregate=aggregate,
    )


@dataclass(frozen=True, slots=True)
class TableCatalogEntry:
    table_key: str
    columns: tuple[TableColumnSpec, ...]
    pinned_count: int = PINNED_COLUMN_COUNT

    def effective_columns(self, permissions: frozenset[str]) -> tuple[TableColumnSpec, ...]:
        return tuple(
            column
            for column in self.columns
            if column.required_permission is None or column.required_permission in permissions
        )

    def allowed_keys(self, permissions: frozenset[str]) -> tuple[str, ...]:
        return tuple(column.key for column in self.effective_columns(permissions))

    def default_visible(self, permissions: frozenset[str]) -> list[str]:
        return [
            column.key for column in self.effective_columns(permissions) if column.default_visible
        ]

    def default_order(self, permissions: frozenset[str]) -> list[str]:
        return list(self.allowed_keys(permissions))

    def pinned_keys(self, permissions: frozenset[str]) -> tuple[str, ...]:
        return tuple(self.default_visible(permissions)[: self.pinned_count])

    def exportable_columns(self, permissions: frozenset[str]) -> tuple[TableColumnSpec, ...]:
        return tuple(column for column in self.effective_columns(permissions) if column.exportable)

    def exportable_keys(self, permissions: frozenset[str]) -> tuple[str, ...]:
        return tuple(column.key for column in self.exportable_columns(permissions))

    def aggregate_keys(self, permissions: frozenset[str]) -> tuple[str, ...]:
        return tuple(
            column.key
            for column in self.exportable_columns(permissions)
            if column.aggregate == "sum"
        )

    def default_export_visible(self, permissions: frozenset[str]) -> list[str]:
        return [
            column.key for column in self.exportable_columns(permissions) if column.default_visible
        ]

    def default_export_order(self, permissions: frozenset[str]) -> list[str]:
        return list(self.exportable_keys(permissions))

    def column_by_key(self, key: str) -> TableColumnSpec | None:
        for column in self.columns:
            if column.key == key:
                return column
        return None


def _cols(*keys: str) -> tuple[TableColumnSpec, ...]:
    return tuple(col(key) for key in keys)


def _hidden(*keys: str) -> tuple[TableColumnSpec, ...]:
    return tuple(col(key, default_visible=False) for key in keys)


def _entry(table_key: str, visible: tuple[str, ...], *hidden: TableColumnSpec) -> TableCatalogEntry:
    return TableCatalogEntry(table_key=table_key, columns=_cols(*visible) + hidden)


TABLE_CATALOG: dict[str, TableCatalogEntry] = {
    entry.table_key: entry
    for entry in (
        _entry(
            "identity.users",
            ("email", "user", "department", "designation", "role", "status"),
            *_hidden("phone", "branch", "last_login_at", "created_at", "updated_at"),
        ),
        _entry(
            "identity.roles",
            ("name", "description", "type", "users_count", "created_at"),
            *_hidden("updated_at"),
        ),
        _entry(
            "identity.branches",
            ("code", "name", "phone", "timezone", "status"),
            *_hidden("address", "created_at", "updated_at"),
        ),
        _entry(
            "identity.departments",
            ("code", "name", "branch", "manager"),
            *_hidden("created_at", "updated_at"),
        ),
        _entry(
            "identity.warehouses",
            ("code", "name", "phone", "default", "active"),
            *_hidden("address", "created_at", "updated_at"),
        ),
        _entry(
            "identity.companies",
            ("name", "email", "phone", "address"),
            *_hidden("bill_to_address", "ship_to_address", "id", "created_at", "updated_at"),
        ),
        _entry(
            "identity.audit_logs",
            (
                "log_id",
                "action",
                "timestamp",
                "user",
                "resource",
                "resource_id",
                "module",
                "ip_address",
                "status",
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.materials",
            columns=(
                col("company"),
                col("product"),
                col("micron"),
                col("size"),
                col("rolls"),
                col("total_kg"),
                col(
                    "price_per_unit",
                    default_visible=False,
                    required_permission="inventory.material.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.material.view_price",
                ),
                col("active", default_visible=False),
            ),
        ),
        _entry(
            "inventory.units",
            ("code", "name", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        TableCatalogEntry(
            table_key="inventory.materials_report",
            pinned_count=0,
            columns=(
                col("product"),
                col("micron"),
                col("size"),
                col("in_rolls"),
                col("in_kg"),
                col("out_rolls"),
                col("out_kg"),
                col("closing_rolls"),
                col("closing_kg"),
                col(
                    "price_per_unit",
                    default_visible=True,
                    required_permission="inventory.material.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.material.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.cylinders",
            columns=(
                col("cylinder_number"),
                col("company"),
                col("product"),
                col("status"),
                col("cylinder_count"),
                col("pet_size", default_visible=False),
                col("cylinder_location", default_visible=False),
                col(
                    "cylinder_cost",
                    default_visible=False,
                    required_permission="inventory.cylinder.view_price",
                ),
                col(
                    "total_cylinder_cost",
                    default_visible=False,
                    required_permission="inventory.cylinder.view_price",
                ),
                col("created_at", default_visible=False),
                col("updated_at", default_visible=False),
            ),
        ),
        _entry(
            "inventory.cylinder_returns",
            ("return_number", "customer", "return_date", "cylinder", "remarks"),
            *_hidden("created_at", "updated_at"),
        ),
        TableCatalogEntry(
            table_key="inventory.inks",
            columns=(
                col("company"),
                col("brand"),
                col("color"),
                col("hex", default_visible=False),
                col("drum_count"),
                col("drum_qty", default_visible=False),
                col("unit", default_visible=False),
                col("total_qty"),
                col(
                    "ink_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                col(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                col("created_at", default_visible=False),
                col("updated_at", default_visible=False),
            ),
        ),
        _entry(
            "inventory.ink_colors",
            ("name", "hex", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        _entry(
            "inventory.ink_brands",
            ("name", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        TableCatalogEntry(
            table_key="inventory.inks_report",
            pinned_count=0,
            columns=(
                col("company"),
                col("brand"),
                col("color"),
                col("in_drums"),
                col("in_qty"),
                col("out_drums"),
                col("out_qty"),
                col("closing_drums"),
                col("closing_qty"),
                col(
                    "ink_rate",
                    required_permission="inventory.ink.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.ink_color_usage",
            pinned_count=0,
            columns=(
                col("company"),
                col("brand"),
                col("drum_count"),
                col("drum_qty", default_visible=False),
                col("unit", default_visible=False),
                col("total_qty"),
                col(
                    "ink_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                col(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                col("sheet"),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.adhesives",
            columns=(
                col("company"),
                col("brand"),
                col("code"),
                col("drum_count"),
                col("drum_qty", default_visible=False),
                col("unit", default_visible=False),
                col("total_qty"),
                col(
                    "adhesive_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                col(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                col("created_at", default_visible=False),
                col("updated_at", default_visible=False),
            ),
        ),
        _entry(
            "inventory.adhesive_codes",
            ("code", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        _entry(
            "inventory.adhesive_brands",
            ("name", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        TableCatalogEntry(
            table_key="inventory.adhesives_report",
            pinned_count=0,
            columns=(
                col("company"),
                col("brand"),
                col("code"),
                col("in_drums"),
                col("in_qty"),
                col("out_drums"),
                col("out_qty"),
                col("closing_drums"),
                col("closing_qty"),
                col(
                    "adhesive_rate",
                    required_permission="inventory.adhesive.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.adhesive_code_usage",
            pinned_count=0,
            columns=(
                col("company"),
                col("brand"),
                col("drum_count"),
                col("drum_qty", default_visible=False),
                col("unit", default_visible=False),
                col("total_qty"),
                col(
                    "adhesive_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                col(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                col("sheet"),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.solvents",
            columns=(
                col("company"),
                col("brand"),
                col("name"),
                col("drum_count"),
                col("drum_qty", default_visible=False),
                col("unit", default_visible=False),
                col("total_qty"),
                col(
                    "solvent_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                col(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                col("created_at", default_visible=False),
                col("updated_at", default_visible=False),
            ),
        ),
        _entry(
            "inventory.solvent_names",
            ("name", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        _entry(
            "inventory.solvent_brands",
            ("name", "active"),
            *_hidden("created_at", "updated_at"),
        ),
        TableCatalogEntry(
            table_key="inventory.solvents_report",
            pinned_count=0,
            columns=(
                col("company"),
                col("brand"),
                col("name"),
                col("in_drums"),
                col("in_qty"),
                col("out_drums"),
                col("out_qty"),
                col("closing_drums"),
                col("closing_qty"),
                col(
                    "solvent_rate",
                    required_permission="inventory.solvent.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.solvent_name_usage",
            pinned_count=0,
            columns=(
                col("company"),
                col("brand"),
                col("drum_count"),
                col("drum_qty", default_visible=False),
                col("unit", default_visible=False),
                col("total_qty"),
                col(
                    "solvent_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                col(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                col(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                col("sheet"),
            ),
        ),
    )
}


def get_table_catalog(table_key: str) -> TableCatalogEntry | None:
    return TABLE_CATALOG.get(table_key)
