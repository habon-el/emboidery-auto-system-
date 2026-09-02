"""Raster -> closed shapely regions per color.

Pipeline: perceptual (Lab) color reduction -> pick the border-touching
color as background and drop it -> per remaining color, trace contours
(with holes) -> simplify jagged pixel edges -> convert to mm-space
Polygons -> flag texture zones and match each color to a thread.
"""
import cv2
import numpy as np
from shapely.geometry import Polygon

from src.params.thread_palette import match_thread
from src.regions.color_reduce import quantize
from src.regions.model import Region
from src.regions.texture import detect_texture_zone
from src.stitches.model import ThreadColor

MIN_REGION_AREA_MM2 = 2.0
SIMPLIFY_TOLERANCE_MM = 0.15


def _background_label(labels: np.ndarray) -> int:
    border = np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
    ])
    counts = np.bincount(border)
    return int(np.argmax(counts))


def _contours_to_polygons(mask: np.ndarray, px_per_mm: float
                           ) -> tuple[list[tuple[Polygon, np.ndarray]], int]:
    """Returns ([(polygon, pixel_mask_of_that_region), ...], dropped_small).
    pixel_mask is the original (pre-simplification) pixel footprint of
    that specific contour, intersected with the color mask -- used by
    texture detection to look back at the source image, not the
    simplified/quantized geometry.
    """
    contours, hierarchy = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return [], 0
    hierarchy = hierarchy[0]

    eps_px = SIMPLIFY_TOLERANCE_MM * px_per_mm
    simplified = [cv2.approxPolyDP(c, eps_px, True) for c in contours]

    def to_mm(contour) -> list[tuple[float, float]]:
        return [(pt[0][0] / px_per_mm, pt[0][1] / px_per_mm) for pt in contour]

    results: list[tuple[Polygon, np.ndarray]] = []
    dropped_small = 0
    for i, h in enumerate(hierarchy):
        parent = h[3]
        if parent != -1:
            continue  # handled as a hole of its parent below
        if len(simplified[i]) < 3:
            continue
        exterior = to_mm(simplified[i])
        holes = []
        child = h[2]
        while child != -1:
            if len(simplified[child]) >= 3:
                holes.append(to_mm(simplified[child]))
            child = hierarchy[child][0]
        try:
            poly = Polygon(exterior, holes).buffer(0)
        except Exception:
            continue
        if poly.is_empty:
            continue

        # This contour's own pixel footprint, for texture detection --
        # filled from the ORIGINAL (unsimplified) contour so it matches
        # the actual source pixels, then ANDed with the color mask so
        # hole pixels (a different label) are naturally excluded.
        region_px_mask = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(region_px_mask, [contours[i]], -1, 1, thickness=cv2.FILLED)
        region_px_mask = (region_px_mask.astype(bool)) & mask

        geoms = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            if g.area >= MIN_REGION_AREA_MM2:
                results.append((g, region_px_mask))
            else:
                dropped_small += 1
    return results, dropped_small


def extract_raster_regions(rgb: np.ndarray, px_per_mm: float
                            ) -> tuple[list[Region], list[ThreadColor], float, int, int, int]:
    """Returns (regions, colors, mean_quantization_error,
    dropped_small_count, raw_color_count, merged_color_count).

    raw_color_count/merged_color_count are the pre-/post-Delta-E-merge
    cluster counts from perceptual color reduction (src/regions/
    color_reduce.py) -- distinct from len(colors), since a color can
    survive merging but still get dropped here for having no region
    above the noise floor (background, or all-tiny-speck regions).
    """
    labels, palette, mean_error, raw_colors, merged_colors = quantize(rgb)
    bg_label = _background_label(labels)

    regions: list[Region] = []
    colors: list[ThreadColor] = []
    color_index = 0
    z_order = 0
    total_dropped_small = 0
    for label in range(palette.shape[0]):
        if label == bg_label:
            continue
        mask = labels == label
        if not mask.any():
            continue
        found, dropped_small = _contours_to_polygons(mask, px_per_mm)
        total_dropped_small += dropped_small
        if not found:
            continue

        r, g, b = (int(c) for c in palette[label])
        thread = match_thread((r, g, b))
        colors.append(ThreadColor(
            name=f"color {color_index + 1}", rgb=(r, g, b),
            matched_thread_name=thread.name, matched_thread_code=thread.code,
            thread_delta_e=thread.delta_e))

        for i, (poly, region_px_mask) in enumerate(found):
            texture = detect_texture_zone(rgb, region_px_mask)
            regions.append(Region(
                polygon=poly, color_index=color_index, source="raster",
                region_id=f"raster-{label}-{i}", z_order=z_order,
                texture_zone=texture.is_texture,
                texture_confidence=texture.confidence))
            z_order += 1
        color_index += 1

    return regions, colors, mean_error, total_dropped_small, raw_colors, merged_colors
