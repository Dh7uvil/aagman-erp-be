"""Export writer totals row."""

from decimal import Decimal

from app.common.export.types import ExportColumn, format_export_cell
from app.common.export.writers import write_csv


def test_format_export_cell_preserves_integer_trailing_zeros() -> None:
    assert format_export_cell(Decimal("100")) == "100"
    assert format_export_cell(Decimal("200")) == "200"
    assert format_export_cell(Decimal("245.50")) == "245.5"
    assert format_export_cell(Decimal("10")) == "10"


def test_csv_includes_totals_row() -> None:
    rows = [{"rolls": Decimal("2")}, {"rolls": Decimal("3")}]

    def rolls(row: object) -> object:
        return row["rolls"]  # type: ignore[index]

    columns = [
        ExportColumn(key="name", header="Name", value_fn=lambda _row: "A"),
        ExportColumn(key="rolls", header="Rolls", value_fn=rolls, aggregate="sum"),
    ]
    csv_body = write_csv(rows, columns)
    lines = csv_body.strip().splitlines()
    assert lines[-1].startswith("Total,")
    assert lines[-1].endswith("5")
