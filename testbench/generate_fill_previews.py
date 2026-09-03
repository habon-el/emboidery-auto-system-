"""Generate a small, real, rendered stitch swatch per fill style
(src/stitches/model.py's FILL_STYLES) for the web UI's fill-style
picker -- run once:

    python -m testbench.generate_fill_previews

These aren't hand-drawn mockups: each swatch is the actual output of
generate_fill()/generate_contour_fill()/generate_crosshatch_fill()/
generate_brick_fill() on a fixed rounded-rectangle sample shape, run
through the same src/preview/render.py the real digitize pipeline uses
-- so what a human (or a customer) sees when picking a style is
literally true to what that style stitches, not an illustration of it.
The rounded corners on the sample shape are deliberate: they're what
makes Contour's edge-hugging rings visibly different from Tatami's
straight rows in a small thumbnail.
"""
import os

from shapely.geometry import box

from src.preview.render import render_preview
from src.stitches.fill import (generate_brick_fill, generate_contour_fill,
                                generate_crosshatch_fill, generate_fill)
from src.stitches.model import (FILL, FILL_BRICK, FILL_CONTOUR,
                                 FILL_CROSSHATCH, FILL_TATAMI, StitchBlock,
                                 StitchPlan, ThreadColor)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "webapp", "static", "fill_previews")

# Deliberately coarser than a real fabric preset's actual row spacing
# (twill's is 0.4mm) -- these are illustrative swatches meant to show
# the *pattern* at a glance, not a literal density preview, and a real
# 0.4mm spacing packs so many rows into a small thumbnail that Tatami
# and Brick become visually indistinguishable (their difference is only
# in where each row's needle points fall, not the rows themselves).
ROW_SPACING_MM = 1.1
STITCH_LENGTH_MM = 3.2
ANGLE_DEG = 0.0
SWATCH_COLOR = (28, 90, 170)  # matches the site's own accent blue


def _sample_shape():
    """A rounded rectangle, ~20x14mm -- straight edges plus rounded
    corners, so Contour's ring-following behavior reads clearly against
    Tatami/Brick's straight rows even at thumbnail size."""
    return box(-7, -4, 7, 4).buffer(3, quad_segs=16)


def _render(name: str, runs: list[list]) -> None:
    blocks = [StitchBlock(FILL, run, color_index=0) for run in runs]
    plan = StitchPlan(blocks=blocks, colors=[ThreadColor(name="preview", rgb=SWATCH_COLOR)])
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{name}.png")
    render_preview(plan, out_path, px_per_mm=16, margin_mm=2.0)
    print(f"wrote {out_path}")


def main():
    shape = _sample_shape()
    _render(FILL_TATAMI, generate_fill(shape, ANGLE_DEG, ROW_SPACING_MM, STITCH_LENGTH_MM))
    _render(FILL_CONTOUR, generate_contour_fill(shape, ROW_SPACING_MM, STITCH_LENGTH_MM))
    _render(FILL_CROSSHATCH, generate_crosshatch_fill(shape, ANGLE_DEG, ROW_SPACING_MM, STITCH_LENGTH_MM))
    _render(FILL_BRICK, generate_brick_fill(shape, ANGLE_DEG, ROW_SPACING_MM, STITCH_LENGTH_MM))


if __name__ == "__main__":
    main()
