"""Travel routing thresholds: when a gap between the end of one block and
the start of the next needs a JUMP (and, if the gap is large enough, a
TRIM so the machine doesn't drag a long thread across the design)."""

# A normal stitch is a couple mm; anything wider than this between blocks
# is deliberate travel, not stitching, so we jump instead of sewing it.
JUMP_THRESHOLD_MM = 2.0

# Beyond this, sewing over the gap unsewn/uncut would leave a visible
# thread float, so cut it.
TRIM_THRESHOLD_MM = 6.0


def needs_jump(gap_mm: float) -> bool:
    return gap_mm > JUMP_THRESHOLD_MM


def needs_trim(gap_mm: float) -> bool:
    return gap_mm > TRIM_THRESHOLD_MM
