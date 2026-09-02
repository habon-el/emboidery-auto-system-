"""Medial-axis extraction for a region: used to derive the fill angle
from the shape's own skeleton rather than its bounding box (Section 9 --
this is a place naive auto-digitizers get wrong), and to derive satin
rails for regions src/params/classify.py has already decided are
simple, band-shaped satin candidates.

MVP approach: rasterize the polygon at a fixed resolution, run
skimage's medial_axis to get a skeleton + per-pixel distance-to-edge,
prune short spurious branches (see _prune_spurs), then walk the
skeleton pixels into an ordered path with a greedy walk from an
endpoint. This assumes a simple (largely unbranched) skeleton -- true
for the satin candidates classify.py routes here, since it screens out
branching/non-rectangular shapes geometrically before the skeleton walk
is ever used for anything but the (order-independent) PCA angle.
"""
import math

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon
from skimage.morphology import medial_axis

from src.stitches.model import Point

RASTER_RES_MM = 0.3
# A branch off the skeleton is pruned as noise if it's shorter than this
# multiple of the local width at the junction it branches from. This is
# resolution/scale independent: e.g. a rectangle's medial axis always has
# short diagonal spurs to its corners (~sqrt(2) x half the short side),
# which are shorter than the shape's own width and get pruned regardless
# of how big the rectangle is; a star's real arm is longer than its own
# base width and survives.
SPUR_SIGNIFICANCE_FACTOR = 1.2


def _rasterize(polygon: Polygon, res_mm: float
                ) -> tuple[np.ndarray, tuple[float, float]]:
    minx, miny, maxx, maxy = polygon.bounds
    pad = res_mm * 3
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    w = max(2, int((maxx - minx) / res_mm))
    h = max(2, int((maxy - miny) / res_mm))

    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)

    def to_px(pt: Point) -> tuple[float, float]:
        return ((pt[0] - minx) / res_mm, (pt[1] - miny) / res_mm)

    draw.polygon([to_px(p) for p in polygon.exterior.coords], fill=255)
    for interior in polygon.interiors:
        draw.polygon([to_px(p) for p in interior.coords], fill=0)

    return np.array(img) > 0, (minx, miny)


def _neighbors_of(coord_set: set[tuple[int, int]], c: tuple[int, int]
                   ) -> list[tuple[int, int]]:
    x, y = c
    return [(x + dx, y + dy)
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0) and (x + dx, y + dy) in coord_set]


def _prune_spurs(coords_px: list[tuple[int, int]], distance: np.ndarray,
                  res_mm: float, significance_factor: float
                  ) -> list[tuple[int, int]]:
    """Remove short dead-end branches from the raw skeleton before
    walking it. Rasterizing a smooth curve (e.g. a circle) produces a
    jagged boundary, and medial_axis turns each little jag into a short
    spurious "hair" branch off the real skeleton -- left unpruned, a
    compact blob's greedy walk can wander down these hairs and report a
    skeleton far longer (and more "elongated") than the shape actually
    is. This iteratively trims any branch shorter than
    significance_factor times the local width at its junction, leaving
    real structure (e.g. a star's actual arms, which are longer than
    their own base width) intact -- see module constant for why this is
    scale-independent.
    """
    coord_set = set(coords_px)
    width_at = lambda c: distance[c[1], c[0]] * 2 * res_mm  # noqa: E731

    changed = True
    while changed and len(coord_set) > 1:
        changed = False
        leaves = [c for c in coord_set if len(_neighbors_of(coord_set, c)) == 1]
        for leaf in leaves:
            if leaf not in coord_set:
                continue
            # Walk from the leaf until we reach a junction pixel (degree
            # != 2 relative to where we came from); the walk appends that
            # junction pixel too, so path[-1] is the junction and
            # path[:-1] is exactly the spur to remove.
            path = [leaf]
            cur, prev = leaf, None
            while True:
                nbrs = [n for n in _neighbors_of(coord_set, cur) if n != prev]
                if len(nbrs) != 1:
                    break
                prev, cur = cur, nbrs[0]
                path.append(cur)
            spur_len_mm = (len(path) - 1) * res_mm

            junction_width_mm = width_at(cur)

            if (spur_len_mm < significance_factor * junction_width_mm
                    and len(coord_set) - (len(path) - 1) >= 1):
                for c in path[:-1]:  # discard the spur, keep the junction pixel
                    coord_set.discard(c)
                changed = True
    return [c for c in coords_px if c in coord_set]


