"""Render a StitchPlan to a stitch-level preview PNG.

This draws the actual needle-point path (not a filled vector shape), so
what you see is what the machine would sew: every stitch as a short
segment, with a small dot at each needle penetration. Rendered at a
supersampled resolution and downscaled for anti-aliased, crisper edges
than drawing directly at the target size would give.
"""
from PIL import Image, ImageDraw

from src.stitches.model import StitchPlan

DEFAULT_PX_PER_MM = 12
DEFAULT_MARGIN_MM = 5.0
SUPERSAMPLE = 3


def render_preview(plan: StitchPlan, out_path: str,
                    px_per_mm: float = DEFAULT_PX_PER_MM,
                    margin_mm: float = DEFAULT_MARGIN_MM) -> str:
    render_px_per_mm = px_per_mm * SUPERSAMPLE
    minx, miny, maxx, maxy = plan.bounds_mm()
    width = max(10, int((maxx - minx + 2 * margin_mm) * render_px_per_mm))
    height = max(10, int((maxy - miny + 2 * margin_mm) * render_px_per_mm))
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    def to_px(pt: tuple[float, float]) -> tuple[float, float]:
        x, y = pt
        return ((x - minx + margin_mm) * render_px_per_mm,
                 (y - miny + margin_mm) * render_px_per_mm)

    line_width = max(1, round(0.18 * render_px_per_mm / SUPERSAMPLE) * SUPERSAMPLE)
    dot_radius = line_width * 0.6

    for block in plan.blocks:
        if block.color_index < len(plan.colors):
            rgb = plan.colors[block.color_index].rgb
        else:
            rgb = (0, 0, 0)
        pts = [to_px(p) for p in block.points_mm]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            draw.line([(x0, y0), (x1, y1)], fill=rgb, width=line_width)
        for x, y in pts:
            draw.ellipse([x - dot_radius, y - dot_radius,
                          x + dot_radius, y + dot_radius], fill=rgb)

    final_size = (max(1, width // SUPERSAMPLE), max(1, height // SUPERSAMPLE))
    img = img.resize(final_size, Image.LANCZOS)
    img.save(out_path)
    return out_path
