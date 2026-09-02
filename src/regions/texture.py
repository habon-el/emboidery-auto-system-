"""Texture-zone detection (Multi-Region Illustration Digitization
milestone, item 8) -- flags artwork zones that read as textured in the
*source* image (a drawn fur/scale/wood-grain pattern meant to look
different from a flat block), not the physical fabric the design will
be sewn onto (that's a separate, later feature: texture-classifying a
photo of the blank garment to auto-suggest a FabricPreset).

By the time a Region exists, its color has already been flattened to
one flat quantized color -- the pixel-level detail that made it look
textured lives only in the *original* raster, not the region's own
mask. So detection has to look back at the source image within the
region's footprint: a genuinely flat-colored area has near-zero local
intensity variance there; an area quantization flattened away real
texture leaves a local variance well above the flat-region noise floor.
"""
from dataclasses import dataclass

import cv2
import numpy as np

# Local std-dev (0-255 grayscale) below this is indistinguishable from
# compression/dither noise on a genuinely flat region.
FLAT_NOISE_FLOOR = 4.0
# Local std-dev at or above this is confidently "this had real texture."
TEXTURE_CONFIDENT_STD = 14.0


@dataclass
class TextureResult:
    is_texture: bool
    confidence: float   # 0..1, margin above the flat-region noise floor
    mean_local_std: float


def detect_texture_zone(source_rgb: np.ndarray, mask: np.ndarray) -> TextureResult:
    """mask is an HxW boolean array (same shape as source_rgb's first two
    dims) marking the pixels belonging to one region, in the *original*
    (pre-quantization) image."""
    if not mask.any():
        return TextureResult(False, 0.0, 0.0)

    gray = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # A small local window's std-dev map -- computed once over the whole
    # image via box-filtered mean/mean-of-squares, then sampled by mask,
    # which is far cheaper than a per-pixel Python loop.
    k = 5
    mean = cv2.blur(gray, (k, k))
    mean_sq = cv2.blur(gray * gray, (k, k))
    local_var = np.clip(mean_sq - mean * mean, 0, None)
    local_std = np.sqrt(local_var)

    # Every region has real intensity variance right at its own boundary
    # -- anti-aliasing softens the edge into a gradient regardless of
    # whether the interior is textured at all. Sampling the raw mask
    # would read that boundary gradient as "texture" on every ordinary
    # region, especially a small one where the edge is a large share of
    # its area. Erode a few pixels in first so only interior pixels,
    # away from the region's own edge, count toward this measurement.
    sample_mask = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    if not sample_mask.any():
        sample_mask = mask  # region too thin/small to erode -- fall back rather than skip it

    mean_local_std = float(local_std[sample_mask].mean())
    margin = mean_local_std - FLAT_NOISE_FLOOR
    span = TEXTURE_CONFIDENT_STD - FLAT_NOISE_FLOOR
    confidence = max(0.0, min(1.0, margin / span)) if span > 0 else 0.0
    is_texture = mean_local_std >= FLAT_NOISE_FLOOR + (span * 0.35)

    return TextureResult(is_texture, round(confidence, 2), round(mean_local_std, 2))
