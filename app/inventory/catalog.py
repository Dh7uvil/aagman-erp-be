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
MATERIAL_HISTORY = build_permission(INVENTORY_MODULE, "material", "history")

MATERIALS_REPORT_READ = build_permission(INVENTORY_MODULE, "materials_report", "read")

CYLINDER_CREATE = build_permission(INVENTORY_MODULE, "cylinder", "create")
CYLINDER_READ = build_permission(INVENTORY_MODULE, "cylinder", "read")
CYLINDER_UPDATE = build_permission(INVENTORY_MODULE, "cylinder", "update")
CYLINDER_DELETE = build_permission(INVENTORY_MODULE, "cylinder", "delete")
CYLINDER_VIEW_PRICE = build_permission(INVENTORY_MODULE, "cylinder", "view_price")
CYLINDER_HISTORY = build_permission(INVENTORY_MODULE, "cylinder", "history")

CYLINDER_IMAGE_CREATE = build_permission(INVENTORY_MODULE, "cylinder_image", "create")
CYLINDER_IMAGE_READ = build_permission(INVENTORY_MODULE, "cylinder_image", "read")
CYLINDER_IMAGE_UPDATE = build_permission(INVENTORY_MODULE, "cylinder_image", "update")
CYLINDER_IMAGE_DELETE = build_permission(INVENTORY_MODULE, "cylinder_image", "delete")

CYLINDER_CHALLAN_CREATE = build_permission(INVENTORY_MODULE, "cylinder_challan", "create")
CYLINDER_CHALLAN_READ = build_permission(INVENTORY_MODULE, "cylinder_challan", "read")
CYLINDER_CHALLAN_UPDATE = build_permission(INVENTORY_MODULE, "cylinder_challan", "update")
CYLINDER_CHALLAN_DELETE = build_permission(INVENTORY_MODULE, "cylinder_challan", "delete")

CYLINDER_RETURN_CREATE = build_permission(INVENTORY_MODULE, "cylinder_return", "create")
CYLINDER_RETURN_READ = build_permission(INVENTORY_MODULE, "cylinder_return", "read")
CYLINDER_RETURN_UPDATE = build_permission(INVENTORY_MODULE, "cylinder_return", "update")
CYLINDER_RETURN_DELETE = build_permission(INVENTORY_MODULE, "cylinder_return", "delete")

INK_COLOR_CREATE = build_permission(INVENTORY_MODULE, "ink_color", "create")
INK_COLOR_READ = build_permission(INVENTORY_MODULE, "ink_color", "read")
INK_COLOR_UPDATE = build_permission(INVENTORY_MODULE, "ink_color", "update")
INK_COLOR_DELETE = build_permission(INVENTORY_MODULE, "ink_color", "delete")
INK_COLOR_HISTORY = build_permission(INVENTORY_MODULE, "ink_color", "history")

INK_CREATE = build_permission(INVENTORY_MODULE, "ink", "create")
INK_READ = build_permission(INVENTORY_MODULE, "ink", "read")
INK_UPDATE = build_permission(INVENTORY_MODULE, "ink", "update")
INK_DELETE = build_permission(INVENTORY_MODULE, "ink", "delete")
INK_VIEW_PRICE = build_permission(INVENTORY_MODULE, "ink", "view_price")
INK_HISTORY = build_permission(INVENTORY_MODULE, "ink", "history")

INK_IMAGE_CREATE = build_permission(INVENTORY_MODULE, "ink_image", "create")
INK_IMAGE_READ = build_permission(INVENTORY_MODULE, "ink_image", "read")
INK_IMAGE_UPDATE = build_permission(INVENTORY_MODULE, "ink_image", "update")
INK_IMAGE_DELETE = build_permission(INVENTORY_MODULE, "ink_image", "delete")

INKS_REPORT_READ = build_permission(INVENTORY_MODULE, "inks_report", "read")

_CATALOG: dict[str, tuple[str, ...]] = {
    "unit": ("create", "read", "update", "delete"),
    "material": ("create", "read", "update", "delete", "view_price", "history"),
    "materials_report": ("read",),
    "cylinder": ("create", "read", "update", "delete", "view_price", "history"),
    "cylinder_image": ("create", "read", "update", "delete"),
    "cylinder_challan": ("create", "read", "update", "delete"),
    "cylinder_return": ("create", "read", "update", "delete"),
    "ink_color": ("create", "read", "update", "delete", "history"),
    "ink": ("create", "read", "update", "delete", "view_price", "history"),
    "ink_image": ("create", "read", "update", "delete"),
    "inks_report": ("read",),
}


def inventory_catalog_permission_strings() -> list[str]:
    return [
        build_permission(INVENTORY_MODULE, resource, action)
        for resource, actions in _CATALOG.items()
        for action in actions
    ]
