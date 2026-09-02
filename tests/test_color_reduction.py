"""Perceptual (Lab) color reduction (Multi-Region Illustration Digitization
milestone, item 3): more than the old 4-color RGB ceiling, determinism,
and small-cluster (anti-aliasing edge) absorption."""
import numpy as np

from src.regions.color_reduce import quantize


def _flat_color_image(colors: list[tuple[int, int, int]], tile: int = 20) -> np.ndarray:
    """A tile-per-color flat raster -- no anti-aliasing, so this isolates
    the clustering/merge logic from edge-noise handling."""
    img = np.zeros((tile, tile * len(colors), 3), dtype=np.uint8)
    for i, c in enumerate(colors):
        img[:, i * tile:(i + 1) * tile] = c
    return img


def test_eight_distinct_flat_colors_stay_separate():
    colors = [
        (230, 20, 20), (20, 160, 60), (20, 60, 200), (230, 200, 20),
        (160, 20, 160), (20, 180, 180), (120, 80, 40), (240, 240, 240),
    ]
    img = _flat_color_image(colors)
    _labels, palette, mean_error, raw, merged = quantize(img)
    assert merged == 8
    assert mean_error < 2.0  # each color reconstructs almost exactly


def test_near_duplicate_colors_merge():
    """Two colors within a few Delta-E of each other should fold into
    one -- this is what turns e.g. 12 raw clusters into 8 real colors."""
    colors = [(200, 30, 30), (204, 32, 31), (20, 120, 20)]  # first two are near-identical
    img = _flat_color_image(colors)
    _labels, palette, _err, raw, merged = quantize(img, raw_k=6)
    assert merged == 2


def test_quantize_is_deterministic():
    """Same input, called repeatedly, must produce the same palette and
    label map -- a design that hasn't changed must digitize the same way
    every time (see src/regions/color_reduce.py's _kmeans_lab docstring)."""
    rng = np.random.RandomState(0)
    img = rng.randint(0, 255, size=(60, 60, 3), dtype=np.uint8)
    first_labels, first_palette, _, first_raw, first_merged = quantize(img)
    for _ in range(3):
        labels, palette, _err, raw, merged = quantize(img)
        assert raw == first_raw
        assert merged == first_merged
        assert np.array_equal(labels, first_labels)
        assert np.array_equal(palette, first_palette)


def test_small_cluster_absorbed_into_dominant_neighbor():
    """A thin band of intermediate/anti-aliasing-like pixels (too small a
    fraction of the image to be a real color) should be folded into
    whichever larger color it's closest to, not survive as its own
    cluster -- otherwise a smooth edge fragments into many tiny regions
    instead of one clean shape (this was a real regression found while
    building this feature: raising raw_k without this step badly
    fragmented a satin-bar test image's boundary)."""
    h, w = 40, 1000
    img = np.full((h, w, 3), (255, 255, 255), dtype=np.uint8)
    img[:, :600] = (200, 30, 30)
    # A ~2px seam of an intermediate shade between the two blocks -- a
    # small fraction (0.2%) of the image's total pixels, well under the
    # small-cluster threshold, unlike each of the two real color blocks.
    img[:, 600:602] = (227, 130, 115)
    _labels, palette, _err, raw, merged = quantize(img)
    assert raw > merged  # the seam's cluster did not survive on its own
    assert merged == 2
