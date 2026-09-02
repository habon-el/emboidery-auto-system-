"""Full digitize pipeline (M1-M4): input -> regions -> classify -> stitch
generation -> pathing -> validate -> export + preview. This is what the
`digitize` CLI subcommand and the web UI (webapp/app.py) both call."""
from src.params.classify import classify_region
from src.params.presets import get_preset
from src.pathing.order import order_by_color_then_distance
from src.regions.pipeline import load_and_extract_regions
from src.regions.scale import scale_region_set
from src.regions.scope import apply_findings, check_min_feature_size
from src.report import write_and_report
from src.stitches.build import build_blocks_for_region
from src.stitches.model import FILL, RUNNING, SATIN, StitchBlock, StitchPlan
from src.validate.checks import validate_plan

# A region classified with confidence below this is close enough to a
# decision boundary (or, for fill, close enough to the satin thresholds)
# that it's worth a human glance -- surfaced as both a warning and a
# per-region flag, not silently accepted. See src/params/classify.py's
# Classification.confidence docstring for how this number is computed.
LOW_CONFIDENCE_THRESHOLD = 0.4


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

    if target_width_mm or target_height_mm:
        # The pre-scale minimum-cap-height check (inside
        # load_and_extract_regions) only guarantees the *source* was in
        # scope -- shrinking it afterward via --width-mm/--height-mm can
        # take otherwise-fine text below the stitchable minimum with
        # nothing else re-checking it. Re-run the same check on the
        # scaled geometry so a shrink-to-too-small still gets caught
        # (or forced-past-with-a-warning, exactly like the original check).
        heights_mm = [r.polygon.bounds[3] - r.polygon.bounds[1] for r in region_set.regions]
        apply_findings([check_min_feature_size(heights_mm)], warnings, strict=not force)

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

    regions_meta = []
    counts = {FILL: 0, SATIN: 0, RUNNING: 0}
    texture_zone_count = 0
    needs_review_count = 0
    for region, classification in classifications:
        counts[classification.stitch_type] = counts.get(classification.stitch_type, 0) + 1
        if region.texture_zone:
            texture_zone_count += 1
        needs_review = classification.confidence < LOW_CONFIDENCE_THRESHOLD
        if needs_review:
            needs_review_count += 1
            warnings.append(
                f"Region '{region.region_id}' ({classification.stitch_type}) "
                f"classified with low confidence ({classification.confidence:.2f}) "
                f"-- {classification.reason} Worth a manual look.")
        color = region_set.colors[region.color_index] if region.color_index < len(region_set.colors) else None
        regions_meta.append({
            "id": region.region_id,
            "color_index": region.color_index,
            "z_order": region.z_order,
            "stitch_type": classification.stitch_type,
            "reason": classification.reason,
            "confidence": round(classification.confidence, 2),
            "needs_review": needs_review,
            "redirected_from_satin": classification.redirected_from_satin,
            "texture_zone": region.texture_zone,
            "texture_confidence": region.texture_confidence,
            "thread_name": color.matched_thread_name if color else "",
            "thread_code": color.matched_thread_code if color else "",
            "thread_delta_e": color.thread_delta_e if color else 0.0,
            "thread_rgb_hex": ("#%02x%02x%02x" % color.rgb) if color else "#888888",
        })

    summary = {
        "visual_colors_detected": region_set.raw_color_count,
        "thread_colors_selected": len(region_set.colors),
        "filled_regions": counts.get(FILL, 0),
        "satin_columns": counts.get(SATIN, 0),
        "running_stitch_details": counts.get(RUNNING, 0),
        "texture_zones": texture_zone_count,
        "warnings_requiring_review": needs_review_count,
    }

    for w in warnings:
        print(f"Warning: {w}")

    result = write_and_report(plan, out_stem)
    result["warnings"] = warnings
    result["summary"] = summary
    result["regions"] = regions_meta
    return result