def _walk_skeleton(coords_px: list[tuple[int, int]]) -> list[int]:
    """Greedy walk from an endpoint (degree-1 pixel) across 8-connected
    skeleton neighbors. Good enough for the largely-unbranched skeletons
    typical of a satin band or a single stroke."""
    coord_set = set(coords_px)
    index_of = {c: i for i, c in enumerate(coords_px)}
    neighbors: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (x, y) in coords_px:
        n = [(x + dx, y + dy)
             for dx in (-1, 0, 1) for dy in (-1, 0, 1)
             if (dx, dy) != (0, 0) and (x + dx, y + dy) in coord_set]
        neighbors[(x, y)] = n

    degree = {c: len(n) for c, n in neighbors.items()}
    endpoints = [c for c, d in degree.items() if d == 1]
    start = endpoints[0] if endpoints else coords_px[0]

    visited = {start}
    path = [start]
    cur = start
    while True:
        nxts = [n for n in neighbors[cur] if n not in visited]
        if not nxts:
            break
        nxt = nxts[0]
        visited.add(nxt)
        path.append(nxt)
        cur = nxt
    return [index_of[c] for c in path]


class MedialAxisResult:
    def __init__(self, path_points_mm: list[Point], widths_mm: list[float],
                 total_skeleton_length_mm: float = 0.0):
        self.path_points_mm = path_points_mm
        self.widths_mm = widths_mm
        # Length of the FULL pruned skeleton (every branch, before the
        # single greedy walk picks one path through it) -- unlike
        # length_mm below, this stays meaningful for a branching shape
        # (a star's arms + hub, not just whichever arm the walk followed).
        # Used by src/params/classify.py as area/this for a true
        # average-width estimate that doesn't depend on walk order.
        self.total_skeleton_length_mm = total_skeleton_length_mm

    @property
    def length_mm(self) -> float:
        return sum(
            math.hypot(x1 - x0, y1 - y0)
            for (x0, y0), (x1, y1) in zip(self.path_points_mm, self.path_points_mm[1:])
        )

    @property
    def avg_width_mm(self) -> float:
        return sum(self.widths_mm) / len(self.widths_mm) if self.widths_mm else 0.0

    @property
    def max_width_mm(self) -> float:
        return float(np.percentile(self.widths_mm, 90)) if self.widths_mm else 0.0

    def angle_deg(self) -> float:
        """Principal direction of the skeleton via PCA -- follows the
        shape's own curvature/orientation, not its bounding box."""
        if len(self.path_points_mm) < 2:
            return 0.0
        pts = np.array(self.path_points_mm)
        pts = pts - pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts, full_matrices=False)
        dx, dy = vt[0]
        return math.degrees(math.atan2(dy, dx))

    def rails(self) -> tuple[list[Point], list[Point]]:
        """Synthetic satin rails offset perpendicular to the skeleton by
        the local half-width. Approximates the true region boundary
        without needing to trace/split it -- a known MVP simplification
        (see module docstring)."""
        pts = self.path_points_mm
        rail_a: list[Point] = []
        rail_b: list[Point] = []
        n = len(pts)
        for i in range(n):
            prev_i, next_i = max(0, i - 1), min(n - 1, i + 1)
            tx = pts[next_i][0] - pts[prev_i][0]
            ty = pts[next_i][1] - pts[prev_i][1]
            tlen = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / tlen, tx / tlen
            half_w = self.widths_mm[i] / 2
            x, y = pts[i]
            rail_a.append((x + nx * half_w, y + ny * half_w))
            rail_b.append((x - nx * half_w, y - ny * half_w))
        return rail_a, rail_b


MEDIAL_AXIS_RNG_SEED = 1729


def compute_medial_axis(polygon: Polygon, res_mm: float = RASTER_RES_MM
                         ) -> MedialAxisResult:
    mask, (ox, oy) = _rasterize(polygon, res_mm)
    # skimage's medial_axis draws an unseeded PRNG by default (its `rng`
    # param, used to break exact distance-transform ties -- a straight,
    # symmetric shape like a satin bar is full of these) -- left
    # unseeded, the *same* polygon can skeletonize to a visibly
    # different pixel count from one call to the next, which cascades
    # into a different satin rail walk and a different stitch count for
    # a design that never changed. A fixed seed makes this reproducible.
    skeleton, distance = medial_axis(
        mask, return_distance=True, rng=MEDIAL_AXIS_RNG_SEED)
    ys, xs = np.nonzero(skeleton)
    if len(xs) == 0:
        return MedialAxisResult([], [])

    coords_px = list(zip(xs.tolist(), ys.tolist()))
    coords_px = _prune_spurs(coords_px, distance, res_mm, SPUR_SIGNIFICANCE_FACTOR)
    if not coords_px:
        return MedialAxisResult([], [])
    # Every remaining skeleton pixel represents ~res_mm of centerline,
    # regardless of how the branches connect -- capture that total before
    # _walk_skeleton below restricts to a single path through the tree.
    total_skeleton_length_mm = len(coords_px) * res_mm

    order = _walk_skeleton(coords_px)
    ordered_coords = [coords_px[i] for i in order]

    path_points_mm = [(ox + x * res_mm, oy + y * res_mm) for x, y in ordered_coords]
    widths_mm = [distance[y, x] * 2 * res_mm for x, y in ordered_coords]
    return MedialAxisResult(path_points_mm, widths_mm, total_skeleton_length_mm)
