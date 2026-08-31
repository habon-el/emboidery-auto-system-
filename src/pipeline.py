"""Full digitize pipeline (M1-M4): input -> regions -> classify -> stitch
generation -> pathing -> validate -> export + preview. This is what the
`digitize` CLI subcommand and the web UI (webapp/app.py) both call."""
from src.params.classify import classify_region
from src.params.presets import get_preset
from src.pathing.order import order_by_color_then_distance
from src.regions.pipeline import load_and_extract_regions
from src.regions.scale import scale_region_set
from src.report import write_and_report
from src.stitches.build import build_blocks_for_region
from src.stitches.model import StitchBlock, StitchPlan
from src.validate.checks import validate_plan


def digitize_image(input_path: str, fabric_name: str, out_stem: str,
                    border_width_mm: float = 0.0, force: bool = False,
                    target_width_mm: float | None = None,
                    target_height_mm: float | None = None) -> dict:
    """Runs the full pipeline and returns a dict: the write_and_report()
    result (dst/pes/preview paths, stitch_count, runtime) plus a
    "warnings" list of every non-fatal notice raised along the way.
    Raises DigitizeScopeError if the input is out of scope, unless
    force=True downgrades that rejection to a loud warning instead (see
    src/regions/scope.py's apply_findings docstring for what this does
    and doesn't bypass).

    target_width_mm/target_height_mm resize the design to a finished
    output size before stitch generation -- give one to scale uniformly
    (the other axis follows the aspect ratio), or both for an exact fit
    (which distorts the design if the aspect ratio doesn't match; you'll
    get a warning). Mirrors the "resize to finished dimensions" step
    real digitizing workflows do first, so density/stitch-length are
    calculated for the actual output size, not the source image's
    incidental resolution.
    """
    fabric = get_preset(fabric_name)

    region_set = load_and_extract_regions(input_path, strict=not force)
    region_set, scale_warnings = scale_region_set(region_set, target_width_mm, target_height_mm)
    warnings: list[str] = list(region_set.warnings) + scale_warnings

    all_blocks: list[StitchBlock] = []
    classifications = []
    for region in region_set.regions:
        classification = classify_region(region, fabric)
        classifications.append((region, classification))
        blocks = build_blocks_for_region(region, classification, fabric, border_width_mm)
        for b in blocks:
            if b.is_empty():
                warnings.append(f"element '{region.region_id}' ({b.stitch_type}) "
                                 f"produced no stitches -- skipped.")
        all_blocks.extend(blocks)

    ordered = order_by_color_then_distance(all_blocks)
    plan = StitchPlan(blocks=ordered, colors=region_set.colors)

    warnings.extend(validate_plan(plan, fabric, classifications))
    for w in warnings:
        print(f"Warning: {w}")

    result = write_and_report(plan, out_stem)
    result["warnings"] = warnings
    return result
