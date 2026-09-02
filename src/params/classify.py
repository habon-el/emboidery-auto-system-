"""Stitch-type assignment rules (Section 6/M2): thin+elongated region ->
satin, wide/blobby -> fill, hairline -> running. Angle comes from the
region's own medial axis (Section 9), never from its bounding box.

Classification itself is decided from the polygon's minimum rotated
rectangle rather than the medial-axis skeleton's walked length: a
skeleton walk is easy to fool by small pixelation artifacts (a smooth
curve rasterizes into a jagged boundary that reads as extra "length") and
gives no coverage guarantee for a genuinely branching shape (a star's
arms meeting at a hub, a letter like "H"/"T" with a crossbar) -- a single
satin zigzag can only trace one branch and leaves the rest of the region
unstitched. A bounding-rectangle elongation/rectangularity test is far
more robust to both problems: branching or compact shapes score low on
one or both measures and fall through to fill, which always covers the
whole polygon regardless of its shape. The medial axis is still used
after classification -- for the fill angle (PCA of the skeleton point
set, which doesn't depend on walk order) and for deriving satin rails
(only reached for shapes this test already confirmed are simple bands).
"""
import math
from dataclasses import dataclass

from src.params.presets import FabricPreset
from src.regions.medial import MedialAxisResult, compute_medial_axis
from src.regions.model import Region
from src.stitches.model import FILL, RUNNING, SATIN

# A region this narrow on average is a hairline stroke -- too thin to
# zigzag as satin, sewn as a running stitch along its own centerline.
RUNNING_MAX_WIDTH_MM = 1.2

# long side / avg width of the minimum rotated rectangle: how "rail-like"
# a shape needs to be to count as a satin column rather than a fill blob.
SATIN_MIN_ELONGATION = 3.0

# polygon.area / minimum-rotated-rectangle.area: how much of its own
# bounding rectangle a shape fills. A true satin band is close to 1 (it
# IS basically a thin rectangle); a branching or notably concave shape
# (a star, a letter with a crossbar) is well below this even when its
# bounding rectangle happens to be elongated.
SATIN_MIN_RECTANGULARITY = 0.55

DEFAULT_FILL_ANGLE_DEG = 45.0
# Below this skeleton length the medial axis is too short/noisy to trust
# for an angle (e.g. a near-circular blob) -- fall back to the default.
MIN_SKELETON_LENGTH_FOR_ANGLE_MM = 3.0



@dataclass
class Classification:
    stitch_type: str
    medial: MedialAxisResult
    angle_deg: float = 0.0
    avg_width_mm: float = 0.0
    # True when the shape reads as satin-like (elongated, rectangular)
    # but exceeds the fabric preset's max satin width, so it was routed
    # to fill instead -- surfaced to validate/checks.py.
    redirected_from_satin: bool = False
    # Which measurement decided the stitch type, in plain language --
    # this is what a manual-correction UI shows next to the decision
    # instead of an unexplained dropdown value.
    reason: str = ""
    # 0..1: how far the deciding measurement sits from its decision
    # boundary, not a statistical probability. A region right at a
    # threshold (e.g. elongation 3.05 against a 3.0 satin cutoff) is
    # low-confidence; one deep in a region's territory is high-confidence.
    confidence: float = 1.0


def _rotated_rect_dims(region_area: float, polygon) -> tuple[float, float, float]:
    """Returns (long_side_mm, short_side_mm, avg_width_mm) of the
    polygon's minimum rotated rectangle. avg_width approximates the
    region's own average thickness as area / long_side, which is exact
    for a true rectangle and a reasonable proxy for anything band-like.
    """
    mrr = polygon.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)
    side_a = math.hypot(coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
    side_b = math.hypot(coords[2][0] - coords[1][0], coords[2][1] - coords[1][1])
    long_side, short_side = max(side_a, side_b), min(side_a, side_b)
    avg_width = region_area / long_side if long_side > 0 else 0.0
    return long_side, short_side, avg_width


def _fill_angle(medial: MedialAxisResult) -> float:
    if medial.path_points_mm and medial.length_mm >= MIN_SKELETON_LENGTH_FOR_ANGLE_MM:
        return medial.angle_deg()
    return DEFAULT_FILL_ANGLE_DEG


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))




