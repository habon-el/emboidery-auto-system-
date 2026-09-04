"""Turn a StitchPlan into a real pyembroidery EmbPattern and write DST/PES.

This is the one place design-space millimetres get converted to
pyembroidery's native 1/10 mm unit, and the one place stitch-plan blocks
turn into actual STITCH/JUMP/TRIM/COLOR_CHANGE commands. No format I/O of
our own -- pyembroidery owns the DST/PES bytes (Section 3/9).
"""
import math
from dataclasses import replace

import pyembroidery as pe

from src.pathing.route import needs_jump, needs_trim
from src.stitches.model import MIN_STITCH_LENGTH_MM, StitchPlan
from .units import mm_to_units, quantize_point_mm

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
# Long enough to survive the 1/10 mm grid a stitch file stores
# coordinates on (src/io_/units.py's quantize_mm): a tie stitch at
# exactly the 0.3mm minimum lands at 0.283mm once a 45-degree
# diagonal's components are snapped to the grid, which is a
# sub-minimum stitch in the delivered file. 0.45mm leaves room for
# the worst case (up to 0.05mm lost per axis) and is still a lock
# stitch, not a visible one.
TIE_STITCH_LENGTH_MM = 0.45


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
    point that's about to be cut. Clamped to that segment's own length
    so the lock stitch never overshoots past the previous real stitch
    point on an already-tiny block -- and no shorter, since every
    segment reaching here is at least the machine minimum (see
    _sewable_points) and a lock stitch under it would itself be the
    thread-break it exists to prevent."""
    unit = _unit_vector(prev_point, cut_point)
    if unit is None:
        return
    seg_len = math.hypot(cut_point[0] - prev_point[0], cut_point[1] - prev_point[1])
    t = min(TIE_STITCH_LENGTH_MM, seg_len)
    if t <= 0:
        return
    ux, uy = unit
    back_point = quantize_point_mm((cut_point[0] - ux * t, cut_point[1] - uy * t))
    if math.hypot(back_point[0] - cut_point[0], back_point[1] - cut_point[1]) < MIN_STITCH_LENGTH_MM:
        return
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
    t = min(TIE_STITCH_LENGTH_MM, seg_len)
    if t <= 0:
        return
    ux, uy = unit
    fwd_point = quantize_point_mm((entry_point[0] + ux * t, entry_point[1] + uy * t))
    if math.hypot(fwd_point[0] - entry_point[0], fwd_point[1] - entry_point[1]) < MIN_STITCH_LENGTH_MM:
        return
    p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(fwd_point))
    p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(entry_point))


def _sewable_points(points: list[tuple[float, float]],
                    continuing_from: tuple[float, float] | None = None
                    ) -> list[tuple[float, float]]:
    """The last line of defence for the machine minimum: drop any
    needle point closer than MIN_STITCH_LENGTH_MM to the one before
    it. Every generator upstream already respects the floor (see
    src/stitches/running.py); this catches the residue -- a satin
    crossing on a column narrower than the floor, a fill row shorter
    than it -- so a file can never leave here with a stitch that jams
    the needle in its own thread. The block's final point is kept in
    preference to the one before it, so a block still ends where it
    should.

    continuing_from is the needle's current position when this block
    sews straight on from the previous one with no jump between them
    (a fill's next row, a satin branch starting where the last one
    ended): the block's own first point is then measured against it
    too, since stitching it again from 0mm away is the same 0mm
    stitch as a duplicate inside a run.

    Points are snapped to the file's own 1/10 mm grid before being
    compared, because that is what the machine will actually run: a
    0.30mm stitch on a diagonal becomes 0.283mm once written, so
    filtering the un-snapped floats let 125 sub-minimum stitches
    through into a file the audit called clean."""
    points = [quantize_point_mm(p) for p in points]
    if continuing_from is not None:
        continuing_from = quantize_point_mm(continuing_from)

    kept: list[tuple[float, float]] = []
    last_needle = continuing_from
    for p in points:
        if last_needle is None or math.hypot(p[0] - last_needle[0], p[1] - last_needle[1]) >= MIN_STITCH_LENGTH_MM - 1e-9:
            kept.append(p)
            last_needle = p
    if not kept:
        return kept
    last = points[-1]
    if kept[-1] != last:
        before = kept[-2] if len(kept) >= 2 else continuing_from
        if before is not None and math.hypot(last[0] - before[0], last[1] - before[1]) >= MIN_STITCH_LENGTH_MM - 1e-9:
            kept[-1] = last
    return kept


def stitch_plan_to_pattern(plan: StitchPlan) -> pe.EmbPattern:
    p = pe.EmbPattern()
    # The file's thread list is read back positionally: each
    # COLOR_CHANGE advances to the next thread. So threads go in in
    # the order the colors actually sew (src/pathing/order.py's
    # color_sew_order puts fills before outlines, which need not be
    # plan.colors order), with any color that never sews appended
    # after so every index still resolves.
    sew_order: list[int] = []
    for block in plan.blocks:
        if not block.is_empty() and block.color_index not in sew_order:
            sew_order.append(block.color_index)
    for idx in sew_order + [i for i in range(len(plan.colors)) if i not in sew_order]:
        color = plan.colors[idx]
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
        block = replace(block, points_mm=_sewable_points(block.points_mm))
        if block.is_empty():
            continue

        # True once this block's transition has actually cut the thread
        # (a color change and/or the distance/force_trim decision below)
        # -- that's what calls for a tie-in at this block's own start.
        # Tracked separately from "a TRIM command was written" so a
        # color-change trim immediately followed by a from-here
        # distance-trim doesn't tie out twice for the same cut.
        trimmed_this_transition = False
        jumped = False

        if cur_color is not None and block.color_index != cur_color:
            _emit_tie_out(p, prev_block_points[-2], prev_block_points[-1])
            p.add_stitch_absolute(pe.TRIM, *mm_to_units_pt(cur_pos))
            p.add_stitch_absolute(pe.COLOR_CHANGE, *mm_to_units_pt(cur_pos))
            trimmed_this_transition = True
        cur_color = block.color_index

        start = block.points_mm[0]
        if cur_pos is not None and trimmed_this_transition:
            # The color change above already cut the thread. The needle
            # still has to get to the new color's first point, and with
            # nothing to drag it does so as a plain jump however short
            # the gap -- never a second TRIM (that double-counted every
            # color change as two trims) and never a stitch (a 1mm
            # "stitch" from the old color's last point would tie the
            # new thread to the wrong place).
            if math.hypot(start[0] - cur_pos[0], start[1] - cur_pos[1]) > 0:
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))
                jumped = True
        elif cur_pos is not None:
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
                _emit_tie_out(p, prev_block_points[-2], prev_block_points[-1])
                p.add_stitch_absolute(pe.TRIM, *mm_to_units_pt(cur_pos))
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))
                trimmed_this_transition = True
                jumped = True
            elif needs_jump(gap):
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))
                jumped = True

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
        elif not jumped and cur_pos is not None:
            # Sewing straight on from the previous block: its first
            # point may coincide with where the needle already is.
            points_to_stitch = _sewable_points(block.points_mm, continuing_from=cur_pos)
            if not points_to_stitch:
                continue

        for point in points_to_stitch:
            p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(point))
        cur_pos = points_to_stitch[-1] if points_to_stitch else block.points_mm[-1]
        prev_block_points = (block.points_mm if len(points_to_stitch) < 2
                             else points_to_stitch)

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
