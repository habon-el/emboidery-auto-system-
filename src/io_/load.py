"""Raster input loading.

Converts a PNG/JPG into an RGB numpy array plus a pixels-per-mm scale
factor, so everything downstream works in real-world millimetres.

Scale comes from the image's DPI metadata when present. Most logo/text
exports don't carry real DPI info, so a missing/implausible value falls
back to a documented assumption (96 DPI) rather than guessing silently --
this is exactly the kind of "smallest reasonable assumption, noted"
Section 10 asks for. Pass `dpi_override` (from a future --dpi CLI flag)
to skip the guess entirely.
"""
import numpy as np
from PIL import Image

FALLBACK_DPI = 96.0
MM_PER_INCH = 25.4


def load_raster(path: str, dpi_override: float | None = None
                 ) -> tuple[np.ndarray, float, list[str]]:
    """Returns (rgb_array HxWx3 uint8, px_per_mm, warnings)."""
    warnings: list[str] = []
    img = Image.open(path)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        # Flatten onto white so a transparent background doesn't get
        # treated as a fifth color by the quantizer.
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert("RGB")
    else:
        img = img.convert("RGB")

    if dpi_override:
        dpi = dpi_override
    else:
        dpi_info = img.info.get("dpi")
        dpi = dpi_info[0] if dpi_info else None
        if not dpi or dpi < 10:
            dpi = FALLBACK_DPI
            warnings.append(
                f"No usable DPI metadata found; assuming {FALLBACK_DPI:.0f} "
                "DPI. Pass an explicit DPI if the design comes out the "
                "wrong physical size.")

    px_per_mm = dpi / MM_PER_INCH
    return np.array(img), px_per_mm, warnings
