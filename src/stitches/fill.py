"""Fill-stitch generation: several selectable *styles* for covering a
FILL-type region's interior, not just one fixed look.

generate_fill() is the classic tatami: parallel rows of stitches
following a chosen angle, spaced row_spacing_mm apart, with needle
points along each row every stitch_length_mm. Rows snake back and forth
(boustrophedon) so the whole region is covered with minimal travel and
consecutive rows connect directly into each other.

generate_contour_fill(), generate_crosshatch_fill(), and
generate_brick_fill() are the other real digitizing fill styles this
tool exposes (src/stitches/model.py's FILL_STYLES) -- a human (or a
customer, via the same web-UI dropdown) picks which one to use instead
of the system always defaulting to tatami; see src/stitches/build.py
for where that choice is applied.

A region can have holes or be crossed by a scan row in more than one
place (a ring/donut shape, a letter like "O", a fill region with a hole
cut out for another color on top of it). Where that happens, connecting
the segments with a plain stitch would sew straight across the gap --
so every generator here returns a *list of runs* instead of one flat
point list: each run is a real continuous stitch path, and a jump
belongs between runs, not a stitch across empty fabric (Section 9:
don't fake it -- src/pathing/route.py inserts the actual JUMP/TRIM at
export time).
"""
import math

from shapely import affinity
from shapely.geometry import LineString, Polygon

from .model import Point
from .running import resample_path


def _row_segments(polygon: Polygon, y: float, xmin: float, xmax: float
                   ) -> list[tuple[float, float]]:
    line = LineString([(xmin - 1, y), (xmax + 1, y)])
    inter = polygon.intersection(line)
    segs: list[tuple[float, float]] = []
    if inter.is_empty:
        return segs
    geoms = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
    for g in geoms:
        if g.geom_type != "LineString" or g.length == 0:
            continue
        xs = [c[0] for c in g.coords]
        segs.append((min(xs), max(xs)))
    segs.sort()
    return segs


def _runs_from_rotated_points(points_rot: list[Point], angle_deg: float, centroid,
                               stitch_length_mm: float, row_spacing_mm: float
                               ) -> list[list[Point]]:
    """Shared tail end of the row-scan generators: rotate the scanned
    points back into design space, then split into separate runs
    wherever consecutive points are farther apart than a normal
    within-row/between-row step -- that gap means the scan crossed a
    hole or a disjoint part of the shape."""
    if not points_rot:
        return []

    line = LineString(points_rot)
    line = affinity.rotate(line, angle_deg, origin=centroid)
    points = [(round(x, 4), round(y, 4)) for x, y in line.coords]

    break_threshold_mm = max(stitch_length_mm, row_spacing_mm) * 2.5
    runs: list[list[Point]] = [[points[0]]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if math.hypot(x1 - x0, y1 - y0) > break_threshold_mm:
            runs.append([])
        runs[-1].append((x1, y1))
    return [r for r in runs if len(r) >= 2]


def generate_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                   stitch_length_mm: float) -> list[list[Point]]:
    """Classic tatami fill: return a list of stitchable runs (each a
    list of needle points, mm) filling `polygon`. Almost always a
    single run; more than one when the polygon has holes or is
    otherwise crossed by a row in multiple places.
    """
    centroid = polygon.centroid
    rotated = affinity.rotate(polygon, -angle_deg, origin=centroid)
    xmin, ymin, xmax, ymax = rotated.bounds

    points_rot: list[Point] = []
    y = ymin + row_spacing_mm / 2
    row_idx = 0
    while y <= ymax:
        segs = _row_segments(rotated, y, xmin, xmax)
        if segs:
            ordered = segs if row_idx % 2 == 0 else list(reversed(segs))
            for (x0, x1) in ordered:
                lo, hi = (x0, x1) if row_idx % 2 == 0 else (x1, x0)
                n_steps = max(1, int(abs(hi - lo) / stitch_length_mm))
                for step in range(n_steps + 1):
                    x = lo + (hi - lo) * step / n_steps
                    points_rot.append((x, y))
        row_idx += 1
        y += row_spacing_mm

    return _runs_from_rotated_points(points_rot, angle_deg, centroid,
                                      stitch_length_mm, row_spacing_mm)


