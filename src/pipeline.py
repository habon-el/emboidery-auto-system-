"""Full digitize pipeline (M1-M4, plus the Multi-Region Illustration
Digitization manual-review workflow): input -> regions -> classify ->
stitch generation -> pathing -> validate -> export + preview. This is
what the `digitize` CLI subcommand and the web UI (webapp/app.py) call
for a fresh upload; src/review/rebuild.py calls build_and_export()
directly to redo the same work with per-region corrections applied.
"""
from dataclasses import replace

from src.params.classify import classify_region
from src.params.presets import get_preset
from src.params.thread_palette import match_thread
from src.pathing.order import order_by_color_then_distance
from src.preview.render import DEFAULT_MARGIN_MM
from src.regions.model import RegionSet
from src.regions.pipeline import load_and_extract_regions
from src.regions.scale import scale_region_set
from src.regions.scope import apply_findings, check_min_feature_size
from src.report import write_and_report
from src.review.corrections import RegionOverride, resolve_override
from src.stitches.build import build_blocks_for_region
from src.stitches.model import (FILL, RUNNING, SATIN, StitchBlock, StitchPlan,
                                 ThreadColor)
from src.validate.checks import validate_plan

# A region classified with confidence below this is close enough to a
# decision boundary (or, for fill, close enough to the satin thresholds)
# that it's worth a human glance -- surfaced as both a warning and a
# per-region flag, not silently accepted. See src/params/classify.py's
# Classification.confidence docstring for how this number is computed.
LOW_CONFIDENCE_THRESHOLD = 0.4


def load_scaled_region_set(input_path: str, force: bool,
                            target_width_mm: float | None,
                            target_height_mm: float | None
                            ) -> tuple[RegionSet, list[str]]:
    """Region extraction + resize + the post-scale minimum-feature-size
    re-check, shared by a fresh digitize (digitize_image below) and a
    corrected rebuild (src/review/rebuild.py) so the two can never
    silently diverge in how they load the same input."""
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

    return region_set, warnings


def digitize_image(input_path: str, fabric_name: str, out_stem: str,
                    border_width_mm: float = 0.0, force: bool = False,
                    target_width_mm: float | None = None,
                    target_height_mm: float | None = None) -> dict:
    """Runs the full pipeline and returns a dict: the write_and_report()
    result (dst/pes/preview paths, stitch_count, runtime) plus a
    "warnings" list, an analysis "summary", and per-region "regions"
    metadata (see build_and_export's docstring for their shape).
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
    region_set, warnings = load_scaled_region_set(
        input_path, force, target_width_mm, target_height_mm)
    return build_and_export(region_set, fabric, out_stem, border_width_mm, warnings)


def build_and_export(region_set: RegionSet, fabric, out_stem: str,
                      border_width_mm: float, warnings: list[str],
                      corrections: dict[str, RegionOverride] | None = None
                      ) -> dict:
    """Classification, per-region correction overrides, stitch
    generation, pathing, validation, export, and the analysis summary --
    shared by a fresh digitize (digitize_image above) and a corrected
    rebuild (src/review/rebuild.py) so a correction round-trip can't
    silently behave differently from a fresh run.

    corrections maps region_id -> RegionOverride (src/review/corrections.py)
    for the subset of regions a human has manually corrected; every
    other region is built from classify_region()'s own decision,
    unchanged -- see src/review/rebuild.py's docstring for why re-running
    classification from scratch is safe (determinism) rather than
    needing to cache/restore each region's prior state.

    Returns write_and_report()'s dict plus:
      "warnings": list[str]
      "summary": {visual_colors_detected, thread_colors_selected,
                  filled_regions, satin_columns, running_stitch_details,
                  texture_zones, warnings_requiring_review}
      "regions": [{id, color_index, z_order, stitch_type, reason,
                   confidence, needs_review, redirected_from_satin,
                   texture_zone, texture_confidence, thread_name,
                   thread_code, thread_delta_e, thread_rgb_hex,
                   corrected, bbox_pct}, ...]
      "corrections_applied": sorted list of region_ids that had a
        (non-no-op) correction applied this build.
    """
    corrections = corrections or {}

    all_blocks: list[StitchBlock] = []
    classifications = []
    z_order_by_element: dict[str, int] = {}
    extra_colors: list[ThreadColor] = []
    color_override_index: dict[str, int] = {}
    next_color_index = len(region_set.colors)
    applied_corrections: list[str] = []

    for region in region_set.regions:
        classification = classify_region(region, fabric)
        override = corrections.get(region.region_id)
        eff_classification, eff_fabric, eff_border, include_underlay = resolve_override(
            classification, fabric, border_width_mm, override)
        classifications.append((region, eff_classification))

        z_order_by_element[region.region_id] = (
            override.z_order if (override and override.z_order is not None) else region.z_order)

        blocks = build_blocks_for_region(
            region, eff_classification, eff_fabric, eff_border, include_underlay)

        if override and override.thread_rgb is not None:
            new_index = next_color_index
            next_color_index += 1
            match = match_thread(override.thread_rgb)
            extra_colors.append(ThreadColor(
                name=f"custom ({region.region_id})", rgb=override.thread_rgb,
                matched_thread_name=match.name, matched_thread_code=match.code,
                thread_delta_e=match.delta_e))
            blocks = [replace(b, color_index=new_index) for b in blocks]
            color_override_index[region.region_id] = new_index

        if override is not None and not override.is_noop():
            applied_corrections.append(region.region_id)

        for b in blocks:
            if b.is_empty():
                warnings.append(f"element '{region.region_id}' ({b.stitch_type}) "
                                 f"produced no stitches -- skipped.")
        all_blocks.extend(blocks)

    ordered = order_by_color_then_distance(all_blocks, z_order_by_element=z_order_by_element)
    all_colors = region_set.colors + extra_colors
    plan = StitchPlan(blocks=ordered, colors=all_colors)

    warnings.extend(validate_plan(plan, fabric, classifications))

    minx, miny, maxx, maxy = plan.bounds_mm()
    full_w = max(1e-6, (maxx - minx) + 2 * DEFAULT_MARGIN_MM)
    full_h = max(1e-6, (maxy - miny) + 2 * DEFAULT_MARGIN_MM)
    origin_x, origin_y = minx - DEFAULT_MARGIN_MM, miny - DEFAULT_MARGIN_MM

    def _bbox_pct(region) -> dict:
        rminx, rminy, rmaxx, rmaxy = region.polygon.bounds
        return {
            "left": round(max(0.0, min(100.0, (rminx - origin_x) / full_w * 100)), 2),
            "top": round(max(0.0, min(100.0, (rminy - origin_y) / full_h * 100)), 2),
            "width": round(max(0.0, min(100.0, (rmaxx - rminx) / full_w * 100)), 2),
            "height": round(max(0.0, min(100.0, (rmaxy - rminy) / full_h * 100)), 2),
        }

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
        color_index = color_override_index.get(region.region_id, region.color_index)
        color = all_colors[color_index] if color_index < len(all_colors) else None
        regions_meta.append({
            "id": region.region_id,
            "color_index": color_index,
            "z_order": z_order_by_element[region.region_id],
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
            "corrected": region.region_id in applied_corrections,
            "bbox_pct": _bbox_pct(region),
        })

    summary = {
        "visual_colors_detected": region_set.raw_color_count,
        "thread_colors_selected": len(all_colors),
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
    result["corrections_applied"] = sorted(applied_corrections)
    return result
