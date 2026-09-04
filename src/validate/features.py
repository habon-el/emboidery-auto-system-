"""Small-feature policy: which regions cannot be rendered at the
requested size, and what to do about each one -- reported, never
applied.

The size floor used to be a hard rejection quoting a millimetre
number ("1 region(s) are under the 6.0mm minimum cap height (smallest:
1.8mm)"), which tells a user nothing about what to change. On the
cartoon face at 200mm the eye is a stack of nested shapes -- iris
outline, highlight, pupil -- each of which classified correctly on its
own, and which together could not be sewn: the highlight swelled and
consumed the pupil. Two kinds of failure, then:

* too small: the feature as a whole is under the minimum feature size
  (a watermark letter, a dot). Thread is ~0.4mm wide; below about 6mm
  nothing reads as what it was drawn as.
* too narrow: a fill region whose narrowest span -- measured down its
  medial axis, so a ring is judged by its band and not its diameter --
  fits fewer than a few fill rows. It sews as a ragged line. A region
  is often narrow *because* of what sits inside it: a pupil is a wide
  disc until the highlight cut out of its middle leaves a 1mm ring.

Every issue carries concrete, numeric remedies: the design height at
which the feature clears the floor, and which region(s) to drop (a
dropped region merges into whatever surrounds it -- the fabric, or
the region whose hole it sat in, which is then filled). Nothing here
changes the design. This system does not get to decide what detail
to discard; a drop is applied only when a human accepts it through
RegionOverride.drop (src/review/corrections.py), and is recorded like
any other override.
"""
from dataclasses import asdict, dataclass, field

from shapely.geometry import Polygon

from src.params.classify import Classification
from src.params.presets import FabricPreset
from src.regions.model import Region
from src.regions.scope import MIN_FEATURE_HEIGHT_MM
from src.stitches.model import FILL

# A fill region narrower than this (down its medial axis) holds only
# three or four rows at a normal spacing, with pull-in eating the
# edges -- it no longer reads as a filled shape.
FILL_MIN_WIDTH_MM = 1.5

TOO_SMALL = "too_small"
TOO_NARROW = "too_narrow"


@dataclass
class FeatureIssue:
    region_id: str
    kind: str
    stitch_type: str
    # The feature's overall size (its longer bounding-box side) and its
    # narrowest span (medial-axis width, for a fill).
    size_mm: float
    narrowest_mm: float
    needed_mm: float
    # Remedy 1: scale the whole design until this feature clears the
    # floor -- the factor, and the design height that gives.
    scale_factor: float
    scale_to_height_mm: float
    # Remedy 2: drop this region. It merges into `merges_into` (the
    # region whose hole it sits in) or, when None, into bare fabric.
    merges_into: str | None
    # Remedy 3 (narrow fills only): drop the regions inside this one
    # instead, which fills its holes and widens it to widened_to_mm.
    children: list[str] = field(default_factory=list)
    widened_to_mm: float = 0.0
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _size_mm(polygon) -> float:
    minx, miny, maxx, maxy = polygon.bounds
    return max(maxx - minx, maxy - miny)


def _narrowest_mm(polygon) -> float:
    rect = polygon.minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        return 0.0
    c = list(rect.exterior.coords)
    a = ((c[0][0] - c[1][0]) ** 2 + (c[0][1] - c[1][1]) ** 2) ** 0.5
    b = ((c[1][0] - c[2][0]) ** 2 + (c[1][1] - c[2][1]) ** 2) ** 0.5
    return min(a, b)


def _hole_parent(region: Region, regions: list[Region]) -> str | None:
    """The region whose hole this one sits in, if any."""
    probe = region.polygon.representative_point()
    for other in regions:
        if other is region or not other.polygon.interiors:
            continue
        if any(Polygon(ring).contains(probe) for ring in other.polygon.interiors):
            return other.region_id
    return None


def _children_in_holes(region: Region, regions: list[Region]) -> list[str]:
    if not region.polygon.interiors:
        return []
    holes = [Polygon(ring) for ring in region.polygon.interiors]
    return [other.region_id for other in regions
            if other is not region
            and any(h.contains(other.polygon.representative_point()) for h in holes)]


def assess_features(classified: list[tuple[Region, Classification]],
                    design_height_mm: float, fabric: FabricPreset) -> list[FeatureIssue]:
    """One FeatureIssue per region that cannot render at this size,
    in region order. Deterministic: a pure function of the input."""
    regions = [r for r, _ in classified]
    issues: list[FeatureIssue] = []
    for region, classification in classified:
        size = _size_mm(region.polygon)
        narrowest = (classification.medial.avg_width_mm
                     if classification.medial.widths_mm else _narrowest_mm(region.polygon))
        parent = _hole_parent(region, regions)
        into = f"into region {parent}" if parent else "into the fabric"

        if 0 < size < MIN_FEATURE_HEIGHT_MM:
            factor = MIN_FEATURE_HEIGHT_MM / size
            to_height = design_height_mm * factor
            issues.append(FeatureIssue(
                region_id=region.region_id, kind=TOO_SMALL,
                stitch_type=classification.stitch_type,
                size_mm=round(size, 2), narrowest_mm=round(narrowest, 2),
                needed_mm=MIN_FEATURE_HEIGHT_MM,
                scale_factor=round(factor, 2), scale_to_height_mm=round(to_height, 1),
                merges_into=parent,
                message=(f"Region {region.region_id} is {size:.1f}mm across -- under the "
                         f"{MIN_FEATURE_HEIGHT_MM:.0f}mm minimum feature size, so it "
                         f"won't read as what was drawn. Scale the design to at least "
                         f"{to_height:.0f}mm tall ({factor:.1f}x), or drop this region "
                         f"(it merges {into})."),
            ))
            continue

        if classification.stitch_type == FILL and 0 < narrowest < FILL_MIN_WIDTH_MM:
            factor = FILL_MIN_WIDTH_MM / narrowest
            to_height = design_height_mm * factor
            children = _children_in_holes(region, regions)
            widened = 0.0
            if children:
                widened = _narrowest_mm(Polygon(region.polygon.exterior))
            rows = max(1, int(narrowest / fabric.fill_row_spacing_mm))
            child_remedy = ""
            if children:
                child_remedy = (f", drop the {len(children)} region(s) inside it "
                                f"({', '.join(children)}) so it fills in to "
                                f"{widened:.1f}mm wide")
            issues.append(FeatureIssue(
                region_id=region.region_id, kind=TOO_NARROW,
                stitch_type=classification.stitch_type,
                size_mm=round(size, 2), narrowest_mm=round(narrowest, 2),
                needed_mm=FILL_MIN_WIDTH_MM,
                scale_factor=round(factor, 2), scale_to_height_mm=round(to_height, 1),
                merges_into=parent, children=children, widened_to_mm=round(widened, 2),
                message=(f"Region {region.region_id} (fill) is only {narrowest:.1f}mm "
                         f"across at its narrowest -- room for about {rows} fill "
                         f"row(s); it will sew as a ragged line. Scale the design to "
                         f"at least {to_height:.0f}mm tall ({factor:.1f}x)"
                         f"{child_remedy}, or drop this region (it merges {into})."),
            ))
    return issues
