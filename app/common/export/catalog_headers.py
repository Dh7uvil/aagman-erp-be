"""Human-readable export headers for catalog column keys."""

from __future__ import annotations

_EXPORT_HEADERS: dict[str, str] = {
    "log_id": "Log ID",
    "resource_id": "Resource ID",
    "ip_address": "IP Address",
    "last_login_at": "Last login",
    "users_count": "Users",
    "total_kg": "Total kg",
    "price_per_unit": "Price per unit",
    "avg_price_per_unit": "Avg price",
    "cylinder_number": "Cylinder #",
    "cylinder_count": "Cylinder count",
    "pet_size": "PET size",
    "cylinder_location": "Location",
    "cylinder_cost": "Cylinder cost",
    "total_cylinder_cost": "Total cylinder cost",
    "return_number": "Return #",
    "drum_count": "Drum count",
    "drum_qty": "Drum qty",
    "total_qty": "Total qty",
    "ink_rate": "Ink rate",
    "total_rate": "Total rate",
    "adhesive_rate": "Adhesive rate",
    "solvent_rate": "Solvent rate",
    "in_rolls": "In rolls",
    "in_kg": "In kg",
    "out_rolls": "Out rolls",
    "out_kg": "Out kg",
    "closing_rolls": "Closing rolls",
    "closing_kg": "Closing kg",
    "in_drums": "In drums",
    "in_qty": "In qty",
    "out_drums": "Out drums",
    "out_qty": "Out qty",
    "closing_drums": "Closing drums",
    "closing_qty": "Closing qty",
    "bill_to_address": "Bill-to address",
    "ship_to_address": "Ship-to address",
}


def export_header_for_key(key: str) -> str:
    if key in _EXPORT_HEADERS:
        return _EXPORT_HEADERS[key]
    return key.replace("_", " ").strip().title()
