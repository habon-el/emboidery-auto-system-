"""Sew a branching satin network -- a letter with a crossbar, a
cartoon's connected line work -- as one continuous pass with no jump
or trim inside it.

The naive way to sew several satin columns that meet at junctions is
one column at a time: finish a branch, jump to the next, trim when the
jump is long. On the cartoon face fixture that put 54 of 88 trims
*inside* elements, and a bold "H" trimmed between its own strokes.

A digitizer's "branching" tool does what this does instead: walk the
network as a tree. Travel down a branch with a running stitch along
its centerline, keep going into whatever branches meet at the far
end, and satin each branch on the way back up. Every outbound run
lies exactly where that branch's satin will sew a moment later, so
it is buried -- it *is* the centerline underlay the column wanted
anyway, just laid in an order that leaves the needle where the next
branch starts. Each branch is travelled once and satined once; the
thread is never cut.

Branches meeting at a junction are found by endpoint proximity: the
skeleton is split at junction pixels (src/regions/medial.py's
_split_into_branches), so the ends of the strokes that meet there
sit within a pixel or two of each other. Loops (a ring, a figure of
eight) are fine: a branch whose far end is a node already visited is
travelled down and satined back like any other -- the walk just
doesn't recurse from it.
"""
import math

from src.params.presets import FabricPreset
from src.stitches.model import SATIN, UNDERLAY_SATIN, Point, StitchBlock
from src.stitches.running import resample_path
from src.stitches.satin import generate_satin

# Two branch endpoints closer than this are the same junction. The
# skeleton is rasterized at 0.3mm and a dropped junction stub can put
# one pixel between the strokes that met at it.
JUNCTION_TOLERANCE_MM = 1.0

Column = tuple[list[Point], list[float], list[Point], list[Point]]


def _dist(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _cluster_endpoints(columns: list[Column]) -> dict[tuple[int, int], int]:
    """(column index, 0 for its start / 1 for its end) -> node id, with
    endpoints within JUNCTION_TOLERANCE_MM of each other sharing a
    node. Union-find over the handful of endpoints a shape has."""
    keys = [(ci, end) for ci in range(len(columns)) for end in (0, 1)]
    point = {(ci, end): columns[ci][0][-end] for ci, end in keys}
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if _dist(point[a], point[b]) <= JUNCTION_TOLERANCE_MM:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    roots = sorted(set(find(k) for k in keys))
    node_id = {root: n for n, root in enumerate(roots)}
    return {k: node_id[find(k)] for k in keys}


def sequence_satin_network(columns: list[Column], fabric: FabricPreset,
                           color_index: int, element_id: str,
                           start_near: Point = (0.0, 0.0)) -> list[StitchBlock]:
    """Blocks for the whole network in sew order, each stamped with
    its position in the chain (StitchBlock.sequence) so pathing keeps
    them together and in order. A disconnected network (two strokes
    that never meet) walks each component in turn, nearest first."""
    node_of = _cluster_endpoints(columns)
    touching: dict[int, list[tuple[int, int]]] = {}
    for (ci, end), node in node_of.items():
        touching.setdefault(node, []).append((ci, end))
    node_point = {node: columns[ci][0][-end] for (ci, end), node in node_of.items()}
    degree = {node: len(ends) for node, ends in touching.items()}

    blocks: list[StitchBlock] = []
    visited_columns: set[int] = set()
    visited_nodes: set[int] = set()

    def emit(kind: str, points: list[Point]) -> None:
        blocks.append(StitchBlock(kind, points, color_index, element_id,
                                  sequence=len(blocks)))

    def walk(node: int) -> None:
        visited_nodes.add(node)
        for ci, end in sorted(touching[node]):
            if ci in visited_columns:
                continue
            visited_columns.add(ci)
            centerline, widths, rail_a, rail_b = columns[ci]
            if end == 1:
                # We're at this column's far end: traverse it reversed.
                centerline, rail_a, rail_b = (list(reversed(centerline)),
                                              list(reversed(rail_a)),
                                              list(reversed(rail_b)))
            far = node_of[(ci, 1 - end)]
            # Down: the centerline run doubles as the column's underlay.
            emit(UNDERLAY_SATIN, resample_path(centerline, fabric.running_stitch_length_mm))
            if far not in visited_nodes:
                walk(far)
            # Back: satin over it, ending where this branch began. The
            # zigzag itself starts and ends on a rail, half a width
            # off the centerline; bracketing it with the two junction
            # points makes every link of the chain start exactly where
            # the last one ended, so nothing inside the element is
            # ever a jump.
            zigzag = generate_satin(list(reversed(rail_a)), list(reversed(rail_b)),
                                    fabric.satin_density_mm, fabric.pull_compensation_mm)
            emit(SATIN, [centerline[-1]] + zigzag + [centerline[0]])

    cur = start_near
    while len(visited_columns) < len(columns):
        # Start each component at a loose end (a leaf) when it has one,
        # nearest to where the needle is; a pure ring starts at its
        # nearest node.
        open_nodes = [n for n in touching
                      if any(ci not in visited_columns for ci, _ in touching[n])]
        leaves = [n for n in open_nodes if degree[n] == 1] or open_nodes
        root = min(leaves, key=lambda n: (_dist(cur, node_point[n]), n))
        walk(root)
        cur = blocks[-1].points_mm[-1]
    return blocks
