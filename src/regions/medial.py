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
from collections import deque

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

# A branch shorter than this multiple of its own width is the fragment
# where several strokes meet, not a stroke in its own right (a bold "H"
# splits into 5 real branches plus 5 stubs 0.3mm long and 3.2mm wide).
# Offsetting rails +/-1.6mm either side of a 0.3mm path spins the
# perpendicular right round and sews a spiky starburst at every
# junction, so these are dropped -- the real branches meeting there
# already cover that fabric.
MIN_BRANCH_LENGTH_OVER_WIDTH = 1.0

# A loop-like skeleton (no loose ends) is accepted as a closed ring when
# a single walk round it reaches at least this much of the skeleton.
LOOP_COVERAGE_MIN = 0.85



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


def _build_neighbors(coords_px: list[tuple[int, int]]) -> dict:
    coord_set = set(coords_px)
    return {(x, y): [(x + dx, y + dy)
                     for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                     if (dx, dy) != (0, 0) and (x + dx, y + dy) in coord_set]
            for (x, y) in coords_px}


def _neighbor_components(coord_set: set, c: tuple[int, int]) -> int:
    """How many *distinct directions* the skeleton leaves this pixel in:
    the number of 8-connected components among its present neighbours.

    Counting raw neighbours instead badly over-reports junctions. A
    skeleton line running diagonally is a staircase, and a staircase
    pixel legitimately touches three others that are all part of the
    same single line -- on a plain rotated satin bar that read as 86
    "branches" where there is really one stroke, and all but one got
    dropped, leaving most of the bar unstitched. Grouping mutually
    adjacent neighbours into one direction is the standard fix (the
    connectivity number): a straight run scores 2 wherever it goes,
    an endpoint 1, a real junction 3+.
    """
    x, y = c
    present = [(x + dx, y + dy)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               if (dx, dy) != (0, 0) and (x + dx, y + dy) in coord_set]
    unassigned = set(present)
    components = 0
    while unassigned:
        stack = [unassigned.pop()]
        components += 1
        while stack:
            cur = stack.pop()
            for other in list(unassigned):
                if max(abs(cur[0] - other[0]), abs(cur[1] - other[1])) <= 1:
                    unassigned.discard(other)
                    stack.append(other)
    return components


def _split_into_branches(coords_px: list[tuple[int, int]]
                          ) -> list[list[tuple[int, int]]]:
    """Cut the skeleton into its individual strokes: maximal runs of
    pixels between one junction/endpoint and the next.

    Line art is not a set of tidy separate strokes -- on a real cartoon
    face every black outline touches its neighbours, so the whole black
    colour layer extracts as ONE connected branching network (head
    outline into the ears, into the hairline, into the eyebrows). A
    single satin column can only trace one path through that, which on
    the real fixture covered just 33% of the skeleton and would have
    left the other 67% unstitched. Splitting at the junctions gives one
    clean stroke per branch, each of which can carry its own satin
    column, so the whole network gets stitched.
    """
    neighbors = _build_neighbors(coords_px)
    coord_set = set(coords_px)
    # Direction count, not raw neighbour count -- see _neighbor_components.
    degree = {c: _neighbor_components(coord_set, c) for c in coords_px}
    nodes = [c for c in coords_px if degree[c] != 2]   # junctions + endpoints

    branches: list[list[tuple[int, int]]] = []
    used_edges: set[frozenset] = set()

    for node in nodes:
        for first in neighbors[node]:
            edge = frozenset((node, first))
            if edge in used_edges:
                continue
            branch = [node, first]
            used_edges.add(edge)
            prev, cur = node, first
            while degree[cur] == 2:
                nxt = next((n for n in neighbors[cur] if n != prev), None)
                if nxt is None or frozenset((cur, nxt)) in used_edges:
                    break
                used_edges.add(frozenset((cur, nxt)))
                branch.append(nxt)
                prev, cur = cur, nxt
            if len(branch) >= 2:
                branches.append(branch)

    if not branches and coords_px:
        # No junctions and no endpoints at all: a pure closed ring.
        branches.append([coords_px[i] for i in _walk_skeleton(coords_px)])
    return branches


