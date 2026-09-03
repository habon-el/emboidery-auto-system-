"""Dispatch input loading by file type and produce a RegionSet, applying
out-of-scope detection along the way (Section 2/9)."""
import os

from src.io_.load import load_raster
from src.regions.model import DigitizeScopeError, RegionSet
from src.regions.raster_regions import extract_raster_regions
from src.regions.scope import (apply_findings, check_color_complexity,
                                check_min_feature_size)
from src.regions.svg_regions import extract_svg_regions


def load_and_extract_regions(path: str, dpi_override: float | None = None,
                              strict: bool = True, check_min_size: bool = True
                              ) -> RegionSet:
    """strict=False (--force / the web UI's force checkbox) downgrades the
    photo/gradient and minimum-cap-height scope checks to warnings instead
    of hard rejections. Regions below the ~2mm^2 noise-floor area are
    always dropped regardless -- that's basic contour noise reduction,
    not a scope judgment call, and skipping it on a genuine photo could
    generate thousands of speck-sized regions and blow up runtime.

    check_min_size=False skips the minimum-cap-height check here entirely
    -- used by src/pipeline.py's load_scaled_region_set when a target
    width/height is about to rescale the design, since checking the
    *source* image's incidental native size (often just a guess from
    missing/assumed DPI -- see src/io_/load.py) before that resize ever
    happens means a source that's "too small" only because of that guess
    gets rejected even though the requested finished size would have
    been perfectly fine. The real check that matters -- on the actual
    scaled geometry -- still runs right after scaling either way.
    """
    warnings: list[str] = []
    ext = os.path.splitext(path)[1].lower()

    dropped_small = 0
    raw_color_count = merged_color_count = 0
    if ext == ".svg":
        regions, colors, width_mm, height_mm, svg_warnings = extract_svg_regions(path)
        warnings.extend(svg_warnings)
        raw_color_count = merged_color_count = len(colors)
    else:
        rgb, px_per_mm, load_warnings = load_raster(path, dpi_override)
        warnings.extend(load_warnings)
        (regions, colors, mean_error, dropped_small,
         raw_color_count, merged_color_count) = extract_raster_regions(rgb, px_per_mm)
        h, w = rgb.shape[:2]
        width_mm, height_mm = w / px_per_mm, h / px_per_mm
        apply_findings([check_color_complexity(mean_error)], warnings, strict)

    if not regions:
        if dropped_small:
            raise DigitizeScopeError(
                f"All {dropped_small} candidate region(s) were smaller than "
                f"the minimum stitchable area (~2mm^2 noise floor, not "
                f"affected by --force) -- there is nothing left to stitch.")
        raise DigitizeScopeError(
            "No stitchable regions found (after removing the background). "
            "Is this a flat 2-4 color logo/text image?")
    if dropped_small:
        warnings.append(
            f"{dropped_small} tiny region(s) were dropped as noise/below "
            f"the minimum stitchable area.")

    if check_min_size:
        heights_mm = [r.polygon.bounds[3] - r.polygon.bounds[1] for r in regions]
        apply_findings([check_min_feature_size(heights_mm)], warnings, strict)

    return RegionSet(regions=regions, colors=colors,
                      width_mm=width_mm, height_mm=height_mm, warnings=warnings,
                      raw_color_count=raw_color_count, merged_color_count=merged_color_count)
