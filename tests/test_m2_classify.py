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


# -- curved satin outlines ------------------------------------------------

def _ring(r_outer, r_inner):
    return (Point(0, 0).buffer(r_outer, quad_segs=64)
            .difference(Point(0, 0).buffer(r_inner, quad_segs=64)))


def test_curved_outline_ring_is_satin_not_fill():
    """The headline case for line art: a curved constant-width stroke.
    The rectangularity test can only ever pass for a *straight* band --
    a curve fills almost none of its own bounding rectangle -- so every
    outline on a real cartoon face (head oval, eyebrows, smile, hair
    strands, measured at elongation 14x-30x with rectangularity
    0.04-0.30) fell through to fill and came out as a mushy blob
    instead of a crisp line. Outlining a curve with satin is *the*
    line-art digitizing technique."""
    fabric = get_preset("twill")
    region = Region(polygon=_ring(20.0, 18.5), color_index=0, region_id="outline")
    c = classify_region(region, fabric)
    assert c.stitch_type == SATIN
    assert "curve" in c.reason


def test_branching_outline_network_gets_a_column_per_stroke():
    """Line art doesn't extract as tidy separate strokes: every outline
    touches its neighbours, so a whole black layer comes out as ONE
    connected branching region. A single satin column can only trace
    one path through that (33% of the skeleton on the real fixture),
    so the strokes are split at their junctions and each gets its own
    column."""
    fabric = get_preset("twill")
    # Two strokes crossing: thin, constant width, clearly not a blob.
    bar_h = Polygon([(0, 9), (40, 9), (40, 11), (0, 11)])
    bar_v = Polygon([(19, 0), (21, 0), (21, 20), (19, 20)])
    region = Region(polygon=bar_h.union(bar_v), color_index=0, region_id="cross")
    c = classify_region(region, fabric)
    assert c.stitch_type == SATIN
    assert len(c.medial.branch_rails()) >= 2, "each stroke needs its own column"


def test_satin_is_only_chosen_when_it_covers_the_whole_stroke():
    """Satin that covers only part of a shape is worse than filling it:
    a letter "o" whose ring skeleton couldn't be reassembled into one
    loop came out stitched as a "c". Anything the columns can't fully
    cover must fall back to fill, which covers everything by
    construction."""
    fabric = get_preset("twill")
    for poly, name in ((_ring(20.0, 18.5), "outline ring"),
                        (Polygon([(0, 0), (40, 0), (40, 4), (0, 4)]), "straight band")):
        c = classify_region(Region(polygon=poly, color_index=0, region_id=name), fabric)
        if c.stitch_type == SATIN:
            assert c.medial.stitchable_coverage() >= 0.85, (
                f"{name}: satin chosen but only covers "
                f"{c.medial.stitchable_coverage():.0%} of the stroke")


def test_stubby_branching_shapes_still_fill():
    """The guard the rectangularity test used to provide, kept
    explicitly: a shape whose branches are as wide as they are long is
    not a stroke network, however much its total skeleton adds up."""
    fabric = get_preset("twill")
    plus = Polygon([(8, 0), (16, 0), (16, 8), (24, 8), (24, 16), (16, 16),
                    (16, 24), (8, 24), (8, 16), (0, 16), (0, 8), (8, 8)])
    c = classify_region(Region(polygon=plus, color_index=0, region_id="plus"), fabric)
    assert c.stitch_type == FILL
