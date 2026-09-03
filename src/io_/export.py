"""Turn a StitchPlan into a real pyembroidery EmbPattern and write DST/PES.

This is the one place design-space millimetres get converted to
pyembroidery's native 1/10 mm unit, and the one place stitch-plan blocks
turn into actual STITCH/JUMP/TRIM/COLOR_CHANGE commands. No format I/O of
our own -- pyembroidery owns the DST/PES bytes (Section 3/9).
"""
import math

import pyembroidery as pe

from src.pathing.route import needs_jump, needs_trim
from src.stitches.model import StitchPlan
from .units import mm_to_units

# A tie ("lock") stitch: a tiny there-and-back needle penetration right
# at a thread cut, so the trimmed end can't work loose off the machine.
# Real digitizing software's standard practice around every TRIM --see
# the build research's own step 6 diagram (tie-out -> trim -> jump ->
# tie-in) -- and, unlike everything else this pipeline decides, not
# something a design choice or fabric preset should tune away: a cut
# thread end is a cut thread end regardless of fabric. Deliberately the
# simple two-stitch (forward-then-back) lock, not the fancier 3-5
# stitch multi-directional version some packages offer -- upgrade this
# if a real sew-out ever shows it isn't holding.
TIE_STITCH_LENGTH_MM = 0.3


def _unit_vector(p_from: tuple[float, float], p_to: tuple[float, float]
                  ) -> tuple[float, float] | None:
    dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
    length = math.hypot(dx, dy)
    return None if length == 0 else (dx / length, dy / length)


def _emit_tie_out(p: pe.EmbPattern, prev_point: tuple[float, float],
                   cut_point: tuple[float, float]) -> None:
    """A tiny there-and-back stitch right at a cut point, anchoring the
    thread immediately before a TRIM: backtrack a hair along the
    direction stitching was already traveling, then return to the exact
    point that's about to be cut. Clamped to at most half that segment's
    own length so the lock stitch never overshoots past the previous
    real stitch point on an already-tiny block."""
    unit = _unit_vector(prev_point, cut_point)
    if unit is None:
        return
    seg_len = math.hypot(cut_point[0] - prev_point[0], cut_point[1] - prev_point[1])
    t = min(TIE_STITCH_LENGTH_MM, seg_len / 2)
    if t <= 0:
        return
    ux, uy = unit
    back_point = (cut_point[0] - ux * t, cut_point[1] - uy * t)
    p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(back_point))
    p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(cut_point))


def _emit_tie_in(p: pe.EmbPattern, entry_point: tuple[float, float],
                  next_point: tuple[float, float]) -> None:
    """Mirror of _emit_tie_out at the start of a new thread run (right
    after a TRIM+JUMP lands the needle at entry_point): a tiny step
    toward the direction stitching is about to travel, then back to
    entry_point, before the real stitching for this run begins."""
    unit = _unit_vector(entry_point, next_point)
    if unit is None:
        return
    seg_len = math.hypot(next_point[0] - entry_point[0], next_point[1] - entry_point[1])
    t = min(TIE_STITCH_LENGTH_MM, seg_len / 2)
    if t <= 0:
        return
    ux, uy = unit
    fwd_point = (entry_point[0] + ux * t, entry_point[1] + uy * t)
    p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(fwd_point))
    p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(entry_point))


def stitch_plan_to_pattern(plan: StitchPlan) -> pe.EmbPattern:
    p = pe.EmbPattern()
    for color in plan.colors:
        # add_thread(name) tries to parse the string as a color and falls
        # back to black for a plain label like "color 1" -- build a real
        # EmbThread from the actual RGB so the file's color list (and the
        # stitch player, which reads it back) match the preview.
        thread = pe.EmbThread()
        thread.set_color(*color.rgb)
        thread.description = color.name
        p.add_thread(thread)

    cur_color = None
    cur_pos = None
    prev_block_points: list[tuple[float, float]] | None = None
    for block in plan.blocks:
        if block.is_empty():
            continue

        # True once this block's transition has actually cut the thread
        # (a color change and/or the distance/force_trim decision below)
        # -- that's what calls for a tie-in at this block's own start.
        # Tracked separately from "a TRIM command was written" so a
        # color-change trim immediately followed by a from-here
        # distance-trim doesn't tie out twice for the same cut.
        trimmed_this_transition = False

        if cur_color is not None and block.color_index != cur_color:
            _emit_tie_out(p, prev_block_points[-2], prev_block_points[-1])
            p.add_stitch_absolute(pe.TRIM, *mm_to_units_pt(cur_pos))
            p.add_stitch_absolute(pe.COLOR_CHANGE, *mm_to_units_pt(cur_pos))
            trimmed_this_transition = True
        cur_color = block.color_index

        start = block.points_mm[0]
        if cur_pos is not None:
            gap = math.hypot(start[0] - cur_pos[0], start[1] - cur_pos[1])
            # force_trim_before (a manual region correction -- see
            # src/review/corrections.py's force_trim) overrides the
            # automatic distance rule either direction: True cuts here
            # even on a short gap; False suppresses a cut even on a
            # long one (the machine still jumps there, just without
            # trimming first). None (the default) leaves needs_trim's
            # distance rule in charge, unchanged from before.
            should_trim = (block.force_trim_before if block.force_trim_before is not None
                           else needs_trim(gap))
            if should_trim:
                if not trimmed_this_transition:
                    _emit_tie_out(p, prev_block_points[-2], prev_block_points[-1])
                p.add_stitch_absolute(pe.TRIM, *mm_to_units_pt(cur_pos))
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))
                trimmed_this_transition = True
            elif needs_jump(gap):
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))

        # Only a genuine thread cut gets a tie-in -- a plain jump (no
        # trim) is still the same physically continuous thread, so
        # there's nothing to anchor. The block's own first point still
        # gets a real penetration either way: via the tie-in sequence's
        # last stitch when there was a cut, or via the loop below when
        # there wasn't.
        points_to_stitch = block.points_mm
        if trimmed_this_transition:
            _emit_tie_in(p, block.points_mm[0], block.points_mm[1])
            points_to_stitch = block.points_mm[1:]

        for point in points_to_stitch:
            p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(point))
        cur_pos = block.points_mm[-1]
        prev_block_points = block.points_mm

    p.end()
    return p


def mm_to_units_pt(point) -> tuple[float, float]:
    x, y = point
    return (mm_to_units(x), mm_to_units(y))


def write_pattern(plan: StitchPlan, out_stem: str) -> dict[str, str]:
    """Write out_stem.dst and out_stem.pes. Returns paths written."""
    pattern = stitch_plan_to_pattern(plan)
    dst_path = f"{out_stem}.dst"
    pes_path = f"{out_stem}.pes"
    pe.write_dst(pattern, dst_path)
    pe.write_pes(pattern, pes_path)
    return {"dst": dst_path, "pes": pes_path}
