"""Resize a RegionSet to a target finished size before stitch generation
-- mirrors the "resize artwork to finished dimensions" step real
digitizing workflows do first (pre-scaling so density/stitch-length
calculations are based on the actual output size, not incidental input
resolution).
"""
from shapely import affinity

from src.regions.model import Region, RegionSet


def _content_bounds(regions: list[Region]) -> tuple[float, float, float, float]:
    """Bounding box of the actual stitchable artwork -- NOT the source
    canvas/viewBox size (region_set.width_mm/height_mm), which usually
    includes background margin the design doesn't fill. "Resize to
    80mm wide" should mean the artwork ends up 80mm wide, not the
    canvas it was sitting in.
    """
    xs0 = min(r.polygon.bounds[0] for r in regions)
    ys0 = min(r.polygon.bounds[1] for r in regions)
    xs1 = max(r.polygon.bounds[2] for r in regions)
    ys1 = max(r.polygon.bounds[3] for r in regions)
    return xs0, ys0, xs1, ys1


def scale_region_set(region_set: RegionSet, target_width_mm: float | None = None,
                      target_height_mm: float | None = None) -> tuple[RegionSet, list[str]]:
    """Uniformly scales to target_width_mm (height follows the aspect
    ratio) or target_height_mm (width follows) if only one is given.
    Giving both scales each axis independently -- which distorts the
    design if the aspect ratio doesn't match, so that case returns a
    warning rather than silently stretching it. Sizes are measured
    against the actual artwork bounding box, not the source canvas.
    """
    if not target_width_mm and not target_height_mm:
        return region_set, []
    if not region_set.regions:
        return region_set, []

    minx, miny, maxx, maxy = _content_bounds(region_set.regions)
    content_width, content_height = maxx - minx, maxy - miny

    warnings: list[str] = []
    if target_width_mm and target_height_mm:
        sx = target_width_mm / content_width
        sy = target_height_mm / content_height
        if abs(sx - sy) / max(sx, sy) > 0.02:
            warnings.append(
                f"Target size {target_width_mm}x{target_height_mm}mm doesn't "
                f"match the source aspect ratio -- the design will be "
                f"stretched non-uniformly.")
    elif target_width_mm:
        sx = sy = target_width_mm / content_width
    else:
        sx = sy = target_height_mm / content_height

    scaled_regions = [
        Region(polygon=affinity.scale(r.polygon, xfact=sx, yfact=sy, origin=(0, 0)),
               color_index=r.color_index, source=r.source, region_id=r.region_id)
        for r in region_set.regions
    ]
    scaled = RegionSet(
        regions=scaled_regions, colors=region_set.colors,
        width_mm=content_width * sx, height_mm=content_height * sy,
        warnings=region_set.warnings)
    return scaled, warnings
