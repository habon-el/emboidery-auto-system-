"""Tatami/fill stitch generation.

Classic tatami fill: parallel rows of stitches following a chosen angle,
spaced `row_spacing_mm` apart, with needle points along each row every
`stitch_length_mm`. Rows snake back and forth (boustrophedon) so the whole
region is covered with minimal travel and consecutive rows connect
directly into each other.

A region can have holes or be crossed by a scan row in more than one
place (a ring/donut shape, a letter like "O", a fill region with a hole
cut out for another color on top of it). Where that happens, connecting
the segments with a plain stitch would sew straight across the gap --
so generate_fill returns a *list of runs* instead of one flat point
list: each run is a real continuous stitch path, and a jump belongs
between runs, not a stitch across empty fabric (Section 9: don't fake
it -- src/pathing/route.py inserts the actual JUMP/TRIM at export time).
"""
import math

from shapely import affinity
from shapely.geometry import LineString, Polygon

from .model import Point


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


def generate_fill(polygon: Polygon, angle_deg: float, row_spacing_mm: float,
                   stitch_length_mm: float) -> list[list[Point]]:
    """Return a list of stitchable runs (each a list of needle points, mm)
    filling `polygon`. Almost always a single run; more than one when the
    polygon has holes or is otherwise crossed by a row in multiple places.
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

    if not points_rot:
        return []

    # Rotate back to original design space.
    line = LineString(points_rot)
    line = affinity.rotate(line, angle_deg, origin=centroid)
    points = [(round(x, 4), round(y, 4)) for x, y in line.coords]

    # Split into separate runs wherever consecutive points are farther
    # apart than a normal within-row/between-row step -- that gap means
    # the scan crossed a hole or a disjoint part of the shape.
    break_threshold_mm = max(stitch_length_mm, row_spacing_mm) * 2.5
    runs: list[list[Point]] = [[points[0]]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if math.hypot(x1 - x0, y1 - y0) > break_threshold_mm:
            runs.append([])
        runs[-1].append((x1, y1))
    return [r for r in runs if len(r) >= 2]
