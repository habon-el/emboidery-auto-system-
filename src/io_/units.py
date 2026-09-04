"""Unit conversion between design-space millimetres and pyembroidery's
native 1/10 mm stitch coordinate unit."""

UNITS_PER_MM = 10.0


def mm_to_units(value_mm: float) -> float:
    return value_mm * UNITS_PER_MM


def point_mm_to_units(point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    return (mm_to_units(x), mm_to_units(y))


def quantize_mm(value_mm: float) -> float:
    """Snap a millimetre value to the 1/10 mm grid every stitch file
    format stores coordinates on.

    This is not a rounding nicety -- it changes stitch lengths. A
    0.30mm stitch running at 45 degrees has components of 0.212mm,
    each of which snaps to 0.2mm, leaving a 0.283mm stitch in the
    written file: under the machine minimum, even though the stitch
    the pipeline generated was exactly at it. Anything that checks a
    stitch length has to check it on these coordinates, not on the
    floats upstream.
    """
    return round(value_mm * UNITS_PER_MM) / UNITS_PER_MM


def quantize_point_mm(point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    return (quantize_mm(x), quantize_mm(y))
