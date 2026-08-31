"""Validation checks run on the final stitch plan (Section 6/M4): satin
regions redirected to fill for being too wide, density outside a safe
range for the fabric, suspiciously large travel jumps (a proxy for
"orphan jump" pathing bugs), and design size vs a common hoop. These are
warnings surfaced to the user, not silent -- Section 9's "rejection is a
feature" extends to flagging a shaky result, not just refusing bad input.
"""
import math

from src.params.classify import Classification
from src.params.presets import FabricPreset
from src.regions.model import Region
from src.stitches.model import StitchPlan

MAX_HOOP_MM = 200.0
MIN_FILL_ROW_SPACING_MM = 0.25
MAX_FILL_ROW_SPACING_MM = 1.0
SUSPICIOUS_JUMP_MM = 50.0


def check_satin_redirects(classifications: list[tuple[Region, Classification]],
                           fabric: FabricPreset) -> list[str]:
    return [
        f"Region {region.region_id} looks satin-shaped but exceeds the "
        f"{fabric.satin_max_width_mm}mm max satin width for '{fabric.name}' "
        f"-- stitched as fill instead."
        for region, c in classifications if c.redirected_from_satin
    ]


def check_hoop_size(plan: StitchPlan) -> list[str]:
    minx, miny, maxx, maxy = plan.bounds_mm()
    w, h = maxx - minx, maxy - miny
    if w > MAX_HOOP_MM or h > MAX_HOOP_MM:
        return [f"Design is {w:.0f}x{h:.0f}mm, larger than a common "
                f"{MAX_HOOP_MM:.0f}mm hoop -- check it fits your hoop "
                f"before sewing."]
    return []


def check_density(fabric: FabricPreset) -> list[str]:
    warnings = []
    if fabric.fill_row_spacing_mm < MIN_FILL_ROW_SPACING_MM:
        warnings.append(
            f"Fill row spacing {fabric.fill_row_spacing_mm}mm is very "
            f"tight for '{fabric.name}' -- risk of thread breakage or "
            f"fabric damage.")
    if fabric.fill_row_spacing_mm > MAX_FILL_ROW_SPACING_MM:
        warnings.append(
            f"Fill row spacing {fabric.fill_row_spacing_mm}mm is loose "
            f"for '{fabric.name}' -- fill may look sparse/gappy.")
    return warnings


def check_suspicious_jumps(plan: StitchPlan) -> list[str]:
    warnings = []
    cur = None
    for block in plan.blocks:
        if block.is_empty():
            continue
        start = block.points_mm[0]
        if cur is not None:
            gap = math.hypot(start[0] - cur[0], start[1] - cur[1])
            if gap > SUSPICIOUS_JUMP_MM:
                warnings.append(
                    f"Unusually large jump ({gap:.0f}mm) before element "
                    f"'{block.element_id}' ({block.stitch_type}) -- check "
                    f"pathing/element placement.")
        cur = block.points_mm[-1]
    return warnings


def validate_plan(plan: StitchPlan, fabric: FabricPreset,
                   classifications: list[tuple[Region, Classification]]
                   ) -> list[str]:
    return (check_satin_redirects(classifications, fabric)
            + check_hoop_size(plan)
            + check_density(fabric)
            + check_suspicious_jumps(plan))
