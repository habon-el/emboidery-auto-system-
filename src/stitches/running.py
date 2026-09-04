"""Running stitch: resample a path to evenly-spaced needle points.

Every stitch this produces respects the machine's minimum stitch length
(src/stitches/model.py's MIN_STITCH_LENGTH_MM). The previous version
kept every original vertex of the path as a needle point and only
filled the gaps *between* them -- fine for a hand-drawn polyline, but
the paths that actually reach it are pixel-resolution: a medial-axis
centerline has a vertex every 0.3mm and a rasterized contour every
0.17mm, so the "stitch length" parameter was effectively ignored and
the underlay, running-stitch details and contour fills were sewn as
chains of sub-0.3mm stitches (thread breaks; on the cartoon face,
2,000 of them). Corners still matter -- a star's tip or a letter's
serif shouldn't be rounded off -- so a vertex is kept as a needle point
only where the path genuinely turns, judged over a window rather than
vertex to vertex so a pixel staircase doesn't read as a corner at
every step.
"""
import math

from .model import MIN_STITCH_LENGTH_MM, Point

# A vertex is a corner (kept as a needle point) when the path's
# direction changes by at least this much across it, measured between
# the chords half a stitch length before and after it.
CORNER_ANGLE_DEG = 30.0


def _dedupe(pts: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


def _cumulative(pts: list[Point]) -> list[float]:
    acc = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        acc.append(acc[-1] + math.hypot(x1 - x0, y1 - y0))
    return acc


def _point_at(pts: list[Point], cum: list[float], s: float) -> Point:
    """The point s mm along the polyline (clamped to its ends)."""
    if s <= 0:
        return pts[0]
    if s >= cum[-1]:
        return pts[-1]
    # Binary search the segment containing s.
    lo, hi = 0, len(cum) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if cum[mid] <= s:
            lo = mid
        else:
            hi = mid
    seg = cum[hi] - cum[lo]
    frac = 0.0 if seg == 0 else (s - cum[lo]) / seg
    (x0, y0), (x1, y1) = pts[lo], pts[hi]
    return (x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)


def _turn_deg(pts: list[Point], cum: list[float], i: int, window: float,
              closed: bool) -> float:
    total = cum[-1]
    s = cum[i]
    if closed:
        s_before, s_after = (s - window) % total, (s + window) % total
    else:
        s_before, s_after = max(0.0, s - window), min(total, s + window)
    a = _point_at(pts, cum, s_before)
    b = _point_at(pts, cum, s_after)
    v = pts[i]
    ux, uy = v[0] - a[0], v[1] - a[1]
    wx, wy = b[0] - v[0], b[1] - v[1]
    lu, lw = math.hypot(ux, uy), math.hypot(wx, wy)
    if lu == 0 or lw == 0:
        return 0.0
    cos = max(-1.0, min(1.0, (ux * wx + uy * wy) / (lu * lw)))
    return math.degrees(math.acos(cos))


def _anchors(pts: list[Point], cum: list[float], stitch_length_mm: float,
             closed: bool, min_stitch_mm: float) -> list[int]:
    """Indices of the vertices that must be needle points: both ends of
    an open path, plus every genuine corner. Corners closer together
    than the minimum stitch keep only the sharpest of the cluster, so a
    tight curve gets short stitches rather than sub-minimum ones."""
    window = stitch_length_mm / 2
    n = len(pts)
    interior = range(1, n - 1)
    anchors = [0]
    cluster: list[tuple[float, int]] = []   # (turn, index) of nearby corners
    cluster_start = 0.0

    def flush():
        if cluster:
            anchors.append(max(cluster)[1])
            cluster.clear()

    for i in interior:
        turn = _turn_deg(pts, cum, i, window, closed)
        if turn < CORNER_ANGLE_DEG:
            continue
        if cluster and cum[i] - cluster_start >= min_stitch_mm:
            flush()
        if not cluster:
            cluster_start = cum[i]
        cluster.append((turn, i))
    flush()
    anchors.append(n - 1)

    # Drop any anchor that sits within the minimum stitch of the one
    # before it (never the path's own ends).
    kept = [anchors[0]]
    for a in anchors[1:-1]:
        if cum[a] - cum[kept[-1]] >= min_stitch_mm:
            kept.append(a)
    if cum[anchors[-1]] - cum[kept[-1]] < min_stitch_mm and len(kept) > 1:
        kept.pop()
    kept.append(anchors[-1])
    return kept


def resample_path(path_mm: list[Point], stitch_length_mm: float,
                  closed: bool = False,
                  min_stitch_mm: float = MIN_STITCH_LENGTH_MM) -> list[Point]:
    """Walk path_mm and drop a needle point roughly every
    stitch_length_mm, following the path's own curve between points.

    Both ends and every genuine corner are needle points; the span
    between two consecutive corners is divided into equal stitches, so
    no stitch is longer than stitch_length_mm and none shorter than
    min_stitch_mm (a corner that close to the previous one is folded
    into it -- see _anchors).
    """
    if len(path_mm) < 2 or stitch_length_mm <= 0:
        return list(path_mm)

    pts = _dedupe(list(path_mm))
    if closed and len(pts) >= 2 and pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    pts = _dedupe(pts)
    if len(pts) < 2:
        return pts

    cum = _cumulative(pts)
    if cum[-1] < min_stitch_mm:
        # Shorter than one legal stitch: a single stitch end to end is
        # the only thing a machine can sew here.
        return [pts[0], pts[-1]]

    anchors = _anchors(pts, cum, stitch_length_mm, closed, min_stitch_mm)
    out: list[Point] = [pts[anchors[0]]]
    for a, b in zip(anchors, anchors[1:]):
        span = cum[b] - cum[a]
        n_steps = max(1, int(round(span / stitch_length_mm)))
        # Never let rounding produce a stitch over the requested length
        # by more than half a stitch, nor under the minimum.
        while n_steps > 1 and span / n_steps < min_stitch_mm:
            n_steps -= 1
        for step in range(1, n_steps + 1):
            out.append(_point_at(pts, cum, cum[a] + span * step / n_steps))
    return out
