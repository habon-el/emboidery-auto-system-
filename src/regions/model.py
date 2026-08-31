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


@dataclass
class RegionSet:
    regions: list[Region]
    colors: list[ThreadColor]
    width_mm: float
    height_mm: float
    warnings: list[str] = field(default_factory=list)


class DigitizeScopeError(ValueError):
    """Input falls outside the MVP's in-scope input per Section 2 of the
    build spec (photo/gradient, too many colors, text below minimum cap
    height, etc). Raised instead of silently producing a bad file."""
