"""Turn one classified Region into its underlay + top-stitch StitchBlocks."""
from src.params.classify import Classification
from src.params.presets import FabricPreset
from src.regions.model import Region
from src.stitches.border import build_border_blocks
from src.stitches.fill import (generate_brick_fill, generate_contour_fill,
                                generate_crosshatch_fill, generate_fill)
from src.stitches.model import (DEFAULT_FILL_STYLE, FILL, FILL_BRICK,
                                 FILL_CONTOUR, FILL_CROSSHATCH, FILL_TATAMI,
                                 RUNNING, SATIN, UNDERLAY_RUN, UNDERLAY_SATIN,
                                 StitchBlock)
from src.stitches.running import resample_path
from src.stitches.satin import generate_satin
from src.stitches.underlay import fill_underlay, satin_centerline_underlay


def build_blocks_for_region(region: Region, classification: Classification,
                             fabric: FabricPreset, border_width_mm: float = 0.0,
                             include_underlay: bool = True,
                             fill_style: str = DEFAULT_FILL_STYLE
                             ) -> list[StitchBlock]:
    """include_underlay=False skips the underlay pass entirely -- used
    by the manual-review correction workflow (src/review/corrections.py)
    when a human has explicitly turned underlay off for one region;
    every other caller leaves it at the default (on).

    fill_style (src/stitches/model.py's FILL_STYLES) only affects
    FILL-type regions -- a human (or customer) choice of which real
    fill pattern to stitch, not a measurement the classifier decides on
    its own; see src/stitches/fill.py for what each style actually does."""
    color, eid = region.color_index, region.region_id
    medial = classification.medial

    if classification.stitch_type == RUNNING:
        pts = resample_path(medial.path_points_mm, fabric.running_stitch_length_mm)
        return [StitchBlock(RUNNING, pts, color, eid)]

    if classification.stitch_type == SATIN:
        rail_a, rail_b = medial.rails()
        blocks = []
        if include_underlay and fabric.satin_underlay:
            underlay_pts = satin_centerline_underlay(
                rail_a, rail_b, fabric.running_stitch_length_mm)
            blocks.append(StitchBlock(UNDERLAY_SATIN, underlay_pts, color, eid))
        satin_pts = generate_satin(
            rail_a, rail_b, fabric.satin_density_mm, fabric.pull_compensation_mm)
        blocks.append(StitchBlock(SATIN, satin_pts, color, eid))
        # Satin columns already have a well-defined, dense edge -- a
        # border ring only applies to fill regions (a badge's outer
        # shape, a blob of color), where it visibly adds definition.
        return blocks

    # FILL
    blocks = []
    if include_underlay:
        underlay_pts = fill_underlay(
            region.polygon, fabric.fill_underlay_inset_mm, fabric.running_stitch_length_mm)
        blocks.append(StitchBlock(UNDERLAY_RUN, underlay_pts, color, eid))

    if fill_style == FILL_CONTOUR:
        fill_runs = generate_contour_fill(
            region.polygon, fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm)
    elif fill_style == FILL_CROSSHATCH:
        fill_runs = generate_crosshatch_fill(
            region.polygon, classification.angle_deg,
            fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm)
    elif fill_style == FILL_BRICK:
        fill_runs = generate_brick_fill(
            region.polygon, classification.angle_deg,
            fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm)
    else:  # FILL_TATAMI, and any unrecognized value falls back to it
        fill_runs = generate_fill(
            region.polygon, classification.angle_deg,
            fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm)

    if region.texture_zone and fill_style in (FILL_TATAMI, FILL_BRICK):
        # A second pass at 90 degrees cross-hatches the fill, giving a
        # texture-flagged region (src/regions/texture.py) a visually
        # distinct look instead of sewing it exactly like a flat block.
        # Wider spacing on this second pass keeps total density from
        # roughly doubling -- see the fabric-density "don't over-stitch"
        # notes in src/params/presets.py. Only for the two angle-based
        # styles: Contour has no single angle to add 90 degrees to, and
        # Cross-Hatch is already two-direction on its own.
        fill_runs = fill_runs + generate_fill(
            region.polygon, classification.angle_deg + 90,
            fabric.fill_row_spacing_mm * 1.6, fabric.fill_stitch_length_mm)
    blocks.extend(StitchBlock(FILL, run, color, eid) for run in fill_runs)
    if border_width_mm > 0:
        blocks.extend(build_border_blocks(
            region.polygon, classification.angle_deg, border_width_mm,
            fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm, color, eid))
    return blocks
