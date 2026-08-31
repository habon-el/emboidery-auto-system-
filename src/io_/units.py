"""Unit conversion between design-space millimetres and pyembroidery's
native 1/10 mm stitch coordinate unit."""

UNITS_PER_MM = 10.0


def mm_to_units(value_mm: float) -> float:
    return value_mm * UNITS_PER_MM


def point_mm_to_units(point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    return (mm_to_units(x), mm_to_units(y))
