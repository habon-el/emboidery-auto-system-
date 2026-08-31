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
    for block in plan.blocks:
        if block.is_empty():
            continue

        if cur_color is not None and block.color_index != cur_color:
            p.add_stitch_absolute(pe.TRIM, *mm_to_units_pt(cur_pos))
            p.add_stitch_absolute(pe.COLOR_CHANGE, *mm_to_units_pt(cur_pos))
        cur_color = block.color_index

        start = block.points_mm[0]
        if cur_pos is not None:
            gap = math.hypot(start[0] - cur_pos[0], start[1] - cur_pos[1])
            if needs_trim(gap):
                p.add_stitch_absolute(pe.TRIM, *mm_to_units_pt(cur_pos))
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))
            elif needs_jump(gap):
                p.add_stitch_absolute(pe.JUMP, *mm_to_units_pt(start))

        for point in block.points_mm:
            p.add_stitch_absolute(pe.STITCH, *mm_to_units_pt(point))
        cur_pos = block.points_mm[-1]

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
