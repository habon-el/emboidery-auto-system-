"""Satin column stitch generation.

A satin column is defined by two "rails" (the long edges of a thin
region) walked in the same direction. The stitch zigzags between
corresponding points on each rail. Density here is stitches-per-mm along
the rail, not a fill row spacing.
"""
import math

from .model import MAX_STITCH_LENGTH_MM, Point


def _resample_by_arclength(path: list[Point], n_points: int) -> list[Point]:
    if n_points < 2:
        return list(path)
    seg_lens = [
        math.hypot(x1 - x0, y1 - y0)
        for (x0, y0), (x1, y1) in zip(path, path[1:])
    ]
    total = sum(seg_lens)
    if total == 0:
        return [path[0]] * n_points
    targets = [total * i / (n_points - 1) for i in range(n_points)]
    out: list[Point] = []
    acc = 0.0
    seg_i = 0
    for t in targets:
        while seg_i < len(seg_lens) - 1 and acc + seg_lens[seg_i] < t:
            acc += seg_lens[seg_i]
            seg_i += 1
        seg_len = seg_lens[seg_i] if seg_lens else 0
        frac = 0.0 if seg_len == 0 else (t - acc) / seg_len
        (x0, y0), (x1, y1) = path[seg_i], path[seg_i + 1]
        out.append((x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac))
    return out


def average_width_mm(rail_a: list[Point], rail_b: list[Point]) -> float:
    n = min(len(rail_a), len(rail_b))
    if n == 0:
        return 0.0
    return sum(
        math.hypot(rail_a[i][0] - rail_b[i][0], rail_a[i][1] - rail_b[i][1])
        for i in range(n)
    ) / n


def _length(path: list[Point]) -> float:
    return sum(math.hypot(x1 - x0, y1 - y0)
               for (x0, y0), (x1, y1) in zip(path, path[1:]))


def _widen(rail_a: Point, rail_b: Point, amount_mm: float
           ) -> tuple[Point, Point]:
    """Push both rail points apart by amount_mm to compensate for pull-in."""
    (ax, ay), (bx, by) = rail_a, rail_b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0 or amount_mm == 0:
        return rail_a, rail_b
    ux, uy = dx / length, dy / length
    return (
        (ax - ux * amount_mm, ay - uy * amount_mm),
        (bx + ux * amount_mm, by + uy * amount_mm),
    )


def _split_long_stitch(out: list[Point], q: Point, index: int,
                       max_stitch_mm: float) -> None:
    """Append q to out, putting intermediate needle points along the
    way when the stitch from out[-1] to q is longer than the machine
    maximum ("split satin"). The split points are staggered from one
    stitch to the next -- a third of the way, halfway, two thirds --
    so they don't line up into a visible seam down the column, which
    is what a digitizer's auto-split does. The column keeps its full
    width; only the single loose span is broken up."""
    p = out[-1]
    length = math.hypot(q[0] - p[0], q[1] - p[1])
    if length > max_stitch_mm:
        n = math.ceil(length / max_stitch_mm)
        stagger = ((index % 3) - 1) * 0.3
        for k in range(1, n):
            f = min(0.9, max(0.1, (k + stagger) / n))
            out.append((p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f))
    out.append(q)


def generate_satin(rail_a: list[Point], rail_b: list[Point],
                    density_mm: float, pull_compensation_mm: float = 0.0,
                    max_stitch_mm: float = MAX_STITCH_LENGTH_MM) -> list[Point]:
    """Zigzag stitch points between two rails, resampled to `density_mm`.

    A column wider than max_stitch_mm is sewn as split satin: each
    crossing gets intermediate penetrations (staggered stitch to
    stitch) so no single stitch is long enough to snag and loop in
    wear -- see _split_long_stitch. The twill preset allows columns to
    12mm; without this every stitch across an 8mm column left the
    file over the 7mm practical maximum (123 of them on one stroke of
    the cartoon face)."""
    if len(rail_a) < 2 or len(rail_b) < 2:
        return []
    # Stitch spacing is measured down the middle of the column, not
    # along one rail: on a curve the outer rail is longer than the
    # inner one, and taking either alone would set the density from
    # whichever side happened to be passed first.
    rail_len = (_length(rail_a) + _length(rail_b)) / 2
    n_points = max(2, int(rail_len / density_mm) + 1)
    a = _resample_by_arclength(rail_a, n_points)
    b = _resample_by_arclength(rail_b, n_points)

    out: list[Point] = []
    for i in range(n_points):
        pa, pb = _widen(a[i], b[i], pull_compensation_mm / 2)
        for j, point in enumerate((pa, pb)):
            if out:
                _split_long_stitch(out, point, 2 * i + j, max_stitch_mm)
            else:
                out.append(point)
    return out