def generate_brick_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                         stitch_length_mm: float) -> list[list[Point]]:
    """Same rows as generate_fill, but every other row's needle points
    are phase-shifted half a stitch length from the row before it --
    like brick coursing, instead of tatami's needle holes lining up
    into a straight grid every row_spacing_mm. A real digitizer reaches
    for this for a softer, less visibly "laddered" look on a larger
    fill; the row/angle/hole handling is identical to generate_fill,
    only where each row's points fall differs.
    """
    centroid = polygon.centroid
    rotated = affinity.rotate(polygon, -angle_deg, origin=centroid)
    xmin, ymin, xmax, ymax = rotated.bounds

    points_rot: list[Point] = []
    y = ymin + row_spacing_mm / 2
    row_idx = 0
    while y <= ymax:
        segs = _row_segments(rotated, y, xmin, xmax)
        if segs:
            ordered = segs if row_idx % 2 == 0 else list(reversed(segs))
            row_phase = (row_idx % 2) * (stitch_length_mm / 2)
            for (x0, x1) in ordered:
                lo, hi = (x0, x1) if row_idx % 2 == 0 else (x1, x0)
                direction = 1.0 if hi >= lo else -1.0
                span = abs(hi - lo)
                points_rot.append((lo, y))
                pos = row_phase if row_phase > 0 else stitch_length_mm
                while pos < span:
                    points_rot.append((lo + direction * pos, y))
                    pos += stitch_length_mm
                points_rot.append((hi, y))
        row_idx += 1
        y += row_spacing_mm

    return _runs_from_rotated_points(points_rot, angle_deg, centroid,
                                      stitch_length_mm, row_spacing_mm)


def generate_crosshatch_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                              stitch_length_mm: float,
                              second_pass_spacing_scale: float = 1.6
                              ) -> list[list[Point]]:
    """Two tatami passes at 90 degrees to each other -- denser feel,
    more stable on stretchy fabric. The same technique
    src/stitches/build.py already auto-applies to texture-flagged
    regions, exposed here as its own selectable fill style
    (src/stitches/model.py's FILL_CROSSHATCH) so it's reachable
    directly, not only via texture detection. The second pass defaults
    to wider spacing so total density doesn't roughly double.
    """
    return (generate_fill(polygon, angle_deg, row_spacing_mm, stitch_length_mm)
            + generate_fill(polygon, angle_deg + 90,
                             row_spacing_mm * second_pass_spacing_scale, stitch_length_mm))


def generate_contour_fill(polygon: Polygon, row_spacing_mm: float,
                           stitch_length_mm: float) -> list[list[Point]]:
    """Concentric ("contour") fill: instead of one set of parallel rows
    at a single angle, each successive ring is the polygon's own
    boundary offset row_spacing_mm further inward -- every ring hugs
    the region's actual curves rather than a straight line picked once
    for the whole shape. This is what a real digitizer reaches for on
    rounded letters/logos specifically: a global straight-line angle
    (generate_fill) is picked per region from that region's own medial
    axis, so two differently-shaped neighboring letters can end up
    stitching in visibly unrelated directions -- contour fill sidesteps
    that by never picking a single direction at all.

    Returns a list of closed-loop runs, outermost ring first. Holes are
    handled for free: buffering a polygon with an interior shrinks its
    outer boundary inward *and* its hole boundary outward at the same
    time, and once they meet, shapely's buffer() naturally stops
    producing geometry there (it may split into a MultiPolygon of
    separate remaining pieces, which this just keeps ringing individually).
    """
    runs: list[list[Point]] = []
    inset = row_spacing_mm / 2
    # A generous cap on ring count rather than an exact geometric bound --
    # buffer() empties out long before this for any real shape, this just
    # guarantees termination if something degenerate slips through.
    max_iterations = 2000
    for _ in range(max_iterations):
        shrunk = polygon.buffer(-inset)
        if shrunk.is_empty:
            break
        pieces = list(shrunk.geoms) if hasattr(shrunk, "geoms") else [shrunk]
        produced_any = False
        for piece in pieces:
            if piece.is_empty or piece.area <= 0 or piece.geom_type != "Polygon":
                continue
            for ring in [piece.exterior, *piece.interiors]:
                pts = resample_path(list(ring.coords), stitch_length_mm, closed=True)
                if len(pts) >= 2:
                    runs.append([(round(x, 4), round(y, 4)) for x, y in pts])
                    produced_any = True
        if not produced_any:
            break
        inset += row_spacing_mm

    if not runs:
        # Region too small for even one inward ring -- stitch its own
        # boundary so it isn't left completely unstitched.
        pts = resample_path(list(polygon.exterior.coords), stitch_length_mm, closed=True)
        if len(pts) >= 2:
            runs.append([(round(x, 4), round(y, 4)) for x, y in pts])
    return runs
