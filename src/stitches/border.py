"""Optional dense border ring: a denser band of fill stitched along a
region's own edge, on top of its interior fill.

This is a normal, well-established embroidery technique -- not literal
3D/puff foam (which stays out of scope, see Section 2/9 and the fixed
compensation-only stance on fabric physics). It reads as a bolder,
more raised-looking edge purely from stitch density and stacking order:
the interior fills first at normal density, then this ring re-stitches
a thin band along the boundary at roughly double density, sewn last so
it sits on top.
"""
from shapely.geometry import Polygon

from .fill import generate_fill
from .model import BORDER, StitchBlock


def border_annulus_polygons(polygon: Polygon, width_mm: float) -> list[Polygon]:
    """The ring-shaped region within width_mm of the polygon's own edge."""
    if width_mm <= 0:
        return []
    inner = polygon.buffer(-width_mm, join_style=2)
    if inner.is_empty:
        # Region narrower than the requested border -- the whole shape
        # is "border", so re-stitch it all at the denser pass instead of
        # producing an empty ring.
        annulus = polygon
    else:
        annulus = polygon.difference(inner)
    if annulus.is_empty:
        return []
    return list(annulus.geoms) if annulus.geom_type == "MultiPolygon" else [annulus]


def build_border_blocks(polygon: Polygon, angle_deg: float, width_mm: float,
                         fill_row_spacing_mm: float, fill_stitch_length_mm: float,
                         color_index: int, element_id: str) -> list[StitchBlock]:
    """Denser fill (half the normal row spacing) restricted to the ring
    within width_mm of the polygon's edge."""
    border_spacing_mm = max(fill_row_spacing_mm / 2, 0.2)
    blocks: list[StitchBlock] = []
    for ring_polygon in border_annulus_polygons(polygon, width_mm):
        runs = generate_fill(ring_polygon, angle_deg, border_spacing_mm, fill_stitch_length_mm)
        blocks.extend(StitchBlock(BORDER, run, color_index, element_id) for run in runs)
    return blocks
