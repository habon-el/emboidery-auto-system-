"""Match a design color to the nearest color in a real thread manufacturer
palette, via Delta-E distance in CIELab space (not raw RGB nearest-
neighbor, for the same perceptual-accuracy reason src/regions/color_reduce.py
clusters in Lab). This is what turns "12 visual colors detected" into
"8 thread colors selected" in the analysis summary -- some source colors
legitimately map to the same available thread.

The shipped palette is a small representative sample of Isacord polyester
embroidery thread numbers/colors, not the full manufacturer catalog --
easy to extend or swap for a different brand's palette dict (only
{name, code, rgb} is required per entry).
"""
from dataclasses import dataclass

import cv2
import numpy as np

ISACORD_SAMPLE: list[tuple[str, str, tuple[int, int, int]]] = [
    ("White", "0100", (255, 255, 255)),
    ("Black", "0200", (0, 0, 0)),
    ("True Red", "1900", (188, 34, 42)),
    ("Really Red", "1902", (200, 16, 46)),
    ("Poppy Red", "1802", (215, 61, 43)),
    ("Orange", "1300", (237, 125, 49)),
    ("Sunflower", "1120", (247, 181, 56)),
    ("Yellow", "0200", (255, 214, 0)),
    ("Gold", "0300", (211, 166, 37)),
    ("Bright Mint", "5620", (99, 199, 152)),
    ("Kelly Green", "5400", (0, 138, 78)),
    ("Dark Grass Green", "5643", (49, 99, 46)),
    ("Real Teal", "4610", (0, 130, 140)),
    ("Copen Blue", "3743", (66, 143, 189)),
    ("Robin Egg", "3720", (108, 195, 213)),
    ("Delft Blue", "3540", (43, 84, 145)),
    ("Navy", "3335", (25, 41, 82)),
    ("Purple", "2810", (95, 55, 128)),
    ("Orchid", "2530", (161, 88, 158)),
    ("Hot Pink", "2510", (222, 60, 130)),
    ("Country Rose", "2223", (176, 92, 108)),
    ("Tan", "0710", (206, 174, 128)),
    ("Coffee Brown", "0847", (92, 64, 51)),
    ("Charcoal", "0180", (79, 79, 82)),
    ("Silver Grey", "0231", (166, 168, 167)),
]


@dataclass
class ThreadMatch:
    name: str
    code: str
    rgb: tuple[int, int, int]
    delta_e: float

    @property
    def low_confidence(self) -> bool:
        # A large Delta-E to the nearest stocked thread means "we're
        # approximating this color," not "we found it" -- worth flagging
        # rather than presenting the match as exact.
        return self.delta_e > 12.0


def _rgb_to_lab1(rgb: tuple[int, int, int]) -> np.ndarray:
    arr = np.array([[rgb]], dtype=np.uint8)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)


def match_thread(rgb: tuple[int, int, int],
                  palette: list[tuple[str, str, tuple[int, int, int]]] = ISACORD_SAMPLE
                  ) -> ThreadMatch:
    """Nearest palette thread to `rgb` by Delta-E (CIE76) in Lab space."""
    target_lab = _rgb_to_lab1(rgb)
    best = None
    best_dist = float("inf")
    for name, code, prgb in palette:
        dist = float(np.linalg.norm(target_lab - _rgb_to_lab1(prgb)))
        if dist < best_dist:
            best_dist = dist
            best = (name, code, prgb)
    name, code, prgb = best
    return ThreadMatch(name=name, code=code, rgb=prgb, delta_e=round(best_dist, 1))
