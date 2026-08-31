"""Turn one classified Region into its underlay + top-stitch StitchBlocks."""
from src.params.classify import Classification
from src.params.presets import FabricPreset
from src.regions.model import Region
from src.stitches.border import build_border_blocks
from src.stitches.fill import generate_fill
from src.stitches.model import (FILL, RUNNING, SATIN, UNDERLAY_RUN,
                                 UNDERLAY_SATIN, StitchBlock)
from src.stitches.running import resample_path
from src.stitches.satin import generate_satin
from src.stitches.underlay import fill_underlay, satin_centerline_underlay


def build_blocks_for_region(region: Region, classification: Classification,
                             fabric: FabricPreset, border_width_mm: float = 0.0
                             ) -> list[StitchBlock]:
    color, eid = region.color_index, region.region_id
    medial = classification.medial

    if classification.stitch_type == RUNNING:
        pts = resample_path(medial.path_points_mm, fabric.running_stitch_length_mm)
        return [StitchBlock(RUNNING, pts, color, eid)]

    if classification.stitch_type == SATIN:
        rail_a, rail_b = medial.rails()
        blocks = []
        if fabric.satin_underlay:
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
    underlay_pts = fill_underlay(
        region.polygon, fabric.fill_underlay_inset_mm, fabric.running_stitch_length_mm)
    fill_runs = generate_fill(
        region.polygon, classification.angle_deg,
        fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm)
    blocks = [StitchBlock(UNDERLAY_RUN, underlay_pts, color, eid)]
    blocks.extend(StitchBlock(FILL, run, color, eid) for run in fill_runs)
    if border_width_mm > 0:
        blocks.extend(build_border_blocks(
            region.polygon, classification.angle_deg, border_width_mm,
            fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm, color, eid))
    return blocks
