"""Canonical permission catalog registry for seeding and export."""

from __future__ import annotations


def permission_catalog() -> dict[str, dict[str, tuple[str, ...]]]:
    from app.core.enums import IDENTITY_MODULE, INVENTORY_MODULE
    from app.identity.catalog import _CATALOG as IDENTITY_CATALOG
    from app.inventory.catalog import _CATALOG as INVENTORY_CATALOG

    return {
        IDENTITY_MODULE: IDENTITY_CATALOG,
        INVENTORY_MODULE: INVENTORY_CATALOG,
    }


def catalog_permission_strings() -> list[str]:
    from app.core.permissions import build_permission

    return sorted(
        build_permission(module, resource, action)
        for module, resources in permission_catalog().items()
        for resource, actions in resources.items()
        for action in actions
    )
