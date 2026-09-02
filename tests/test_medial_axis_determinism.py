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

from src.regions.medial import compute_medial_axis


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
