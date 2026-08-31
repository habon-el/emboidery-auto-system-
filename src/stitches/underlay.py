"""Underlay generation.

Underlay is the foundation layer sewn before the visible top stitching:
it anchors the fabric, compresses the nap, and gives the top stitches
something to grab. Auto-selected by stitch type, not user-tunable in the
MVP (see Section 2 / Section 9 -- no per-design manual tuning yet).
"""
from shapely.geometry import Polygon

from .model import Point
from .running import resample_path


def fill_underlay(polygon: Polygon, inset_mm: float,
                   stitch_length_mm: float) -> list[Point]:
    """Perimeter running-stitch underlay, inset inward from the fill edge.

    A simple edge-walk underlay is a conservative, safe default for the
    MVP; it anchors the outline before the fill rows lay down on top of it.
    """
    inner = polygon.buffer(-inset_mm, join_style=2)
    if inner.is_empty:
        # Region too small for an inset underlay -- fall back to the
        # original boundary rather than skipping underlay entirely.
        inner = polygon
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    coords = list(inner.exterior.coords)
    return resample_path(coords, stitch_length_mm, closed=True)


def satin_centerline_underlay(rail_a: list[Point], rail_b: list[Point],
                               stitch_length_mm: float) -> list[Point]:
    """A running-stitch underlay down the middle of a satin column."""
    n = min(len(rail_a), len(rail_b))
    centerline = [
        ((rail_a[i][0] + rail_b[i][0]) / 2, (rail_a[i][1] + rail_b[i][1]) / 2)
        for i in range(n)
    ]
    return resample_path(centerline, stitch_length_mm)
