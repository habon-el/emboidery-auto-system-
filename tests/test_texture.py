"""Texture-zone detection (Multi-Region Illustration Digitization
milestone, item 8): flags source-image regions whose original pixels
show real local variance that flat-color quantization erased."""
import numpy as np

from src.regions.texture import detect_texture_zone


def test_flat_region_is_not_texture():
    rgb = np.full((40, 40, 3), 120, dtype=np.uint8)
    mask = np.ones((40, 40), dtype=bool)
    result = detect_texture_zone(rgb, mask)
    assert not result.is_texture
    assert result.confidence < 0.2


def test_noisy_region_is_texture():
    rng = np.random.RandomState(0)
    rgb = rng.randint(80, 180, size=(40, 40, 3)).astype(np.uint8)
    mask = np.ones((40, 40), dtype=bool)
    result = detect_texture_zone(rgb, mask)
    assert result.is_texture
    assert result.confidence > 0.5


def test_empty_mask_is_not_texture():
    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    mask = np.zeros((10, 10), dtype=bool)
    result = detect_texture_zone(rgb, mask)
    assert not result.is_texture
    assert result.confidence == 0.0
