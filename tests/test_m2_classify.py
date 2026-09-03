"""M2: stitch assignment rules, tested against clean synthetic shapes
(not raster-derived) so results aren't sensitive to rasterization noise."""
from shapely.geometry import Point, Polygon

from src.params.classify import classify_region
from src.params.presets import get_preset
from src.regions.model import Region
from src.stitches.model import FILL, RUNNING, SATIN


def _rect_region(w_mm, h_mm, color=0):
    poly = Polygon([(0, 0), (w_mm, 0), (w_mm, h_mm), (0, h_mm)])
    return Region(polygon=poly, color_index=color, region_id="test-rect")


def test_thin_long_rectangle_is_satin():
    fabric = get_preset("twill")
    region = _rect_region(40.0, 4.0)  # long, narrow -> classic satin band
    c = classify_region(region, fabric)
    assert c.stitch_type == SATIN
    assert not c.redirected_from_satin


def test_wide_square_is_fill():
    fabric = get_preset("twill")
    region = _rect_region(20.0, 20.0)  # blobby -> fill
    c = classify_region(region, fabric)
    assert c.stitch_type == FILL


def test_hairline_stroke_is_running():
    fabric = get_preset("twill")
    region = _rect_region(30.0, 0.6)  # sub-1.2mm wide -> running stitch
    c = classify_region(region, fabric)
    assert c.stitch_type == RUNNING


def test_satin_too_wide_for_preset_redirects_to_fill():
    fabric = get_preset("twill")  # satin_max_width_mm = 12.0
    region = _rect_region(50.0, 15.0)  # elongated but too wide
    c = classify_region(region, fabric)
    assert c.stitch_type == FILL
    assert c.redirected_from_satin


def test_satin_rails_span_expected_width():
    fabric = get_preset("twill")
    region = _rect_region(40.0, 4.0)
    c = classify_region(region, fabric)
    rail_a, rail_b = c.medial.rails()
    assert len(rail_a) == len(rail_b) > 2
    # rails should roughly bracket the 4mm rectangle width
    import math
    widths = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(rail_a, rail_b)]
    assert 2.5 <= sum(widths) / len(widths) <= 5.5


def test_winding_line_art_is_running_despite_wide_bounding_box():
    """A thin stroke that winds within a roughly-square bounding box (a
    line-art squiggle, not unlike a spiral) should be running stitch --
    its bounding-rectangle elongation alone doesn't say so, but its true
    width (area over the full medial-axis skeleton length, not just one
    walked path) does. This is the milestone's "line-art detection"
    (Multi-Region Illustration Digitization, item 6)."""
    import math
    fabric = get_preset("twill")
    xs = [i * 40.0 / 200 for i in range(201)]
    ys = [8 * math.sin(x / 40 * 4 * math.pi) for x in xs]
    width = 1.5
    top = [(x, y + width / 2) for x, y in zip(xs, ys)]
    bottom = [(x, y - width / 2) for x, y in zip(reversed(xs), reversed(ys))]
    ribbon = Polygon(top + bottom).buffer(0)
    region = Region(polygon=ribbon, color_index=0, region_id="ribbon")
    c = classify_region(region, fabric)
    assert c.stitch_type == RUNNING


def test_letter_bowl_with_hole_is_fill_not_running():
    """Regression test for a real bug: a region with a hole (a letter
    bowl like "e"/"o"/"d", at ordinary small-text proportions) has a
    closed-loop medial axis that pixel-level rasterization jaggedness
    can inflate -- spur pruning only cleans dead-end branches, not loop
    waviness -- which was systematically *underestimating* the
    true-width-via-skeleton-length line-art check (Multi-Region
    Illustration Digitization's line-art detection) for exactly this
    shape, misclassifying ordinary bowled letters as thin running-
    stitch line art instead of a filled glyph. classify_region must
    skip that check entirely for any region with a hole."""
    fabric = get_preset("twill")
    outer = Point(0, 0).buffer(3.2, quad_segs=32)
    inner = Point(0, 0).buffer(1.9, quad_segs=32)  # ~1.3mm stroke width
    bowl = Region(polygon=outer.difference(inner), color_index=0, region_id="bowl")
    c = classify_region(bowl, fabric)
    assert c.stitch_type == FILL


def test_confidence_is_bounded_and_reason_is_set():
    fabric = get_preset("twill")
    for region in (_rect_region(40.0, 4.0), _rect_region(20.0, 20.0),
                    _rect_region(30.0, 0.6), _rect_region(50.0, 15.0)):
        c = classify_region(region, fabric)
        assert 0.0 <= c.confidence <= 1.0
        assert c.reason


def test_angle_follows_long_axis_not_bounding_box():
    """A rectangle rotated 30 degrees should report an angle near 30 (mod
    180), not 0/90 -- proves angle comes from the medial axis, not the
    axis-aligned bounding box (Section 9)."""
    import math
    fabric = get_preset("twill")
    w, h = 40.0, 4.0
    theta = math.radians(30)
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    rotated = [(x * math.cos(theta) - y * math.sin(theta),
                x * math.sin(theta) + y * math.cos(theta)) for x, y in corners]
    region = Region(polygon=Polygon(rotated), color_index=0, region_id="rot")
    c = classify_region(region, fabric)
    assert c.stitch_type == SATIN
    angle_mod_180 = c.angle_deg % 180
    diff = min(abs(angle_mod_180 - 30), abs(angle_mod_180 - 30 - 180))
    assert diff < 8.0
