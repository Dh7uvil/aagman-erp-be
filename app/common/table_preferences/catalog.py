"""Allowlists and defaults for list-table columns."""

from __future__ import annotations

from dataclasses import dataclass

PINNED_COLUMN_COUNT = 2
LOCKED_COLUMN_ID = "actions"


@dataclass(frozen=True, slots=True)
class TableColumnSpec:
    key: str
    default_visible: bool = True
    required_permission: str | None = None


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


def _cols(*keys: str) -> tuple[TableColumnSpec, ...]:
    return tuple(TableColumnSpec(key) for key in keys)


def _hidden(*keys: str) -> tuple[TableColumnSpec, ...]:
    return tuple(TableColumnSpec(key, default_visible=False) for key in keys)


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
                TableColumnSpec("company"),
                TableColumnSpec("product"),
                TableColumnSpec("micron"),
                TableColumnSpec("size"),
                TableColumnSpec("rolls"),
                TableColumnSpec("total_kg"),
                TableColumnSpec(
                    "price_per_unit",
                    default_visible=False,
                    required_permission="inventory.material.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.material.view_price",
                ),
                TableColumnSpec("active", default_visible=False),
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
                TableColumnSpec("product"),
                TableColumnSpec("micron"),
                TableColumnSpec("size"),
                TableColumnSpec("in_rolls"),
                TableColumnSpec("in_kg"),
                TableColumnSpec("out_rolls"),
                TableColumnSpec("out_kg"),
                TableColumnSpec("closing_rolls"),
                TableColumnSpec("closing_kg"),
                TableColumnSpec(
                    "price_per_unit",
                    default_visible=True,
                    required_permission="inventory.material.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.material.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.cylinders",
            columns=(
                TableColumnSpec("cylinder_number"),
                TableColumnSpec("company"),
                TableColumnSpec("product"),
                TableColumnSpec("status"),
                TableColumnSpec("cylinder_count"),
                TableColumnSpec("pet_size", default_visible=False),
                TableColumnSpec("cylinder_location", default_visible=False),
                TableColumnSpec(
                    "cylinder_cost",
                    default_visible=False,
                    required_permission="inventory.cylinder.view_price",
                ),
                TableColumnSpec(
                    "total_cylinder_cost",
                    default_visible=False,
                    required_permission="inventory.cylinder.view_price",
                ),
                TableColumnSpec("created_at", default_visible=False),
                TableColumnSpec("updated_at", default_visible=False),
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
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("color"),
                TableColumnSpec("hex", default_visible=False),
                TableColumnSpec("drum_count"),
                TableColumnSpec("drum_qty", default_visible=False),
                TableColumnSpec("unit", default_visible=False),
                TableColumnSpec("total_qty"),
                TableColumnSpec(
                    "ink_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                TableColumnSpec(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                TableColumnSpec("created_at", default_visible=False),
                TableColumnSpec("updated_at", default_visible=False),
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
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("color"),
                TableColumnSpec("in_drums"),
                TableColumnSpec("in_qty"),
                TableColumnSpec("out_drums"),
                TableColumnSpec("out_qty"),
                TableColumnSpec("closing_drums"),
                TableColumnSpec("closing_qty"),
                TableColumnSpec(
                    "ink_rate",
                    required_permission="inventory.ink.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.ink_color_usage",
            pinned_count=0,
            columns=(
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("drum_count"),
                TableColumnSpec("drum_qty", default_visible=False),
                TableColumnSpec("unit", default_visible=False),
                TableColumnSpec("total_qty"),
                TableColumnSpec(
                    "ink_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                TableColumnSpec(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.ink.view_price",
                ),
                TableColumnSpec("sheet"),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.adhesives",
            columns=(
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("code"),
                TableColumnSpec("drum_count"),
                TableColumnSpec("drum_qty", default_visible=False),
                TableColumnSpec("unit", default_visible=False),
                TableColumnSpec("total_qty"),
                TableColumnSpec(
                    "adhesive_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                TableColumnSpec(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                TableColumnSpec("created_at", default_visible=False),
                TableColumnSpec("updated_at", default_visible=False),
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
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("code"),
                TableColumnSpec("in_drums"),
                TableColumnSpec("in_qty"),
                TableColumnSpec("out_drums"),
                TableColumnSpec("out_qty"),
                TableColumnSpec("closing_drums"),
                TableColumnSpec("closing_qty"),
                TableColumnSpec(
                    "adhesive_rate",
                    required_permission="inventory.adhesive.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.adhesive_code_usage",
            pinned_count=0,
            columns=(
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("drum_count"),
                TableColumnSpec("drum_qty", default_visible=False),
                TableColumnSpec("unit", default_visible=False),
                TableColumnSpec("total_qty"),
                TableColumnSpec(
                    "adhesive_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                TableColumnSpec(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.adhesive.view_price",
                ),
                TableColumnSpec("sheet"),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.solvents",
            columns=(
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("name"),
                TableColumnSpec("drum_count"),
                TableColumnSpec("drum_qty", default_visible=False),
                TableColumnSpec("unit", default_visible=False),
                TableColumnSpec("total_qty"),
                TableColumnSpec(
                    "solvent_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                TableColumnSpec(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                TableColumnSpec("created_at", default_visible=False),
                TableColumnSpec("updated_at", default_visible=False),
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
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("name"),
                TableColumnSpec("in_drums"),
                TableColumnSpec("in_qty"),
                TableColumnSpec("out_drums"),
                TableColumnSpec("out_qty"),
                TableColumnSpec("closing_drums"),
                TableColumnSpec("closing_qty"),
                TableColumnSpec(
                    "solvent_rate",
                    required_permission="inventory.solvent.view_price",
                ),
            ),
        ),
        TableCatalogEntry(
            table_key="inventory.solvent_name_usage",
            pinned_count=0,
            columns=(
                TableColumnSpec("company"),
                TableColumnSpec("brand"),
                TableColumnSpec("drum_count"),
                TableColumnSpec("drum_qty", default_visible=False),
                TableColumnSpec("unit", default_visible=False),
                TableColumnSpec("total_qty"),
                TableColumnSpec(
                    "solvent_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                TableColumnSpec(
                    "avg_price_per_unit",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                TableColumnSpec(
                    "total_rate",
                    default_visible=False,
                    required_permission="inventory.solvent.view_price",
                ),
                TableColumnSpec("sheet"),
            ),
        ),
    )
}


def get_table_catalog(table_key: str) -> TableCatalogEntry | None:
    return TABLE_CATALOG.get(table_key)
