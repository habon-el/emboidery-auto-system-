"""Full digitize pipeline (M1-M4, plus the Multi-Region Illustration
Digitization manual-review workflow): input -> regions -> classify ->
stitch generation -> pathing -> validate -> export + preview. This is
what the `digitize` CLI subcommand and the web UI (webapp/app.py) call
for a fresh upload; src/review/rebuild.py calls build_and_export()
directly to redo the same work with per-region corrections applied.
"""
from dataclasses import replace

from shapely.geometry import Polygon

from src.params.classify import classify_region
from src.params.presets import get_preset
from src.params.thread_palette import match_thread
from src.pathing.order import color_sew_order, order_by_color_then_distance
from src.preview.render import DEFAULT_MARGIN_MM
from src.regions.model import Region, RegionSet
from src.regions.pipeline import load_and_extract_regions
from src.regions.scale import scale_region_set
from src.regions.scope import apply_findings, check_min_feature_size, feature_sizes_mm
from src.report import write_and_report
from src.review.corrections import RegionOverride, resolve_override
from src.stitches.build import build_blocks_for_region
from src.stitches.model import (DEFAULT_FILL_STYLE, FILL, FILL_STYLES, RUNNING,
                                 SATIN, UNIFORM_FILL_ANGLE_DEG, StitchBlock,
                                 StitchPlan, ThreadColor)
from src.validate.audit import audit_plan, format_audit_summary
from src.validate.checks import validate_plan
from src.validate.features import assess_features

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
    has_target_size = bool(target_width_mm or target_height_mm)
    # Skip the check on the *source* image's native size when a target
    # width/height is given -- that native size is frequently just a
    # guess (missing DPI metadata falls back to an assumed 96, see
    # src/io_/load.py), so rejecting on it before the requested resize
    # ever runs would block a perfectly fine finished size for the
    # wrong reason. The real check -- on the actual scaled geometry --
    # always runs below regardless.
    region_set = load_and_extract_regions(
        input_path, strict=not force, check_min_size=not has_target_size)
    region_set, scale_warnings = scale_region_set(region_set, target_width_mm, target_height_mm)
    warnings: list[str] = list(region_set.warnings) + scale_warnings

    if has_target_size:
        # Re-run the same check on the scaled geometry so a shrink-to-
        # too-small (or a source that was too small and the requested
        # size doesn't actually fix it) still gets caught -- or
        # forced-past-with-a-warning, exactly like the original check.
        regions = region_set.regions
        content_height = (max(r.polygon.bounds[3] for r in regions)
                          - min(r.polygon.bounds[1] for r in regions)) if regions else 0.0
        apply_findings([check_min_feature_size(feature_sizes_mm(regions), content_height)],
                       warnings, strict=not force)

    return region_set, warnings


