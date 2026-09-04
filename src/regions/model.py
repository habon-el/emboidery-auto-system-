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
    # Layer order (lower sews first) among regions of the same color --
    # a hard constraint for src/pathing/order.py, which is otherwise
    # free to pick the nearest region next. Raster regions come from
    # mutually-exclusive per-pixel color masks, so two of the same
    # color can never overlap: every region of a color shares one
    # layer (its color's index) and a human moves one ahead of or
    # behind its peers with the manual-review z_order override. SVG
    # regions all default to the same layer too; the document's paint
    # order is not yet captured.
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
