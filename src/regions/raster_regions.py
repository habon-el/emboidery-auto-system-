"""Raster -> closed shapely regions per color.

Pipeline: quantize to <=4 colors -> pick the border-touching color as
background and drop it -> per remaining color, trace contours (with
holes) -> simplify jagged pixel edges -> convert to mm-space Polygons.
"""
import cv2
import numpy as np
from shapely.geometry import Polygon

from src.regions.color_reduce import quantize
from src.regions.model import Region
from src.stitches.model import ThreadColor

MIN_REGION_AREA_MM2 = 2.0
SIMPLIFY_TOLERANCE_MM = 0.15


def _background_label(labels: np.ndarray) -> int:
    border = np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
    ])
    counts = np.bincount(border)
    return int(np.argmax(counts))


def _contours_to_polygon(mask: np.ndarray, px_per_mm: float
                          ) -> tuple[list[Polygon], int]:
    contours, hierarchy = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]

    eps_px = SIMPLIFY_TOLERANCE_MM * px_per_mm
    simplified = [cv2.approxPolyDP(c, eps_px, True) for c in contours]

    def to_mm(contour) -> list[tuple[float, float]]:
        return [(pt[0][0] / px_per_mm, pt[0][1] / px_per_mm) for pt in contour]

    polygons: list[Polygon] = []
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
        geoms = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            if g.area >= MIN_REGION_AREA_MM2:
                polygons.append(g)
            else:
                dropped_small += 1
    return polygons, dropped_small


def extract_raster_regions(rgb: np.ndarray, px_per_mm: float
                            ) -> tuple[list[Region], list[ThreadColor], float, int]:
    """Returns (regions, colors, mean_quantization_error, dropped_small_count)."""
    labels, palette, mean_error = quantize(rgb)
    bg_label = _background_label(labels)

    regions: list[Region] = []
    colors: list[ThreadColor] = []
    color_index = 0
    total_dropped_small = 0
    for label in range(palette.shape[0]):
        if label == bg_label:
            continue
        mask = labels == label
        if not mask.any():
            continue
        polygons, dropped_small = _contours_to_polygon(mask, px_per_mm)
        total_dropped_small += dropped_small
        if not polygons:
            continue
        r, g, b = (int(c) for c in palette[label])
        colors.append(ThreadColor(name=f"color {color_index + 1}", rgb=(r, g, b)))
        for i, poly in enumerate(polygons):
            regions.append(Region(
                polygon=poly, color_index=color_index, source="raster",
                region_id=f"raster-{label}-{i}"))
        color_index += 1

    return regions, colors, mean_error, total_dropped_small
