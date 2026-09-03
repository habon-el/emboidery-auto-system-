"""Regression test: skimage's medial_axis draws an unseeded PRNG by
default to break exact distance-transform ties, which a straight,
symmetric shape (a satin bar's centerline is full of these) hits
constantly -- left unseeded, the *same* polygon skeletonized to a
visibly different pixel count from one call to the next, which
cascaded into a different satin rail walk and a different stitch count
for a design that never changed (found while building the Multi-Region
Illustration Digitization milestone's texture/line-art features, which
made classify_region lean on skeleton length more than before)."""
from shapely.geometry import Polygon

from src.regions.medial import _walk_skeleton, compute_medial_axis


def test_medial_axis_is_deterministic_on_a_symmetric_shape():
    # A long straight rectangle -- every point on its centerline is
    # exactly equidistant from both long edges, which is exactly the
    # tie-breaking case the unseeded PRNG made unstable.
    rect = Polygon([(0, 0), (60, 0), (60, 5), (0, 5)])
    first = compute_medial_axis(rect)
    for _ in range(5):
        again = compute_medial_axis(rect)
        assert len(again.path_points_mm) == len(first.path_points_mm)
        assert again.total_skeleton_length_mm == first.total_skeleton_length_mm


def test_walk_skeleton_reaches_the_full_spine_past_a_looped_tip():
    """Regression test for a real bug found from an actual user upload:
    a thin, straight satin column's ("l" in a bold sans-serif font)
    pruned skeleton came out as a long ~40-pixel spine with a tiny
    leftover 3-pixel *loop* at each tip -- a real skimage medial_axis
    artifact at RASTER_RES_MM's resolution, not a shape property. Every
    pixel in that graph has degree >= 2 (the loops mean there's no true
    degree-1 endpoint anywhere), so the original greedy "walk forward,
    never backtrack" approach could start inside a tip loop, circle it,
    and dead-end after 2-3 points -- entirely depending on which
    neighbor happened to be tried first -- while the real spine sat
    completely unvisited. That's exactly what turned this letter's
    satin column into a tiny zigzag star instead of a clean column.

    This is the literal pixel coordinate list captured from that real
    failure (src/regions/medial.py's _prune_spurs output for that
    region), used directly rather than a synthetic approximation.
    """
    barbell_pixels = [
        (5, 5), (5, 6), (5, 8), (5, 13), (5, 15), (5, 16), (5, 17), (5, 18),
        (5, 19), (5, 22), (5, 24), (5, 25), (5, 26), (5, 31), (5, 34),
        (5, 37), (5, 38), (5, 39), (5, 40), (5, 41), (5, 42),
        (6, 5), (6, 7), (6, 9), (6, 10), (6, 11), (6, 12), (6, 14),
        (6, 20), (6, 21), (6, 23), (6, 27), (6, 28), (6, 29), (6, 30),
        (6, 32), (6, 33), (6, 35), (6, 36), (6, 42),
    ]
    order = _walk_skeleton(barbell_pixels)
    # The real spine is all 40 pixels (one connected barbell graph) --
    # the walk must reach (nearly) all of it, not get trapped in a
    # 3-pixel tip loop.
    assert len(order) >= len(barbell_pixels) - 2