def classify_region(region: Region, fabric: FabricPreset) -> Classification:
    polygon = region.polygon
    long_side, short_side, avg_width = _rotated_rect_dims(polygon.area, polygon)
    medial = compute_medial_axis(polygon)

    if avg_width <= RUNNING_MAX_WIDTH_MM:
        angle = medial.angle_deg() if medial.path_points_mm else 0.0
        confidence = _clamp01((RUNNING_MAX_WIDTH_MM - avg_width) / RUNNING_MAX_WIDTH_MM)
        return Classification(
            RUNNING, medial, angle, avg_width_mm=avg_width, confidence=confidence,
            reason=f"average width {avg_width:.2f}mm is at or under the "
                   f"{RUNNING_MAX_WIDTH_MM}mm hairline threshold.")

    if medial.total_skeleton_length_mm > 0:
        # area / total skeleton length (every branch, not just the one
        # walked path) is a topology-independent true average width --
        # unlike avg_width above (which comes from the bounding
        # rectangle and is easily fooled by a shape that winds or curves
        # within a compact bbox, e.g. a spiral or a squiggly line-art
        # stroke). A branching-but-filled shape (a star, a plus sign)
        # still comes out wide by this measure -- its arms have real
        # width -- so this only catches genuinely thin strokes, not the
        # branching-shape case classify.py's own module docstring is
        # about avoiding false positives on.
        true_width = polygon.area / medial.total_skeleton_length_mm
        if true_width <= RUNNING_MAX_WIDTH_MM:
            angle = medial.angle_deg() if medial.path_points_mm else 0.0
            confidence = _clamp01((RUNNING_MAX_WIDTH_MM - true_width) / RUNNING_MAX_WIDTH_MM)
            return Classification(
                RUNNING, medial, angle, avg_width_mm=avg_width, confidence=confidence,
                reason=f"true average width {true_width:.2f}mm (area over full "
                       f"skeleton length, not just its bounding rectangle) is "
                       f"at or under the {RUNNING_MAX_WIDTH_MM}mm hairline "
                       f"threshold -- reads as a thin winding stroke.")

    elongation = long_side / avg_width if avg_width > 0 else 0.0
    rectangularity = polygon.area / (long_side * short_side) if long_side * short_side > 0 else 0.0
    satin_shaped = (elongation >= SATIN_MIN_ELONGATION
                     and rectangularity >= SATIN_MIN_RECTANGULARITY)
    too_wide_for_satin = short_side > fabric.satin_max_width_mm

    if satin_shaped and not too_wide_for_satin:
        angle = medial.angle_deg() if medial.path_points_mm else 0.0
        elong_margin = (elongation - SATIN_MIN_ELONGATION) / SATIN_MIN_ELONGATION
        rect_margin = ((rectangularity - SATIN_MIN_RECTANGULARITY)
                        / (1.0 - SATIN_MIN_RECTANGULARITY))
        width_margin = (fabric.satin_max_width_mm - short_side) / fabric.satin_max_width_mm
        confidence = _clamp01(min(elong_margin, rect_margin, width_margin))
        return Classification(
            SATIN, medial, angle, avg_width_mm=avg_width, confidence=confidence,
            reason=f"elongation {elongation:.1f}x and rectangularity "
                   f"{rectangularity:.2f} both clear the satin thresholds "
                   f"({SATIN_MIN_ELONGATION}x / {SATIN_MIN_RECTANGULARITY}), "
                   f"and width {short_side:.1f}mm fits under "
                   f"{fabric.satin_max_width_mm}mm for '{fabric.name}'.")

    if satin_shaped and too_wide_for_satin:
        width_margin = (short_side - fabric.satin_max_width_mm) / fabric.satin_max_width_mm
        confidence = _clamp01(1.0 - width_margin)  # just-over-width is lower confidence, not higher
        reason = (f"shaped like a satin column (elongation {elongation:.1f}x, "
                  f"rectangularity {rectangularity:.2f}) but {short_side:.1f}mm "
                  f"exceeds the {fabric.satin_max_width_mm}mm max satin width "
                  f"for '{fabric.name}' -- redirected to fill.")
    else:
        # Genuinely blobby, or sitting close enough to the satin boundary
        # that a small change in the source art could have tipped it --
        # flag the latter as lower-confidence rather than presenting
        # every fill decision as equally certain.
        near_satin = (elongation >= SATIN_MIN_ELONGATION * 0.7
                      and rectangularity >= SATIN_MIN_RECTANGULARITY * 0.7)
        confidence = 0.55 if near_satin else 0.95
        reason = (f"elongation {elongation:.1f}x / rectangularity "
                  f"{rectangularity:.2f} sit close to the satin thresholds "
                  f"-- classified as fill, but worth a second look."
                  if near_satin else
                  f"elongation {elongation:.1f}x / rectangularity "
                  f"{rectangularity:.2f} read as a filled blob, not a "
                  f"satin-shaped band.")

    return Classification(
        FILL, medial, _fill_angle(medial), avg_width_mm=avg_width,
        redirected_from_satin=satin_shaped and too_wide_for_satin,
        confidence=confidence, reason=reason)
