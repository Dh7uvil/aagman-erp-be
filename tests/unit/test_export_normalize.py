"""Export preference merge (list → export fallback)."""

from app.common.table_preferences.catalog import get_table_catalog
from app.common.table_preferences.export_normalize import merge_export_stored


def test_custom_export_columns_override_list_fallback() -> None:
    entry = get_table_catalog("inventory.cylinders")
    assert entry is not None
    perms = frozenset({"inventory.cylinder.view_price", "inventory.cylinder.read"})

    merged = merge_export_stored(
        entry,
        export_visible_columns=["cylinder_number", "product"],
        export_column_order=["cylinder_number", "product", "company"],
        permissions=perms,
        fallback_visible_columns=["cylinder_number", "cylinder_cost"],
        fallback_column_order=["cylinder_number", "cylinder_cost"],
    )
    assert merged.export_visible_columns == ["cylinder_number", "product"]
    assert "cylinder_cost" not in merged.export_visible_columns


def test_list_visible_used_when_export_not_saved() -> None:
    entry = get_table_catalog("inventory.cylinders")
    assert entry is not None
    perms = frozenset({"inventory.cylinder.view_price", "inventory.cylinder.read"})

    merged = merge_export_stored(
        entry,
        export_visible_columns=None,
        export_column_order=None,
        permissions=perms,
        fallback_visible_columns=["cylinder_number", "cylinder_cost", "total_cylinder_cost"],
        fallback_column_order=["cylinder_number", "cylinder_cost", "total_cylinder_cost"],
    )
    assert merged.export_visible_columns == [
        "cylinder_number",
        "cylinder_cost",
        "total_cylinder_cost",
    ]


def test_catalog_defaults_when_no_export_or_list_fallback() -> None:
    entry = get_table_catalog("inventory.materials")
    assert entry is not None
    perms = frozenset({"inventory.material.read", "inventory.material.view_price"})

    merged = merge_export_stored(
        entry,
        export_visible_columns=None,
        export_column_order=None,
        permissions=perms,
        fallback_visible_columns=None,
        fallback_column_order=None,
    )
    assert merged.export_visible_columns == entry.default_export_visible(perms)
