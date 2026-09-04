"""Rough run-time estimate for a stitch plan.

Conservative, not machine-calibrated: real run time depends on the
specific machine's max speed, curve slow-down, hooping changes, and
thread trims. This gives a ballpark for planning, using typical
single-head home/light-commercial embroidery speeds.
"""
from src.stitches.model import StitchPlan

STITCHES_PER_MINUTE = 700.0
SECONDS_PER_COLOR_CHANGE = 8.0
# A trim is the slow part of a sew-out: the machine decelerates, cuts,
# and re-starts. Without this a design's trim count never showed up in
# its run time, so a badly-pathed design looked as fast as a good one.
SECONDS_PER_TRIM = 3.0


def estimate_runtime_seconds(plan: StitchPlan, trim_count: int = 0) -> float:
    """trim_count is how many times the trimmer fires, counted from the
    exported command stream (src/preview/stitch_export.py or
    src/validate/audit.py) -- the plan alone can't know, since the
    trim decision is made at export time (src/pathing/route.py)."""
    stitch_seconds = plan.stitch_count() / STITCHES_PER_MINUTE * 60.0

    color_changes = 0
    last_color = None
    for block in plan.blocks:
        if block.is_empty():
            continue
        if last_color is not None and block.color_index != last_color:
            color_changes += 1
        last_color = block.color_index

    return (stitch_seconds + color_changes * SECONDS_PER_COLOR_CHANGE
            + trim_count * SECONDS_PER_TRIM)


def format_runtime(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs:02d}s"
