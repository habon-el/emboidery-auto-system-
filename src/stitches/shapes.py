"""Hand-built shapes for the M0 spine demo (no CV/image input involved)."""
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

from src.params.presets import FabricPreset
from src.stitches.fill import generate_fill
from src.stitches.model import FILL, UNDERLAY_RUN, StitchBlock, ThreadColor
from src.stitches.underlay import fill_underlay

SHAPES = {"circle"}


def _circle_polygon(radius_mm: float = 15.0) -> Polygon:
    return ShapelyPoint(0.0, 0.0).buffer(radius_mm, quad_segs=64)


def build_demo_blocks(shape: str, fabric: FabricPreset, angle_deg: float = 45.0
                       ) -> list[StitchBlock]:
    if shape not in SHAPES:
        raise ValueError(f"Unknown demo shape {shape!r}. Available: {sorted(SHAPES)}")

    polygon = _circle_polygon()

    underlay_pts = fill_underlay(
        polygon, fabric.fill_underlay_inset_mm, fabric.running_stitch_length_mm)
    fill_runs = generate_fill(
        polygon, angle_deg, fabric.fill_row_spacing_mm, fabric.fill_stitch_length_mm)

    blocks = [StitchBlock(UNDERLAY_RUN, underlay_pts, color_index=0, element_id=shape)]
    blocks.extend(StitchBlock(FILL, run, color_index=0, element_id=shape) for run in fill_runs)
    return blocks


DEMO_THREAD = ThreadColor(name="demo red", rgb=(196, 30, 40))