def _walk_skeleton(coords_px: list[tuple[int, int]]) -> list[int]:
    """Longest-path walk across 8-connected skeleton neighbors, via the
    standard double-sweep BFS technique (BFS from any pixel to find the
    farthest pixel U, then BFS from U to find the farthest pixel V --
    the U-to-V shortest path is the graph's longest simple path for a
    tree, and it's what we want here).

    A single greedy "walk forward, never backtrack" pass (this
    function's original approach) is not safe even starting from a
    real endpoint: a rasterized skeleton at RASTER_RES_MM's resolution
    is not always the clean open tree the module docstring assumes.
    Confirmed on a real bold-sans-serif "l" satin column: pruning left
    a long ~40-pixel spine with a tiny leftover 3-pixel *loop* at each
    tip (a real skimage medial_axis artifact at this resolution, not a
    shape property) -- every pixel in the graph then has degree >= 2,
    so there's no true degree-1 endpoint to start from at all, and a
    greedy walk from any pixel can wander around one tiny end-loop and
    dead-end after 2-3 points, never reaching the real spine, entirely
    depending on which neighbor happens to be tried first. BFS doesn't
    have that failure mode: it explores every direction at once, so it
    can't get trapped by one bad first choice.
    """
    coord_set = set(coords_px)
    index_of = {c: i for i, c in enumerate(coords_px)}
    neighbors: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (x, y) in coords_px:
        n = [(x + dx, y + dy)
             for dx in (-1, 0, 1) for dy in (-1, 0, 1)
             if (dx, dy) != (0, 0) and (x + dx, y + dy) in coord_set]
        neighbors[(x, y)] = n

    def farthest_via_bfs(start: tuple[int, int]
                          ) -> tuple[tuple[int, int], dict]:
        parent = {start: None}
        queue = deque([start])
        farthest = start
        while queue:
            cur = queue.popleft()
            farthest = cur
            for n in neighbors[cur]:
                if n not in parent:
                    parent[n] = cur
                    queue.append(n)
        return farthest, parent

    # A skeleton with no endpoints at all and every pixel of degree 2 is
    # a closed ring -- the medial axis of an outline stroke that loops
    # back on itself (a head outline, a letter "o", a badge border).
    # BFS between two points on a ring returns the *shorter way round*,
    # i.e. half the loop, which would satin only half an outline; walk
    # the whole cycle instead.
    coord_set = set(coords_px)
    degree = {c: _neighbor_components(coord_set, c) for c in coords_px}
    if not any(d <= 1 for d in degree.values()):
        # No loose ends anywhere: the skeleton closes on itself. Demanding
        # every pixel be exactly degree 2 was too strict -- a couple of
        # rasterization junctions anywhere on the ring failed the test,
        # BFS then returned the shorter way round (exactly half), and a
        # letter "o" came out stitched as a "c". Walk it greedily instead
        # and accept it as a ring if the walk gets most of the way round.
        start = coords_px[0]
        cycle = [start]
        visited = {start}
        cur, prev = start, None
        while True:
            nxts = [n for n in neighbors[cur] if n != prev and n not in visited]
            if not nxts:
                break
            prev, cur = cur, nxts[0]
            visited.add(cur)
            cycle.append(cur)
        if len(cycle) >= LOOP_COVERAGE_MIN * len(coords_px):
            return [index_of[c] for c in cycle]

    u, _ = farthest_via_bfs(coords_px[0])
    v, parent = farthest_via_bfs(u)

    path = [v]
    cur = v
    while parent[cur] is not None:
        cur = parent[cur]
        path.append(cur)
    path.reverse()
    return [index_of[c] for c in path]


# The centerline smoothing window, as a multiple of the stroke's own
# width. A pixel skeleton only ever steps in 45-degree increments, so
# its local direction flips by up to 45 degrees from one pixel to the
# next; offsetting rails by half the width along those normals swings
# each rail point a millimetre or more either side of where the edge
# really is. On the satin bar fixture that inflated a 34mm rail to
# 150mm of zigzag, so the column got 4x the requested stitch density
# (needle breakage) with a visibly ragged edge. Smoothing over about
# one width's worth of pixels takes the staircase out while keeping
# any genuine bend of the stroke, which is longer than that by
# definition (a stroke can't turn tighter than its own width).
SMOOTH_WINDOW_WIDTHS = 1.0
SMOOTH_WINDOW_MIN_PTS = 3
SMOOTH_WINDOW_MAX_PTS = 15


