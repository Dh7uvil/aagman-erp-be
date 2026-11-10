"""Per-table export value extractors keyed by catalog column id."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.common.export.nested import attr_getter, path_getter, role_labels
from app.inventory.cylinders.export_fields import total_cylinder_cost as compute_total_cylinder_cost
from app.inventory.material_export import _MATERIAL_EXTRACTORS

ExtractorMap = dict[str, Callable[[Any], object]]

_TABLE_EXTRACTORS: dict[str, ExtractorMap] = {}


def _register(table_key: str, mapping: ExtractorMap) -> None:
    _TABLE_EXTRACTORS[table_key] = mapping


def get_table_extractors(table_key: str) -> ExtractorMap | None:
    return _TABLE_EXTRACTORS.get(table_key)


def _m(mapping: dict[str, str]) -> ExtractorMap:
    return {key: path_getter(path) for key, path in mapping.items()}


_register(
    "identity.users",
    {
        **_m(
            {
                "email": "email",
                "user": "name",
                "designation": "designation",
                "status": "status",
                "phone": "phone",
            }
        ),
        "department": path_getter("department.name"),
        "branch": path_getter("branch.name"),
        "role": role_labels,
        "last_login_at": attr_getter("last_login_at"),
        "created_at": attr_getter("created_at"),
        "updated_at": attr_getter("updated_at"),
    },
)

_register(
    "identity.roles",
    _m(
        {
            "name": "name",
            "description": "description",
            "type": "role_type",
            "users_count": "users_count",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "identity.branches",
    _m(
        {
            "code": "code",
            "name": "name",
            "phone": "phone",
            "timezone": "timezone",
            "status": "status",
            "address": "address",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "identity.departments",
    {
        **_m(
            {
                "code": "code",
                "name": "name",
                "created_at": "created_at",
                "updated_at": "updated_at",
            }
        ),
        "branch": path_getter("branch.name"),
        "manager": path_getter("manager.name"),
    },
)

_register(
    "identity.warehouses",
    _m(
        {
            "code": "code",
            "name": "name",
            "phone": "phone",
            "default": "is_default",
            "active": "is_active",
            "address": "address",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "identity.companies",
    _m(
        {
            "name": "name",
            "email": "email",
            "phone": "phone",
            "address": "address",
            "bill_to_address": "bill_to_address",
            "ship_to_address": "ship_to_address",
            "id": "id",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "identity.audit_logs",
    {
        "log_id": path_getter("id"),
        "timestamp": attr_getter("timestamp"),
        "user": path_getter("user.name"),
        "action": attr_getter("action"),
        "resource": attr_getter("entity_label"),
        "resource_id": attr_getter("entity_id"),
        "module": attr_getter("module"),
        "ip_address": attr_getter("ip_address"),
        "status": attr_getter("status"),
    },
)

_register(
    "inventory.units",
    _m(
        {
            "code": "code",
            "name": "name",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register("inventory.materials", _MATERIAL_EXTRACTORS)

_register(
    "inventory.inks",
    _m(
        {
            "company": "company_name",
            "brand": "brand_name",
            "color": "color_name",
            "hex": "hex",
            "drum_count": "drum_count",
            "drum_qty": "drum_qty",
            "unit": "unit_code",
            "total_qty": "total_qty",
            "ink_rate": "ink_rate",
            "avg_price_per_unit": "avg_price_per_unit",
            "total_rate": "total_rate",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "inventory.adhesives",
    _m(
        {
            "company": "company_name",
            "brand": "brand_name",
            "code": "code",
            "drum_count": "drum_count",
            "drum_qty": "drum_qty",
            "unit": "unit_code",
            "total_qty": "total_qty",
            "adhesive_rate": "adhesive_rate",
            "avg_price_per_unit": "avg_price_per_unit",
            "total_rate": "total_rate",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "inventory.solvents",
    _m(
        {
            "company": "company_name",
            "brand": "brand_name",
            "name": "name",
            "drum_count": "drum_count",
            "drum_qty": "drum_qty",
            "unit": "unit_code",
            "total_qty": "total_qty",
            "solvent_rate": "solvent_rate",
            "avg_price_per_unit": "avg_price_per_unit",
            "total_rate": "total_rate",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_register(
    "inventory.ink_colors",
    _m(
        {
            "name": "name",
            "hex": "hex_code",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)
_register(
    "inventory.ink_brands",
    _m(
        {
            "name": "name",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)
_register(
    "inventory.adhesive_codes",
    _m(
        {
            "code": "code",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)
_register(
    "inventory.adhesive_brands",
    _m(
        {
            "name": "name",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)
_register(
    "inventory.solvent_names",
    _m(
        {
            "name": "name",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)
_register(
    "inventory.solvent_brands",
    _m(
        {
            "name": "name",
            "active": "is_active",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

def _total_cylinder_cost_cell(row: Any) -> object:
    existing = getattr(row, "total_cylinder_cost", None)
    if existing is not None:
        return existing
    return compute_total_cylinder_cost(
        getattr(row, "cylinder_cost", None),
        getattr(row, "cylinder_count", None),
    )


_register(
    "inventory.cylinders",
    {
        **_m(
            {
                "cylinder_number": "cylinder_number",
                "company": "company_name",
                "product": "product_name",
                "status": "status",
                "cylinder_count": "cylinder_count",
                "pet_size": "pet_size",
                "cylinder_location": "cylinder_location",
                "cylinder_cost": "cylinder_cost",
                "created_at": "created_at",
                "updated_at": "updated_at",
            }
        ),
        "total_cylinder_cost": _total_cylinder_cost_cell,
    },
)

_register(
    "inventory.cylinder_returns",
    _m(
        {
            "return_number": "return_number",
            "customer": "customer_name",
            "return_date": "return_date",
            "cylinder": "cylinder_number",
            "remarks": "remarks",
            "created_at": "created_at",
            "updated_at": "updated_at",
        }
    ),
)

_report_fields = {
    "company": "company_name",
    "brand": "brand_name",
    "color": "color_name",
    "code": "code",
    "name": "name",
    "product": "product_name",
    "micron": "micron_name",
    "size": "size_label",
    "in_rolls": "in_rolls",
    "in_kg": "in_kg",
    "out_rolls": "out_rolls",
    "out_kg": "out_kg",
    "closing_rolls": "closing_rolls",
    "closing_kg": "closing_kg",
    "in_drums": "in_drums",
    "in_qty": "in_qty",
    "out_drums": "out_drums",
    "out_qty": "out_qty",
    "closing_drums": "closing_drums",
    "closing_qty": "closing_qty",
    "price_per_unit": "price_per_unit",
    "avg_price_per_unit": "avg_price_per_unit",
    "ink_rate": "ink_rate",
    "adhesive_rate": "adhesive_rate",
    "solvent_rate": "solvent_rate",
}

_register("inventory.materials_report", _m(_report_fields))
_register("inventory.inks_report", _m(_report_fields))
_register("inventory.adhesives_report", _m(_report_fields))
_register("inventory.solvents_report", _m(_report_fields))

_usage_fields = {
    "company": "company_name",
    "brand": "brand_name",
    "drum_count": "drum_count",
    "drum_qty": "drum_qty",
    "unit": "drum_unit_code",
    "total_qty": "total_qty",
    "ink_rate": "ink_rate",
    "adhesive_rate": "adhesive_rate",
    "solvent_rate": "solvent_rate",
    "avg_price_per_unit": "avg_price_per_unit",
    "total_rate": "total_rate",
}

_register(
    "inventory.ink_color_usage",
    {**_m(_usage_fields), "sheet": path_getter("ink_sheet_id")},
)
_register(
    "inventory.adhesive_code_usage",
    {**_m(_usage_fields), "sheet": path_getter("adhesive_sheet_id")},
)
_register(
    "inventory.solvent_name_usage",
    {**_m(_usage_fields), "sheet": path_getter("solvent_sheet_id")},
)
