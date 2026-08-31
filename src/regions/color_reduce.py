"""Reduce a raster image to at most MAX_COLORS flat colors via k-means.

Also returns the mean quantization error, which src/regions/scope.py uses
to decide whether the input actually looks flat (in scope) or like a
photo/gradient (out of scope) -- a real photo reduced to 4 colors leaves
a large reconstruction error; a flat logo leaves almost none.
"""
import cv2
import numpy as np

MAX_COLORS = 4


def quantize(rgb: np.ndarray, k: int = MAX_COLORS
             ) -> tuple[np.ndarray, np.ndarray, float]:
    """Returns (label_map HxW int, palette kx3 uint8, mean_error)."""
    h, w, _ = rgb.shape
    samples = rgb.reshape(-1, 3).astype(np.float32)

    k = min(k, len(np.unique(samples, axis=0)))
    k = max(k, 1)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _compactness, labels, centers = cv2.kmeans(
        samples, k, None, criteria, attempts=4, flags=cv2.KMEANS_PP_CENTERS)

    palette = np.clip(centers, 0, 255).astype(np.uint8)
    labels = labels.reshape(h, w)

    reconstructed = palette[labels].astype(np.float32)
    mean_error = float(np.mean(np.abs(reconstructed - rgb.astype(np.float32))))

    return labels, palette, mean_error
