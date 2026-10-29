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

JOB_CREATE = build_permission(INVENTORY_MODULE, "job", "create")
JOB_READ = build_permission(INVENTORY_MODULE, "job", "read")
JOB_UPDATE = build_permission(INVENTORY_MODULE, "job", "update")
JOB_DELETE = build_permission(INVENTORY_MODULE, "job", "delete")
JOB_VIEW_PRICE = build_permission(INVENTORY_MODULE, "job", "view_price")
JOB_HISTORY = build_permission(INVENTORY_MODULE, "job", "history")

JOB_IMAGE_CREATE = build_permission(INVENTORY_MODULE, "job_image", "create")
JOB_IMAGE_READ = build_permission(INVENTORY_MODULE, "job_image", "read")
JOB_IMAGE_UPDATE = build_permission(INVENTORY_MODULE, "job_image", "update")
JOB_IMAGE_DELETE = build_permission(INVENTORY_MODULE, "job_image", "delete")

JOB_CHALLAN_CREATE = build_permission(INVENTORY_MODULE, "job_challan", "create")
JOB_CHALLAN_READ = build_permission(INVENTORY_MODULE, "job_challan", "read")
JOB_CHALLAN_UPDATE = build_permission(INVENTORY_MODULE, "job_challan", "update")
JOB_CHALLAN_DELETE = build_permission(INVENTORY_MODULE, "job_challan", "delete")

CYLINDER_RETURN_CREATE = build_permission(INVENTORY_MODULE, "cylinder_return", "create")
CYLINDER_RETURN_READ = build_permission(INVENTORY_MODULE, "cylinder_return", "read")
CYLINDER_RETURN_UPDATE = build_permission(INVENTORY_MODULE, "cylinder_return", "update")
CYLINDER_RETURN_DELETE = build_permission(INVENTORY_MODULE, "cylinder_return", "delete")

_CATALOG: dict[str, tuple[str, ...]] = {
    "unit": ("create", "read", "update", "delete"),
    "material": ("create", "read", "update", "delete", "view_price"),
    "materials_report": ("read",),
    "job": ("create", "read", "update", "delete", "view_price", "history"),
    "job_image": ("create", "read", "update", "delete"),
    "job_challan": ("create", "read", "update", "delete"),
    "cylinder_return": ("create", "read", "update", "delete"),
}


def inventory_catalog_permission_strings() -> list[str]:
    return [
        build_permission(INVENTORY_MODULE, resource, action)
        for resource, actions in _CATALOG.items()
        for action in actions
    ]
