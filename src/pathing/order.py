"""Sew-order optimization: decide what order to stitch blocks in.

MVP approach: nearest-neighbor greedy, per color group, allowing a block
to be walked in reverse if that end is closer to the current needle
position. This is not globally optimal (that's an NP-hard routing
problem) but it removes the worst travel for simple logos/text, which is
the whole of our in-scope input per Section 2.

The ordered block list this produces is exactly the "correction hook"
called for in Section 6/M3: a human (or a later pass) can re-sequence it
by editing element_id order before export.
"""
import math

from src.stitches.model import (BORDER, FILL, RUNNING, SATIN, UNDERLAY_RUN,
                                 UNDERLAY_SATIN, Point, StitchBlock)

# Underlay must always be sewn before the top stitching it supports, and
# a border ring is stitched last, on top of the fill it outlines, per
# color, regardless of which is spatially closer.
_STAGE_PRIORITY = {
    UNDERLAY_RUN: 0,
    UNDERLAY_SATIN: 0,
    RUNNING: 1,
    SATIN: 2,
    FILL: 2,
    BORDER: 3,
}


def _dist(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def nearest_neighbor_order(blocks: list[StitchBlock],
                            start: Point = (0.0, 0.0)) -> list[StitchBlock]:
    remaining = [b for b in blocks if not b.is_empty()]
    ordered: list[StitchBlock] = []
    cur = start
    while remaining:
        best_i, best_reversed, best_d = 0, False, math.inf
        for i, b in enumerate(remaining):
            d_start = _dist(cur, b.points_mm[0])
            d_end = _dist(cur, b.points_mm[-1])
            if d_start < best_d:
                best_i, best_reversed, best_d = i, False, d_start
            if d_end < best_d:
                best_i, best_reversed, best_d = i, True, d_end
        b = remaining.pop(best_i)
        if best_reversed:
            b = StitchBlock(b.stitch_type, list(reversed(b.points_mm)),
                             b.color_index, b.element_id)
        ordered.append(b)
        cur = b.points_mm[-1]
    return ordered


def order_by_color_then_distance(blocks: list[StitchBlock],
                                  start: Point = (0.0, 0.0),
                                  z_order_by_element: dict[str, int] | None = None
                                  ) -> list[StitchBlock]:
    """Group blocks by color (in first-seen order), then by underlay/top
    stitch stage within each color (underlay always first), and
    nearest-neighbor order within each stage. This keeps all stitching
    for one thread together (COLOR_CHANGE only fires between groups)
    without ever sewing top stitching before its underlay.

    z_order_by_element (element_id -> layer index, lower sews first --
    see Region.z_order and the manual-review workflow's per-region layer
    override in src/review/corrections.py) additionally groups each
    stage's blocks by element and walks the elements in that order,
    nearest-neighbor only *within* one element's own blocks. Left as
    None (the default for every caller except src/pipeline.py), a
    stage's blocks from different elements can interleave by whichever
    is spatially closest -- which is what every existing test and
    caller already expects, so this is purely additive.
    """
    seen_colors: list[int] = []
    for b in blocks:
        if b.color_index not in seen_colors:
            seen_colors.append(b.color_index)

    result: list[StitchBlock] = []
    cur = start
    for color in seen_colors:
        group = [b for b in blocks if b.color_index == color]
        stages = sorted(set(_STAGE_PRIORITY.get(b.stitch_type, 1)
                             for b in group))
        for stage in stages:
            stage_blocks = [b for b in group
                             if _STAGE_PRIORITY.get(b.stitch_type, 1) == stage]
            if z_order_by_element:
                elements = sorted(
                    dict.fromkeys(b.element_id for b in stage_blocks),
                    key=lambda e: z_order_by_element.get(e, 0))
                for element in elements:
                    el_blocks = [b for b in stage_blocks if b.element_id == element]
                    ordered = nearest_neighbor_order(el_blocks, start=cur)
                    result.extend(ordered)
                    if ordered:
                        cur = ordered[-1].points_mm[-1]
            else:
                ordered = nearest_neighbor_order(stage_blocks, start=cur)
                result.extend(ordered)
                if ordered:
                    cur = ordered[-1].points_mm[-1]
    return result
