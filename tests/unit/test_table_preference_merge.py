"""Table preference merge when catalog gains columns."""

from app.common.table_preferences.catalog import TABLE_CATALOG
from app.common.table_preferences.normalize import merge_stored


def test_materials_report_merge_appends_new_default_visible_column() -> None:
    entry = TABLE_CATALOG["inventory.materials_report"]
    perms = frozenset({"inventory.materials_report.read", "inventory.material.view_price"})
    merged = merge_stored(
        entry,
        visible_columns=[
            "product",
            "micron",
            "size",
            "in_rolls",
            "in_kg",
            "out_rolls",
            "out_kg",
            "closing_rolls",
            "closing_kg",
            "price_per_unit",
        ],
        column_order=[
            "product",
            "micron",
            "size",
            "in_rolls",
            "in_kg",
            "out_rolls",
            "out_kg",
            "closing_rolls",
            "closing_kg",
            "price_per_unit",
        ],
        permissions=perms,
    )
    assert merged.column_order[-1] == "avg_price_per_unit"
    assert "avg_price_per_unit" not in merged.visible_columns


def test_materials_report_merge_keeps_user_hidden_column() -> None:
    entry = TABLE_CATALOG["inventory.materials_report"]
    perms = frozenset({"inventory.materials_report.read", "inventory.material.view_price"})
    merged = merge_stored(
        entry,
        visible_columns=[
            "product",
            "micron",
            "size",
            "in_rolls",
            "in_kg",
            "out_rolls",
            "out_kg",
            "closing_rolls",
            "closing_kg",
        ],
        column_order=[
            "product",
            "micron",
            "size",
            "in_rolls",
            "in_kg",
            "out_rolls",
            "out_kg",
            "closing_rolls",
            "closing_kg",
            "price_per_unit",
            "avg_price_per_unit",
        ],
        permissions=perms,
    )
    assert "price_per_unit" not in merged.visible_columns
    assert "avg_price_per_unit" not in merged.visible_columns
