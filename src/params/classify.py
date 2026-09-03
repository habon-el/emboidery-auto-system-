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
import statistics
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

# --- curved stroke ("satin outline") detection -------------------------
#
# The rectangularity test above only ever passes for a *straight* band:
# a curved stroke fills almost none of its own bounding rectangle. On a
# real cartoon line-art face every black outline -- the head oval, the
# eyebrows, the smile, the hair strands -- measured elongation 14x to
# 30x with rectangularity 0.04-0.30, so all of them fell through to
# fill and came out as mushy blobs instead of crisp lines. Outlining a
# curve with a satin column is *the* fundamental line-art digitizing
# technique, so it needs a test that doesn't go through the bounding box.
#
# A stroke is recognised from its own medial axis instead:
#   * it is long relative to its width (aspect, measured along the
#     centerline rather than across a bounding rectangle), and
#   * its width stays near-constant down that length (a blob's medial
#     axis runs from a fat middle out to thin tips), and
#   * the walked centerline explains essentially the whole skeleton.
#
# That last one is what keeps a *branching* shape out (a star, a letter
# "H"): a single satin column can only trace one branch, so anything
# whose skeleton the walk doesn't account for must stay fill -- which is
# the same guarantee the rectangularity test used to provide, kept
# explicitly instead of as a side effect.
# Each satin column must be at least this much longer than it is wide.
# Measured per branch, not on the summed skeleton: a thick plus sign's
# four arms are each as wide as they are long (aspect ~1) but sum to a
# stroke-like total, and satining them would sew 8mm columns 8mm long.
# A letter's stems come out around 2.2-2.8 and a line-art outline far
# higher, so this keeps both while excluding the stubby case.
STROKE_MIN_ASPECT = 2.0

# Curved-stroke detection is for *line art* -- outlines, letter stems,
# detail strokes -- which are thin. A wide curved band (a badge's 10mm
# ring) is a different animal: rails derived from a medial axis are only
# an approximation of the true boundary, and at that width the
# approximation shows as a visibly ragged, flaring edge where a plain
# fill was clean. Wide bands therefore keep the old behaviour. The
# fabric preset's satin_max_width_mm still applies on top of this; this
# is the narrower limit for the *curved* path specifically.
STROKE_MAX_WIDTH_MM = 5.0
STROKE_MAX_WIDTH_VARIATION = 0.40
# polygon area over (total skeleton length x average width): ~1 when the
# skeleton really does explain the shape as a constant-width stroke
# network. This is what keeps a *tapering* branching shape out -- a
# star's arms or a square's diagonals run from a fat middle to zero-width
# tips, so their area and their skeleton disagree badly -- while letting
# a genuine outline network through, where every branch is the same
# width as every other. Junction pixels get counted by more than one
# branch, so a network measures a little under 1.
STROKE_AREA_RATIO_RANGE = (0.55, 1.7)

# Satin is only chosen when the columns we would emit actually cover the
# stroke. A shape we can column only partly is better off filled, which
# covers everything by construction -- this is what stops a letter "o"
# (a ring whose skeleton we can't always reassemble into one loop, and
# which measures ~65% covered) from being stitched as a "c".
#
# Not higher, because the measure under-counts by a few percent at every
# junction by construction: the stub where strokes meet is dropped as a
# column of its own, so its pixels score as uncovered even though the
# columns either side of it stitch that fabric. Two crossing strokes
# measure 85% for that reason alone.
STROKE_MIN_STITCHABLE_COVERAGE = 0.75

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

    # A region with a hole (a letter bowl like "e"/"o"/"d", a ring) has
    # a *closed-loop* medial axis, not a tree of open branches -- spur
    # pruning only removes short dead-end branches, so it can't clean up
    # a loop that picked up pixel-level jaggedness from rasterization.
    # That inflates total_skeleton_length_mm for a holed region without
    # anything correcting for it, which systematically *underestimates*
    # true_width below -- confirmed to misclassify ordinary bowled
    # letters at normal text sizes as thin line art (e.g. "Hello World"
    # digitizing every rounded letter as a scribbly running stitch
    # instead of a filled glyph). The true-width check below is only
    # valid for a simply-connected region's open skeleton, so holed
    # regions skip it entirely and fall through to the bounding-
    # rectangle-based test the same as any other blobby shape.
    if not polygon.interiors and medial.total_skeleton_length_mm > 0:
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

    # A curved stroke: caught here, before the bounding-rectangle tests
    # below, which any curve fails by construction.
    # Measured over the WHOLE skeleton, not just the one walked path:
    # every branch gets its own satin column (medial.branch_rails), so
    # nothing is left unstitched and the question is only whether the
    # shape really is a constant-width stroke network.
    # Judge the proportions of whatever will actually be stitched: one
    # column for a simple stroke, or the branches for a network (the
    # same choice branch_rails() makes, for the same coverage reason).
    single_aspect = (medial.length_mm / medial.avg_width_mm
                     if medial.avg_width_mm > 0 else 0.0)
    aspects = medial.branch_aspects()
    branch_aspect = statistics.median(aspects) if aspects else 0.0
    stroke_aspect = max(single_aspect, branch_aspect) if aspects else single_aspect
    explained_area = medial.total_skeleton_length_mm * medial.avg_width_mm
    area_ratio = polygon.area / explained_area if explained_area > 0 else 0.0
    lo, hi = STROKE_AREA_RATIO_RANGE
    is_stroke = (stroke_aspect >= STROKE_MIN_ASPECT
                 and medial.width_variation <= STROKE_MAX_WIDTH_VARIATION
                 and lo <= area_ratio <= hi
                 and medial.stitchable_coverage() >= STROKE_MIN_STITCHABLE_COVERAGE)
    if (is_stroke and medial.max_width_mm <= STROKE_MAX_WIDTH_MM
            and medial.max_width_mm <= fabric.satin_max_width_mm):
        confidence = _clamp01(min(
            (stroke_aspect - STROKE_MIN_ASPECT) / STROKE_MIN_ASPECT,
            (STROKE_MAX_WIDTH_VARIATION - medial.width_variation) / STROKE_MAX_WIDTH_VARIATION))
        n_branches = len(medial.branches)
        shape = ("closed outline ring" if medial.is_closed_loop
                 else f"outline network of {n_branches} strokes" if n_branches > 1
                 else "curved stroke")
        return Classification(
            SATIN, medial, medial.angle_deg(), avg_width_mm=medial.avg_width_mm,
            confidence=confidence,
            reason=f"reads as a {shape}: {stroke_aspect:.0f}x longer than it is "
                   f"wide along its own centerline, width varies only "
                   f"{medial.width_variation * 100:.0f}% down that length, and its "
                   f"area matches that centerline x width to within "
                   f"{abs(1 - area_ratio) * 100:.0f}% -- satin along the curve.")

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
