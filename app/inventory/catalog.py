"""Inventory permission catalog."""

from app.core.enums import INVENTORY_MODULE
from app.core.permissions import build_permission

UNIT_CREATE = build_permission(INVENTORY_MODULE, "unit", "create")
UNIT_READ = build_permission(INVENTORY_MODULE, "unit", "read")
UNIT_UPDATE = build_permission(INVENTORY_MODULE, "unit", "update")
UNIT_DELETE = build_permission(INVENTORY_MODULE, "unit", "delete")

MATERIAL_CREATE = build_permission(INVENTORY_MODULE, "material", "create")
MATERIAL_READ = build_permission(INVENTORY_MODULE, "material", "read")
MATERIAL_UPDATE = build_permission(INVENTORY_MODULE, "material", "update")
MATERIAL_DELETE = build_permission(INVENTORY_MODULE, "material", "delete")
MATERIAL_VIEW_PRICE = build_permission(INVENTORY_MODULE, "material", "view_price")

MATERIALS_REPORT_READ = build_permission(INVENTORY_MODULE, "materials_report", "read")

_CATALOG: dict[str, tuple[str, ...]] = {
    "unit": ("create", "read", "update", "delete"),
    "material": ("create", "read", "update", "delete", "view_price"),
    "materials_report": ("read",),
}


def inventory_catalog_permission_strings() -> list[str]:
    return [
        build_permission(INVENTORY_MODULE, resource, action)
        for resource, actions in _CATALOG.items()
        for action in actions
    ]
