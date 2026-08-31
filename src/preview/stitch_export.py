"""Export a StitchPlan as JSON for the web UI's Stitch Player.

This walks the literal pyembroidery command stream (STITCH/JUMP/TRIM/
COLOR_CHANGE) rather than re-deriving it -- so playback shows exactly
what will be sewn, not an approximation. Mirrors the "Simulate and
Audit Production Sequence" step real digitizing software provides
(step-by-step playback to verify stitch order and spot missing
underlay before sending a file to the machine).
"""
import json

import pyembroidery as pe

from src.io_.export import stitch_plan_to_pattern
from src.io_.units import UNITS_PER_MM
from src.stitches.model import StitchPlan

_KIND_BY_CODE = {
    pe.STITCH: "stitch",
    pe.JUMP: "jump",
    pe.TRIM: "trim",
    pe.COLOR_CHANGE: "color_change",
    pe.END: "end",
}


def export_stitch_json(plan: StitchPlan, out_path: str) -> str:
    pattern = stitch_plan_to_pattern(plan)
    colors_hex = [t.hex_color() for t in pattern.threadlist] or ["#000000"]

    steps = []
    for x, y, cmd in pattern.stitches:
        kind = _KIND_BY_CODE.get(cmd & pe.COMMAND_MASK, "other")
        steps.append({
            "x": round(x / UNITS_PER_MM, 3),
            "y": round(y / UNITS_PER_MM, 3),
            "t": kind,
        })

    with open(out_path, "w") as f:
        json.dump({"colors": colors_hex, "steps": steps}, f)
    return out_path
