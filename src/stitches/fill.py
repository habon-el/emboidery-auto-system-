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
from shapely.ops import unary_union

from .model import MIN_STITCH_LENGTH_MM, Point
from .running import resample_path

# How far a segment-to-segment connector may stray outside the shape
# before it has to become a jump instead of a stitch. Small enough to
# catch a real crossing, large enough to tolerate the boundary noise a
# rasterized/simplified contour carries.
CONNECTOR_OUTSIDE_TOLERANCE_MM = 0.3

# The containment test runs against the shape grown by this much. A
# connector that runs *along* an edge is geometrically ambiguous --
# shapely's intersection flips between "fully inside" and "fully
# outside" on ~1e-5 of floating-point jitter there -- and without this
# nudge those edge-hugging connectors get split at random, each costing
# a needless jump/trim. It does not weaken the real test: an actual
# crossing (a star's notch, a ring's hole) is orders of magnitude
# wider than this.
CONTAINMENT_EPSILON_MM = 0.05


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


def _runs_from_segments(segments_rot: list[list[Point]], angle_deg: float, centroid,
                         rotated_polygon: Polygon) -> list[list[Point]]:
    """Shared tail end of the row-scan generators: join consecutive row
    segments into continuous runs, then rotate back into design space.

    Two consecutive segments are joined only when the stitch that would
    connect them actually stays *inside* the shape. This used to be a
    distance guess instead (join anything closer than 2.5x a stitch
    length), which is fine for a convex blob but wrong for any concave
    or multi-part shape: on a real badge illustration it sewed up to
    271mm of thread straight across open fabric per region -- through a
    star's notches, across a ring's hole, between a letter's arms --
    because those gaps happened to be under the threshold. A gap that
    leaves the shape needs a jump, not a stitch, no matter how short it
    is (Section 9: don't fake it -- src/pathing/route.py inserts the
    real JUMP/TRIM between runs at export time).
    """
    # A row segment shorter than one legal stitch (a scan row clipping
    # the very tip of a corner) can't be sewn as anything but a thread-
    # breaking sub-minimum stitch; dropping it leaves a sliver a
    # fraction of a mm wide unstitched at a boundary the next row
    # covers anyway.
    segments_rot = [seg for seg in segments_rot
                    if math.hypot(seg[-1][0] - seg[0][0], seg[-1][1] - seg[0][1])
                    >= MIN_STITCH_LENGTH_MM]
    if not segments_rot:
        return []

    test_shape = rotated_polygon.buffer(CONTAINMENT_EPSILON_MM)
    runs_rot: list[list[Point]] = [list(segments_rot[0])]
    for seg in segments_rot[1:]:
        connector = LineString([runs_rot[-1][-1], seg[0]])
        # A small tolerance: a rasterized contour's own boundary noise
        # can put a legitimate edge-hugging stitch a hair outside the
        # simplified polygon, which shouldn't force a needless trim.
        outside = connector.length - connector.intersection(test_shape).length
        if outside > CONNECTOR_OUTSIDE_TOLERANCE_MM:
            runs_rot.append(list(seg))
        else:
            runs_rot[-1].extend(seg)

    runs: list[list[Point]] = []
    for run in runs_rot:
        if len(run) < 2:
            continue
        line = affinity.rotate(LineString(run), angle_deg, origin=centroid)
        runs.append([(round(x, 4), round(y, 4)) for x, y in line.coords])
    return runs


def pull_compensate(polygon: Polygon, angle_deg: float,
                    pull_compensation_mm: float) -> Polygon:
    """The polygon extended by pull_compensation_mm along the stitch
    direction (half each way), the way src/stitches/satin.py's _widen
    pushes a satin column's rails apart.

    A tensioned stitch pulls the fabric under it inward along its own
    axis, so a shape filled with rows at angle_deg sews narrower in
    that direction than it was drawn -- a filled circle comes out as
    an oval, and the fill stops short of a satin border that was
    supposed to overlap it. Fills had no compensation at all (satin
    did). The extension is a Minkowski sum with a segment along the
    stitch direction, built as the union of the shape and two copies
    shifted half the compensation each way -- exact for any shape
    wider than the compensation, i.e. every shape here; holes shrink
    by the same amount, as they should."""
    if pull_compensation_mm <= 0:
        return polygon
    dx = math.cos(math.radians(angle_deg)) * pull_compensation_mm / 2
    dy = math.sin(math.radians(angle_deg)) * pull_compensation_mm / 2
    grown = unary_union([affinity.translate(polygon, -dx, -dy), polygon,
                         affinity.translate(polygon, dx, dy)])
    if grown.geom_type != "Polygon":
        # A sliver of a multi-part shape can, in theory, come back as
        # several pieces; keep the one that is the shape.
        grown = max(grown.geoms, key=lambda g: g.area)
    return grown