def _smooth_path(pts: list[Point], widths_mm: list[float], closed: bool,
                  res_mm: float) -> tuple[list[Point], list[float]]:
    """Centred moving average over the skeleton points and their
    widths. An open path keeps its two endpoints exactly (a stroke
    must start and end where the shape does); a closed ring wraps."""
    n = len(pts)
    if n < 3:
        return list(pts), list(widths_mm)
    avg_w = sum(widths_mm) / n
    half = int(round(avg_w * SMOOTH_WINDOW_WIDTHS / res_mm / 2))
    half = max((SMOOTH_WINDOW_MIN_PTS - 1) // 2, min((SMOOTH_WINDOW_MAX_PTS - 1) // 2, half))
    out_pts: list[Point] = []
    out_w: list[float] = []
    for i in range(n):
        if closed:
            idx = [(i + k) % n for k in range(-half, half + 1)]
        else:
            # Shrink the window symmetrically near the ends so the
            # endpoints themselves stay put and the path doesn't
            # retreat from the stroke's tips.
            h = min(half, i, n - 1 - i)
            idx = list(range(i - h, i + h + 1))
        out_pts.append((sum(pts[j][0] for j in idx) / len(idx),
                        sum(pts[j][1] for j in idx) / len(idx)))
        out_w.append(sum(widths_mm[j] for j in idx) / len(idx))
    return out_pts, out_w


def _offset_rails(pts: list[Point], widths_mm: list[float], closed: bool
                   ) -> tuple[list[Point], list[Point]]:
    """Offset a centerline into two satin rails, perpendicular to the
    local tangent by the local half-width. A closed ring wraps its
    tangents at the seam so the column doesn't flare where it meets."""
    rail_a: list[Point] = []
    rail_b: list[Point] = []
    n = len(pts)
    for i in range(n):
        if closed:
            prev_i, next_i = (i - 1) % n, (i + 1) % n
        else:
            prev_i, next_i = max(0, i - 1), min(n - 1, i + 1)
        tx = pts[next_i][0] - pts[prev_i][0]
        ty = pts[next_i][1] - pts[prev_i][1]
        tlen = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / tlen, tx / tlen
        half_w = widths_mm[i] / 2
        x, y = pts[i]
        rail_a.append((x + nx * half_w, y + ny * half_w))
        rail_b.append((x - nx * half_w, y - ny * half_w))
    return rail_a, rail_b


class MedialAxisResult:
    def __init__(self, path_points_mm: list[Point], widths_mm: list[float],
                 total_skeleton_length_mm: float = 0.0,
                 is_closed_loop: bool = False,
                 branches: list[tuple[list, list]] | None = None,
                 skeleton_px: int = 0):
        self.path_points_mm = path_points_mm
        self.widths_mm = widths_mm
        # True when the walked path is a closed ring (an outline stroke
        # that loops back on itself). rails() wraps its tangents so the
        # satin column closes cleanly instead of flaring at the seam.
        self.is_closed_loop = is_closed_loop
        # Every stroke in the skeleton as (points_mm, widths_mm) -- one
        # entry for a simple stroke, several when the strokes form a
        # connected network (see _split_into_branches). Satin uses these
        # so a branching outline gets a column per branch instead of one
        # column covering a fraction of it.
        self.branches = branches or []
        # Pixel count of the whole pruned skeleton, so coverage can be
        # compared against len(path_points_mm) directly. (Comparing
        # *lengths* doesn't work: a diagonal step measures 0.42mm while
        # contributing one 0.3mm pixel, so a ring reads as 119% covered.)
        self.skeleton_px = skeleton_px
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
    def path_coverage(self) -> float:
        """Fraction of the skeleton the single walked centerline
        explains. ~1 for a simple stroke (one satin column covers it);
        well below 1 for a branching network, where one column would
        leave the rest unstitched."""
        if self.skeleton_px <= 0:
            return 1.0
        return min(1.0, len(self.path_points_mm) / self.skeleton_px)

    @property
    def width_variation(self) -> float:
        """Coefficient of variation of the width along the centerline.
        Near 0 for a real stroke (an outline, an eyebrow, a satin band
        keep a near-constant width down their length); large for a blob,
        whose medial axis runs from a fat middle out to thin tips. This
        is what distinguishes a *curved stroke* from a blob without
        appealing to the bounding rectangle, which any curve fails."""
        if len(self.widths_mm) < 2:
            return 0.0
        mean = self.avg_width_mm
        if mean <= 0:
            return 0.0
        var = sum((w - mean) ** 2 for w in self.widths_mm) / len(self.widths_mm)
        return math.sqrt(var) / mean

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

    def stitchable_coverage(self) -> float:
        """Fraction of the skeleton the satin columns we would actually
        emit (branch_rails) manage to cover. Satin is only the right
        answer when it covers the whole stroke: a shape we can only
        partly column is better off filled, which covers everything by
        construction. Without this gate a letter "o" -- a ring whose
        skeleton splits into arcs we can't fully reassemble -- came out
        stitched as a "c"."""
        if self.skeleton_px <= 0:
            return 1.0
        covered = sum(len(rail_a) for rail_a, _ in self.branch_rails())
        return min(1.0, covered / self.skeleton_px)

    def branch_aspects(self) -> list[float]:
        """length / width for each stroke, junction stubs excluded. A
        satin column should be meaningfully longer than it is wide;
        judging that per branch rather than on the summed skeleton is
        what separates a real stroke network (a cartoon's outlines, a
        letter's stems) from a stubby branching blob like a thick plus
        sign, whose short arms would otherwise add up to a stroke-like
        total while each one is as wide as it is long."""
        out = []
        for points, widths in self.branches:
            if len(points) < 2 or not widths:
                continue
            length = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                         for a, b in zip(points, points[1:]))
            avg_w = sum(widths) / len(widths)
            if avg_w <= 0:
                continue
            aspect = length / avg_w
            if aspect >= MIN_BRANCH_LENGTH_OVER_WIDTH:
                out.append(aspect)
        return out

    def branch_columns(self) -> list[tuple[list[Point], list[float], list[Point], list[Point]]]:
        """Every satin column this shape sews as: (centerline points,
        widths, rail_a, rail_b) per stroke -- the same strokes
        branch_rails() returns rails for, with their centerlines kept
        so src/stitches/satin_network.py can travel along a branch
        before satining it and find where branches meet."""
        kept = []
        covered_px = 0
        for points, widths in self.branches:
            if len(points) < 2 or not widths:
                continue
            length = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                         for a, b in zip(points, points[1:]))
            avg_w = sum(widths) / len(widths)
            if avg_w > 0 and length / avg_w < MIN_BRANCH_LENGTH_OVER_WIDTH:
                continue                      # a junction stub, not a stroke
            rail_a, rail_b = _offset_rails(points, widths, closed=False)
            if len(rail_a) >= 2:
                kept.append((points, widths, rail_a, rail_b))
                covered_px += len(points)

        if not kept or covered_px <= len(self.path_points_mm):
            rail_a, rail_b = self.rails()
            return [(self.path_points_mm, self.widths_mm, rail_a, rail_b)]
        return kept

    def branch_rails(self) -> list[tuple[list[Point], list[Point]]]:
        """One satin rail pair per stroke in the skeleton. For a simple
        stroke that's a single pair identical to rails(); for a
        branching outline network it's one pair per branch, so the whole
        network gets stitched rather than just the one path a single
        column could trace."""
        # Whichever actually covers more of the skeleton wins, rather
        # than a threshold guess. Both options genuinely lose coverage
        # in different cases: a single column can only trace one path
        # through a branching outline network (33% of a real cartoon's
        # black layer), while branch splitting fragments a plain
        # rasterized stroke into dozens of stubs that individually get
        # dropped (a rotated satin bar decomposed into 78 pieces, and
        # keeping only the few valid ones left most of the bar bare).
        # Comparing the two directly is what keeps both cases whole.
        return [(rail_a, rail_b) for _, _, rail_a, rail_b in self.branch_columns()]

    def rails(self) -> tuple[list[Point], list[Point]]:
        """Synthetic satin rails offset perpendicular to the skeleton by
        the local half-width. Approximates the true region boundary
        without needing to trace/split it -- a known MVP simplification
        (see module docstring)."""
        return _offset_rails(self.path_points_mm, self.widths_mm,
                              closed=self.is_closed_loop)


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
    # The walk covered every skeleton pixel and came back to where it
    # started -- a closed ring, not an open stroke with two ends.
    is_closed_loop = (len(order) == len(coords_px) > 2
                      and max(abs(ordered_coords[0][0] - ordered_coords[-1][0]),
                              abs(ordered_coords[0][1] - ordered_coords[-1][1])) <= 1)

    def to_mm(coords, closed):
        pts = [(ox + x * res_mm, oy + y * res_mm) for x, y in coords]
        widths = [distance[y, x] * 2 * res_mm for x, y in coords]
        return _smooth_path(pts, widths, closed, res_mm)

    path_points_mm, widths_mm = to_mm(ordered_coords, is_closed_loop)
    branches = [to_mm(b, False) for b in _split_into_branches(coords_px)]
    return MedialAxisResult(path_points_mm, widths_mm, total_skeleton_length_mm,
                             is_closed_loop, branches, len(coords_px))
