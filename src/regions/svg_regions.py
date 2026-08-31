"""SVG -> closed shapely regions per color.

svgelements resolves each shape's geometry into a single "user unit"
space that already accounts for viewBox scaling and any width/height
unit (mm, in, pt, ...) declared on the <svg> root. A user unit equals
1/96 inch by the CSS/SVG spec, so converting to mm is a constant factor
regardless of viewBox -- this holds for correctly unit-labeled SVGs, and
is the standard assumption for unitless ones too (documented here per
Section 10 rather than silently guessing per-file).
"""
import svgelements as se
from shapely.geometry import Polygon

from src.regions.model import Region
from src.stitches.model import ThreadColor

PX_TO_MM = 25.4 / 96.0
MAX_COLORS = 4
MIN_STEP_UNITS = 2.0  # sample curves roughly every 2 user units (~0.5mm)
BACKGROUND_COVERAGE_RATIO = 0.9  # a shape covering this much of the canvas
                                   # is treated as a background fill, not art


def _shape_to_polygon(shape: se.Shape) -> Polygon | None:
    path = se.Path(shape)
    length = path.length()
    if not length:
        return None
    n = max(16, int(length / MIN_STEP_UNITS))
    points = []
    for i in range(n + 1):
        t = i / n
        pt = path.point(t)
        points.append((pt[0] * PX_TO_MM, pt[1] * PX_TO_MM))
    if len(points) < 3:
        return None
    try:
        poly = Polygon(points).buffer(0)
    except Exception:
        return None
    return None if poly.is_empty else poly


def extract_svg_regions(svg_path: str
                         ) -> tuple[list[Region], list[ThreadColor], float, float, list[str]]:
    warnings: list[str] = []
    svg = se.SVG.parse(svg_path)
    width_mm = svg.width * PX_TO_MM
    height_mm = svg.height * PX_TO_MM
    canvas_area = svg.width * svg.height

    color_to_index: dict[str, int] = {}
    colors: list[ThreadColor] = []
    regions: list[Region] = []
    dropped_colors = 0

    for i, element in enumerate(svg.elements()):
        if not isinstance(element, se.Shape):
            continue
        fill = element.fill
        if fill is None or fill.value is None:
            continue  # unfilled / fill:none

        poly = _shape_to_polygon(element)
        if poly is None:
            continue

        bbox = element.bbox()
        if bbox:
            x0, y0, x1, y1 = bbox
            if (x1 - x0) * (y1 - y0) >= BACKGROUND_COVERAGE_RATIO * canvas_area:
                continue  # near-full-canvas shape: treat as background

        hexcolor = fill.hexrgb
        if hexcolor not in color_to_index:
            if len(colors) >= MAX_COLORS:
                dropped_colors += 1
                continue
            color_to_index[hexcolor] = len(colors)
            colors.append(ThreadColor(
                name=f"color {len(colors) + 1}",
                rgb=(fill.red, fill.green, fill.blue)))
        color_index = color_to_index[hexcolor]

        geoms = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            regions.append(Region(polygon=g, color_index=color_index,
                                   source="svg", region_id=f"svg-{i}"))

    if dropped_colors:
        warnings.append(
            f"SVG has more than {MAX_COLORS} fill colors; {dropped_colors} "
            f"shape(s) beyond the first {MAX_COLORS} colors were dropped "
            f"(Section 2: 2-4 solid colors in scope).")

    return regions, colors, width_mm, height_mm, warnings
