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
            ),
        ),
    )
}


def get_table_catalog(table_key: str) -> TableCatalogEntry | None:
    return TABLE_CATALOG.get(table_key)