def digitize_image(input_path: str, fabric_name: str, out_stem: str,
                    border_width_mm: float = 0.0, force: bool = False,
                    target_width_mm: float | None = None,
                    target_height_mm: float | None = None,
                    fill_style: str = DEFAULT_FILL_STYLE,
                    fill_angle_deg: float | None = UNIFORM_FILL_ANGLE_DEG) -> dict:
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

    fill_style (src/stitches/model.py's FILL_STYLES) is the *default*
    fill pattern for every FILL-type region in this design -- a human
    (or customer) choice made once at upload time, overridable per
    region afterward in the manual-review workflow. Never decided
    automatically: an unrecognized value is rejected rather than
    silently substituted, on the same principle as an unknown fabric
    preset.

    fill_angle_deg is the design-wide fill *direction* every FILL
    region stitches at -- see src/stitches/model.py's
    UNIFORM_FILL_ANGLE_DEG for why one shared angle is the default and
    what None (per-shape angles) means.
    """
    if fill_style not in FILL_STYLES:
        raise ValueError(f"fill_style must be one of {sorted(FILL_STYLES)}, got {fill_style!r}.")
    fabric = get_preset(fabric_name)
    region_set, warnings = load_scaled_region_set(
        input_path, force, target_width_mm, target_height_mm)
    return build_and_export(region_set, fabric, out_stem, border_width_mm, warnings,
                             default_fill_style=fill_style,
                             default_fill_angle_deg=fill_angle_deg)


def build_and_export(region_set: RegionSet, fabric, out_stem: str,
                      border_width_mm: float, warnings: list[str],
                      corrections: dict[str, RegionOverride] | None = None,
                      default_fill_style: str = DEFAULT_FILL_STYLE,
                      default_fill_angle_deg: float | None = UNIFORM_FILL_ANGLE_DEG
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

    default_fill_style (src/stitches/model.py's FILL_STYLES) is the
    design-wide fill pattern every FILL-type region uses unless its own
    correction overrides it (RegionOverride.fill_style).

    default_fill_angle_deg is the design-wide fill *direction* (see
    src/stitches/model.py's UNIFORM_FILL_ANGLE_DEG): applied to every
    FILL region before per-region corrections, so a region whose own
    correction sets an angle still wins. None keeps each region's own
    medial-axis angle. Satin is untouched either way -- a satin
    column's direction comes from its rails, not from this angle.

    Returns write_and_report()'s dict plus:
      "warnings": list[str]
      "summary": {visual_colors_detected, thread_colors_selected,
                  color_sew_order (thread names, first sewn first),
                  filled_regions, satin_columns, running_stitch_details,
                  texture_zones, warnings_requiring_review}
      "regions": [{id, color_index, z_order, stitch_type, fill_style,
                   angle_deg, reason, confidence, needs_review, redirected_from_satin,
                   texture_zone, texture_confidence, thread_name,
                   thread_code, thread_delta_e, thread_rgb_hex,
                   corrected, dropped, feature_issue, bbox_pct}, ...]
      "corrections_applied": sorted list of region_ids that had a
        (non-no-op) correction applied this build.
      "audit": src/validate/audit.py's SewabilityAudit.to_dict() --
        trims/jumps/stitch-length/density/size-floor measurements plus
        a "problems" list of concrete rejection reasons.
      "feature_issues": src/validate/features.py's FeatureIssue.to_dict()
        per region that cannot render at this size, each with its
        numeric remedies (scale to, drop, drop children). Each region's
        own entry in "regions" carries the message as feature_issue,
        and "dropped" when a correction dropped it.
    """
    corrections = corrections or {}

    all_blocks: list[StitchBlock] = []
    classifications = []
    z_order_by_element: dict[str, int] = {}
    fill_style_by_element: dict[str, str] = {}
    extra_colors: list[ThreadColor] = []
    color_override_index: dict[str, int] = {}
    next_color_index = len(region_set.colors)
    applied_corrections: list[str] = []
    classifications_meta_only: list = []

    # A dropped region (RegionOverride.drop -- a human accepting the
    # small-feature policy's remedy, see src/validate/features.py) is
    # not stitched, and merges into whatever surrounds it: any other
    # region whose hole it sat in has that hole filled before it is
    # classified and built, so the surrounding fill sews straight over
    # where the dropped feature was.
    dropped = [r for r in region_set.regions
               if corrections.get(r.region_id) is not None and corrections[r.region_id].drop]
    regions = [_fill_holes_of_dropped(r, dropped) if dropped else r
               for r in region_set.regions]
    dropped_ids = {r.region_id for r in dropped}

    for region in regions:
        classification = classify_region(region, fabric)
        if region.region_id in dropped_ids:
            # Listed in the region metadata (so review can un-drop it),
            # built as nothing.
            classification = replace(classification, reason="dropped by manual correction.")
            classifications_meta_only.append((region, classification))
            applied_corrections.append(region.region_id)
            z_order_by_element[region.region_id] = region.z_order
            fill_style_by_element[region.region_id] = default_fill_style
            continue
        if default_fill_angle_deg is not None and classification.stitch_type == FILL:
            # One shared direction for every filled region (see
            # src/stitches/model.py's UNIFORM_FILL_ANGLE_DEG). Applied
            # *before* resolve_override so a region whose own correction
            # sets an angle still wins, and only to FILL -- satin takes
            # its direction from its rails, and running stitch follows
            # its own centerline.
            classification = replace(classification, angle_deg=default_fill_angle_deg)
        override = corrections.get(region.region_id)
        eff_classification, eff_fabric, eff_border, eff_fill_style, include_underlay = resolve_override(
            classification, fabric, border_width_mm, default_fill_style, override)
        classifications.append((region, eff_classification))

        z_order_by_element[region.region_id] = (
            override.z_order if (override and override.z_order is not None) else region.z_order)
        fill_style_by_element[region.region_id] = eff_fill_style

        blocks = build_blocks_for_region(
            region, eff_classification, eff_fabric, eff_border, include_underlay, eff_fill_style)

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

    # What cannot render at this size, with numeric remedies -- reported
    # here and in the region metadata, applied only through a human's
    # RegionOverride.drop (src/validate/features.py).
    built_regions = [r for r, _ in classifications]
    content_height = (max(r.polygon.bounds[3] for r in built_regions)
                      - min(r.polygon.bounds[1] for r in built_regions)) if built_regions else 0.0
    feature_issues = assess_features(classifications, content_height, fabric)
    issue_by_region = {issue.region_id: issue for issue in feature_issues}
    if feature_issues:
        warnings.append(
            f"{len(feature_issues)} feature(s) cannot render at this size -- see the "
            f"small-feature report for what to scale or drop.")

    # force_trim (src/review/corrections.py) marks whichever block ends
    # up scheduled *first* for that region -- not necessarily the block
    # that was blocks[0] before pathing, since a region with several
    # same-stage blocks (e.g. multiple fill runs) can have any of them
    # picked first by nearest-neighbor ordering. Doing this after
    # ordering, on the real final sequence, is what makes the forced
    # (or suppressed) trim land exactly at the region's actual start
    # rather than wherever an arbitrarily-marked block happened to land.
    force_trim_by_id = {rid: ov.force_trim for rid, ov in corrections.items()
                         if ov and ov.force_trim is not None}
    if force_trim_by_id:
        already_marked: set[str] = set()
        for i, b in enumerate(ordered):
            if b.element_id in force_trim_by_id and b.element_id not in already_marked:
                ordered[i] = replace(b, force_trim_before=force_trim_by_id[b.element_id])
                already_marked.add(b.element_id)

    all_colors = region_set.colors + extra_colors
    plan = StitchPlan(blocks=ordered, colors=all_colors)

    warnings.extend(validate_plan(plan, fabric, classifications))
    audit = audit_plan(plan, fabric, classifications, fill_style_by_element)

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
    for region, classification in classifications + classifications_meta_only:
        is_dropped = region.region_id in dropped_ids
        if not is_dropped:
            counts[classification.stitch_type] = counts.get(classification.stitch_type, 0) + 1
        if region.texture_zone:
            texture_zone_count += 1
        needs_review = (not is_dropped) and classification.confidence < LOW_CONFIDENCE_THRESHOLD
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
            "fill_style": fill_style_by_element[region.region_id],
            "angle_deg": round(classification.angle_deg, 2),
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
            "dropped": is_dropped,
            "feature_issue": (issue_by_region[region.region_id].message
                              if region.region_id in issue_by_region else ""),
            "bbox_pct": _bbox_pct(region),
        })
    # Region order as extracted, so the review page lists them stably
    # whether or not any were dropped.
    order_index = {r.region_id: i for i, r in enumerate(regions)}
    regions_meta.sort(key=lambda m: order_index[m["id"]])

    # The order the thread colors sew in (src/pathing/order.py's
    # color_sew_order: fills first, outlines last) -- recorded here so
    # the decision is visible next to everything else the system chose,
    # not buried in the file.
    sew_order = [all_colors[i].matched_thread_name or all_colors[i].name
                 for i in color_sew_order(ordered) if i < len(all_colors)]
    summary = {
        "visual_colors_detected": region_set.raw_color_count,
        "thread_colors_selected": len(all_colors),
        "color_sew_order": sew_order,
        "filled_regions": counts.get(FILL, 0),
        "satin_columns": counts.get(SATIN, 0),
        "running_stitch_details": counts.get(RUNNING, 0),
        "texture_zones": texture_zone_count,
        "warnings_requiring_review": needs_review_count,
    }

    for w in warnings:
        print(f"Warning: {w}")

    result = write_and_report(plan, out_stem)
    print(format_audit_summary(audit))
    result["warnings"] = warnings
    result["summary"] = summary
    # The sewability audit (src/validate/audit.py): what a production
    # digitizer would reject this file for, measured on the exported
    # command stream. Structured, so the web UI and the testbench can
    # compare runs by number rather than by preview image.
    result["audit"] = audit.to_dict()
    result["regions"] = regions_meta
    result["corrections_applied"] = sorted(applied_corrections)
    result["feature_issues"] = [issue.to_dict() for issue in feature_issues]
    return result


def _fill_holes_of_dropped(region, dropped: list) -> "Region":
    """region with any hole that a dropped region sits in filled."""
    polygon = region.polygon
    if not polygon.interiors:
        return region
    probes = [d.polygon.representative_point() for d in dropped if d is not region]
    keep = [ring for ring in polygon.interiors
            if not any(Polygon(ring).contains(probe) for probe in probes)]
    if len(keep) == len(polygon.interiors):
        return region
    return replace(region, polygon=Polygon(polygon.exterior, keep))
