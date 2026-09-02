"""Region data model: a closed shape in one flat color, in design-space mm."""
from dataclasses import dataclass, field

from shapely.geometry import Polygon

from src.stitches.model import ThreadColor


@dataclass
class Region:
    polygon: Polygon           # exterior + holes, in mm
    color_index: int
    source: str = "raster"     # "raster" | "svg"
    region_id: str = ""
    # Draw/discovery order (0-based). For SVG this is the source
    # document's own paint order, which is meaningful (an SVG shape
    # painted later legitimately sits above one painted earlier). For
    # raster this is just quantization/contour discovery order -- a
    # reasonable default z-order, not a resolved overlap analysis
    # (raster regions come from mutually-exclusive per-pixel color
    # masks, so they don't literally overlap the way SVG shapes can).
    z_order: int = 0
    # Set by src/regions/texture.py during raster extraction: True when
    # the *original* (pre-quantization) pixels under this region show
    # meaningfully more local variance than a flat-color noise floor --
    # i.e. quantization flattened away real drawn texture here.
    texture_zone: bool = False
    texture_confidence: float = 0.0


@dataclass
class RegionSet:
    regions: list[Region]
    colors: list[ThreadColor]
    width_mm: float
    height_mm: float
    warnings: list[str] = field(default_factory=list)
    # Pre-/post-Delta-E-merge color cluster counts from perceptual color
    # reduction (src/regions/color_reduce.py). SVG input has no
    # quantization step, so both default to len(colors) there -- every
    # declared fill color is already "one visual color."
    raw_color_count: int = 0
    merged_color_count: int = 0


class DigitizeScopeError(ValueError):
    """Input falls outside the MVP's in-scope input per Section 2 of the
    build spec (photo/gradient, too many colors, text below minimum cap
    height, etc). Raised instead of silently producing a bad file."""