def generate_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                   stitch_length_mm: float, pull_compensation_mm: float = 0.0
                   ) -> list[list[Point]]:
    """Classic tatami fill: return a list of stitchable runs (each a
    list of needle points, mm) filling `polygon`. Almost always a
    single run; more than one when the polygon has holes or is
    otherwise crossed by a row in multiple places.

    pull_compensation_mm extends the rows along their own direction
    (see pull_compensate); 0 fills the shape exactly as drawn.
    """
    polygon = pull_compensate(polygon, angle_deg, pull_compensation_mm)
    centroid = polygon.centroid
    rotated = affinity.rotate(polygon, -angle_deg, origin=centroid)
    xmin, ymin, xmax, ymax = rotated.bounds

    # One entry per row segment (the run-splitting decision is made
    # between segments, not by guessing from stitch distance).
    segments_rot: list[list[Point]] = []
    y = ymin + row_spacing_mm / 2
    row_idx = 0
    while y <= ymax:
        segs = _row_segments(rotated, y, xmin, xmax)
        if segs:
            ordered = segs if row_idx % 2 == 0 else list(reversed(segs))
            for (x0, x1) in ordered:
                lo, hi = (x0, x1) if row_idx % 2 == 0 else (x1, x0)
                n_steps = max(1, int(abs(hi - lo) / stitch_length_mm))
                segments_rot.append([
                    (lo + (hi - lo) * step / n_steps, y) for step in range(n_steps + 1)])
        row_idx += 1
        y += row_spacing_mm

    return _runs_from_segments(segments_rot, angle_deg, centroid, rotated)


def generate_brick_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                         stitch_length_mm: float, pull_compensation_mm: float = 0.0
                         ) -> list[list[Point]]:
    """Same rows as generate_fill, but every other row's needle points
    are phase-shifted half a stitch length from the row before it --
    like brick coursing, instead of tatami's needle holes lining up
    into a straight grid every row_spacing_mm. A real digitizer reaches
    for this for a softer, less visibly "laddered" look on a larger
    fill; the row/angle/hole handling is identical to generate_fill,
    only where each row's points fall differs.
    """
    polygon = pull_compensate(polygon, angle_deg, pull_compensation_mm)
    centroid = polygon.centroid
    rotated = affinity.rotate(polygon, -angle_deg, origin=centroid)
    xmin, ymin, xmax, ymax = rotated.bounds

    segments_rot: list[list[Point]] = []
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
                seg_points: list[Point] = [(lo, y)]
                pos = row_phase if row_phase > 0 else stitch_length_mm
                while pos < span:
                    seg_points.append((lo + direction * pos, y))
                    pos += stitch_length_mm
                seg_points.append((hi, y))
                segments_rot.append(seg_points)
        row_idx += 1
        y += row_spacing_mm

    return _runs_from_segments(segments_rot, angle_deg, centroid, rotated)


def generate_crosshatch_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                              stitch_length_mm: float,
                              second_pass_spacing_scale: float = 1.6,
                              pull_compensation_mm: float = 0.0
                              ) -> list[list[Point]]:
    """Two tatami passes at 90 degrees to each other -- denser feel,
    more stable on stretchy fabric. The same technique
    src/stitches/build.py already auto-applies to texture-flagged
    regions, exposed here as its own selectable fill style
    (src/stitches/model.py's FILL_CROSSHATCH) so it's reachable
    directly, not only via texture detection. The second pass defaults
    to wider spacing so total density doesn't roughly double.
    """
    return (generate_fill(polygon, angle_deg, row_spacing_mm, stitch_length_mm,
                          pull_compensation_mm)
            + generate_fill(polygon, angle_deg + 90,
                             row_spacing_mm * second_pass_spacing_scale, stitch_length_mm,
                             pull_compensation_mm))


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
