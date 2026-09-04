"""Sew-order optimization: decide what order to stitch blocks in.

The order a design sews in is most of what separates a file a machine
runs cleanly from one that spends its time trimming and hopping. The
rules here are the ones a human digitizer applies by hand:

* One thread at a time. Every block of a color sews before the next
  color starts -- a color change is the most expensive event on the
  machine, so there is exactly one per color.
* Fills before outlines. Colors whose stitching is mostly satin and
  running-stitch detail (a cartoon's black line work, a swoosh) sew
  after the colors that are mostly fill, and the biggest fill sews
  first: an outline sewn *under* the fill it borders is buried by the
  fill's edge. The previous order (whichever color the quantizer
  happened to label first) sewed a face's black outlines before its
  skin.
* Finish each element before moving on. An element's underlay, then
  its top stitching, then its border, back to back -- not "every
  element's underlay, then every element's top stitching", which
  visited every letter of a word twice and doubled its trims.
* Nearest next. Among the elements a layer order leaves free (see
  z_order below), the one whose nearest end is closest to where the
  needle already is comes next, and a block is walked in reverse when
  that end is closer. Nearest-neighbor isn't globally optimal (that's
  an NP-hard routing problem) but it turns the quantizer's arbitrary
  discovery order into a path that reads left-to-right across a word
  and stays local on an illustration.

All of it is deterministic: ties break on first-seen order, never on
anything that varies between runs.

The ordered block list this produces is exactly the "correction hook"
called for in Section 6/M3: a human (or a later pass) can re-sequence
it by editing element_id order before export.
"""
import math

from src.stitches.model import (BORDER, FILL, RUNNING, SATIN, UNDERLAY_RUN,
                                 UNDERLAY_SATIN, Point, StitchBlock)

# Within one element: underlay must always be sewn before the top
# stitching it supports, and a border ring is stitched last, on top of
# the fill it outlines, regardless of which is spatially closer.
_STAGE_PRIORITY = {
    UNDERLAY_RUN: 0,
    UNDERLAY_SATIN: 0,
    RUNNING: 1,
    SATIN: 2,
    FILL: 2,
    BORDER: 3,
}

# A color is an "outline" color when at least this share of its top
# stitching (by thread length) is satin or running stitch rather than
# fill. Outline colors sew after fill colors.
OUTLINE_COLOR_SHARE = 0.5

_OUTLINE_TYPES = (SATIN, RUNNING)
_FILL_TYPES = (FILL, BORDER)


def _dist(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _length(points: list[Point]) -> float:
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


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
                             b.color_index, b.element_id, b.force_trim_before,
                             b.sequence)
        ordered.append(b)
        cur = b.points_mm[-1]
    return ordered


def color_sew_order(blocks: list[StitchBlock]) -> list[int]:
    """The order the thread colors sew in: fill colors first, largest
    first; outline colors (mostly satin/running) after them. Ties keep
    first-seen order."""
    first_seen: dict[int, int] = {}
    outline_mm: dict[int, float] = {}
    fill_mm: dict[int, float] = {}
    for b in blocks:
        if b.is_empty():
            continue
        c = b.color_index
        first_seen.setdefault(c, len(first_seen))
        if b.stitch_type in _OUTLINE_TYPES:
            outline_mm[c] = outline_mm.get(c, 0.0) + _length(b.points_mm)
        elif b.stitch_type in _FILL_TYPES:
            fill_mm[c] = fill_mm.get(c, 0.0) + _length(b.points_mm)

    def key(c: int):
        top = outline_mm.get(c, 0.0) + fill_mm.get(c, 0.0)
        share = outline_mm.get(c, 0.0) / top if top > 0 else 0.0
        is_outline = share >= OUTLINE_COLOR_SHARE
        return (is_outline, -top, first_seen[c])

    return sorted(first_seen, key=key)


def _entry_distance(el_blocks: list[StitchBlock], cur: Point) -> float:
    """How far the needle has to travel to start this element: to the
    nearest end of any block in its first stage (which is what it
    would sew first), or to the fixed start of its chain."""
    chain = [b for b in el_blocks if b.sequence is not None]
    if chain:
        first = min(chain, key=lambda b: b.sequence)
        return _dist(cur, first.points_mm[0])
    first_stage = min(_STAGE_PRIORITY.get(b.stitch_type, 1) for b in el_blocks)
    return min(min(_dist(cur, b.points_mm[0]), _dist(cur, b.points_mm[-1]))
               for b in el_blocks
               if _STAGE_PRIORITY.get(b.stitch_type, 1) == first_stage)


def _order_element(el_blocks: list[StitchBlock], cur: Point
                   ) -> tuple[list[StitchBlock], Point]:
    """One element start to finish: each stage in order, nearest-
    neighbor within a stage, picking up from wherever the previous
    stage left the needle."""
    out: list[StitchBlock] = []
    chain = sorted((b for b in el_blocks if b.sequence is not None),
                   key=lambda b: b.sequence)
    if chain:
        # A fixed chain (see StitchBlock.sequence) sews first, as
        # built: every link starts where the last one ended, so there
        # is nothing for nearest-neighbor to improve and reversing a
        # link would break the continuity that makes it trim-free.
        out.extend(chain)
        cur = chain[-1].points_mm[-1]
        el_blocks = [b for b in el_blocks if b.sequence is None]
    stages = sorted(set(_STAGE_PRIORITY.get(b.stitch_type, 1) for b in el_blocks))
    for stage in stages:
        stage_blocks = [b for b in el_blocks
                        if _STAGE_PRIORITY.get(b.stitch_type, 1) == stage]
        ordered = nearest_neighbor_order(stage_blocks, start=cur)
        out.extend(ordered)
        if ordered:
            cur = ordered[-1].points_mm[-1]
    return out, cur


def order_by_color_then_distance(blocks: list[StitchBlock],
                                  start: Point = (0.0, 0.0),
                                  z_order_by_element: dict[str, int] | None = None
                                  ) -> list[StitchBlock]:
    """Group blocks by color (fills first, outlines last -- see
    color_sew_order), and within a color sew one element at a time
    (underlay, then top stitching, then border), choosing the next
    element by proximity among those the layer order leaves free.

    z_order_by_element (element_id -> layer index, lower sews first --
    see Region.z_order and the manual-review workflow's per-region
    layer override in src/review/corrections.py) is a hard constraint
    between elements of one color: a lower layer always sews before a
    higher one. Elements on the same layer are free, and are taken
    nearest-first. Raster input puts every region of a color on the
    same layer (same-color raster regions can't overlap, so there is
    nothing to layer), which is what lets a word's letters sew across
    in reading order instead of contour-discovery order; an explicit
    z_order override moves one region ahead of or behind its peers.
    """
    blocks = [b for b in blocks if not b.is_empty()]
    z = z_order_by_element or {}

    result: list[StitchBlock] = []
    cur = start
    for color in color_sew_order(blocks):
        by_element: dict[str, list[StitchBlock]] = {}
        for b in blocks:
            if b.color_index == color:
                by_element.setdefault(b.element_id, []).append(b)

        remaining = list(by_element)
        while remaining:
            lowest = min(z.get(e, 0) for e in remaining)
            candidates = [e for e in remaining if z.get(e, 0) == lowest]
            nearest = min(candidates,
                          key=lambda e: (_entry_distance(by_element[e], cur),
                                         candidates.index(e)))
            remaining.remove(nearest)
            ordered, cur = _order_element(by_element[nearest], cur)
            result.extend(ordered)
    return result
