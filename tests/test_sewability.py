"""The sewability audit (src/validate/audit.py) and the machine-facing
defects it was built to catch. Each regression test here pins a number
that was measured wrong on real fixture output before its fix.
"""
import math
import os

import pyembroidery as pe
import pytest

from src.io_.export import stitch_plan_to_pattern
from src.params.classify import classify_region
from src.params.presets import get_preset
from src.pipeline import load_scaled_region_set
from src.stitches.build import build_blocks_for_region
from src.stitches.model import (FILL, SATIN, UNDERLAY_RUN, StitchBlock, StitchPlan,
                                 ThreadColor)
from src.validate.audit import (MIN_STITCH_LENGTH_MM, SewabilityAudit,
                                audit_plan)

INPUTS = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs")


def _thread_mm(points) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def test_audit_counts_travel_from_the_command_stream():
    """A hand-built plan with known travel: one gap that jumps without
    a trim (4mm), one that trims (20mm). The audit must report exactly
    those from the exported command stream, and the entry penetration
    at each jump landing must not be counted as a 0mm stitch."""
    blocks = [
        StitchBlock(FILL, [(0, 0), (3, 0), (6, 0)], 0, "a"),
        StitchBlock(FILL, [(10, 0), (13, 0)], 0, "a"),            # 4mm gap: jump only
        StitchBlock(FILL, [(33, 0), (36, 0), (39, 0)], 0, "a"),   # 20mm gap: trim + jump
    ]
    plan = StitchPlan(blocks=blocks, colors=[ThreadColor("c")])
    audit = audit_plan(plan, get_preset("twill"), [])

    assert audit.jump_count == 2
    assert audit.trim_count == 1
    assert audit.total_jump_mm == pytest.approx(24.0)
    assert audit.longest_jump_mm == pytest.approx(20.0)
    assert audit.color_changes == 0
    assert audit.stitches_below_min == 0
    # The tie stitches, snapped to the file's 1/10mm grid.
    assert audit.stitch_min_mm >= MIN_STITCH_LENGTH_MM - 1e-9
    assert audit.problems() == []


def test_export_never_emits_a_stitch_under_the_machine_minimum():
    """Regression: every fixture's output carried sub-0.3mm stitches
    (2,021 on the cartoon face, shortest 0.00mm). Whatever a generator
    hands it, the export must not write one -- here a 0.1mm step in
    the middle of a run, and a block whose last point sits 0.05mm
    from the one before it (the block must still end at its own last
    point, not the one before)."""
    blocks = [
        StitchBlock(FILL, [(0, 0), (3, 0), (3.1, 0), (6, 0)], 0, "a"),
        StitchBlock(FILL, [(20, 0), (23, 0), (25.95, 0), (26, 0)], 0, "a"),
    ]
    plan = StitchPlan(blocks=blocks, colors=[ThreadColor("c")])
    audit = audit_plan(plan, get_preset("twill"), [])
    assert audit.stitches_below_min == 0

    pattern = stitch_plan_to_pattern(plan)
    needle_points = [(x / 10, y / 10) for x, y, cmd in pattern.stitches
                     if cmd & pe.COMMAND_MASK == pe.STITCH]
    assert (3.1, 0.0) not in needle_points
    assert (26.0, 0.0) in needle_points
    assert (25.95, 0.0) not in needle_points


def test_color_change_is_one_trim_and_a_jump_not_two_trims():
    """Regression: a color change wrote TRIM + COLOR_CHANGE and then,
    because the next color started more than 6mm away, a second TRIM
    -- so every color change counted (and ran) as two cuts. And when
    the next color started *under* 2mm away it wrote no JUMP at all,
    stitching the new thread from the old color's last point."""
    blocks = [
        StitchBlock(FILL, [(0, 0), (3, 0), (6, 0)], 0, "a"),
        StitchBlock(FILL, [(40, 0), (43, 0), (46, 0)], 1, "b"),   # far away
        StitchBlock(FILL, [(47, 0), (50, 0), (53, 0)], 2, "c"),   # 1mm away
    ]
    plan = StitchPlan(blocks=blocks, colors=[ThreadColor("x"), ThreadColor("y"), ThreadColor("z")])
    audit = audit_plan(plan, get_preset("twill"), [])
    assert audit.color_changes == 2
    assert audit.trim_count == 2
    assert audit.jump_count == 2


def test_audit_is_deterministic_for_the_same_plan():
    blocks = [StitchBlock(FILL, [(0, 0), (3, 0), (6, 0)], 0, "a"),
              StitchBlock(FILL, [(20, 0), (23, 0)], 0, "a")]
    plan = StitchPlan(blocks=blocks, colors=[ThreadColor("c")])
    first = audit_plan(plan, get_preset("twill"), [])
    again = audit_plan(plan, get_preset("twill"), [])
    assert first.to_dict() == again.to_dict()


def test_satin_bar_is_stitched_at_the_presets_density_not_four_times_it():
    """Regression: the satin bar fixture measured 21.9mm of thread per
    mm^2 against a 5.7 target -- the pixel-staircase skeleton's normals
    swung the offset rails into a 150mm zigzag along a 34mm column, and
    the stitch count followed the rail length. Rails must now run
    close to the column's true length and density must land near the
    preset's 2/satin_density."""
    fabric = get_preset("twill")
    region_set, _ = load_scaled_region_set(
        os.path.join(INPUTS, "bar_satin.png"), False, None, None)
    (region,) = region_set.regions
    classification = classify_region(region, fabric)
    assert classification.stitch_type == SATIN

    for rail_a, rail_b in classification.medial.branch_rails():
        chord = math.hypot(rail_a[-1][0] - rail_a[0][0], rail_a[-1][1] - rail_a[0][1])
        assert _thread_mm(rail_a) <= chord * 1.15
        assert _thread_mm(rail_b) <= chord * 1.15

    satin_thread = sum(_thread_mm(b.points_mm)
                       for b in build_blocks_for_region(region, classification, fabric)
                       if b.stitch_type == SATIN)
    density = satin_thread / region.polygon.area
    target = 2.0 / fabric.satin_density_mm
    assert target * 0.8 <= density <= target * 1.3


# --- sew order --------------------------------------------------------

def _gap(a: StitchBlock, b: StitchBlock) -> float:
    return math.hypot(b.points_mm[0][0] - a.points_mm[-1][0],
                      b.points_mm[0][1] - a.points_mm[-1][1])


def test_fill_colors_sew_before_outline_colors_largest_fill_first():
    """Regression: colors sewed in quantizer-label order, which on the
    cartoon face put the black outlines *under* the skin fill that
    followed them. Fills sew first (largest first); a color that is
    mostly satin/running detail sews last."""
    from src.pathing.order import color_sew_order
    blocks = [
        StitchBlock(SATIN, [(0, 0), (0, 3), (1, 0), (1, 3)], 0, "outline"),   # color 0: outline
        StitchBlock(FILL, [(0, 0), (10, 0), (10, 0.4), (0, 0.4)], 1, "small"),  # color 1: small fill
        StitchBlock(FILL, [(0, 0), (50, 0), (50, 0.4), (0, 0.4), (0, 0.8), (50, 0.8)], 2, "big"),
    ]
    assert color_sew_order(blocks) == [2, 1, 0]


def test_each_element_finishes_before_the_next_starts():
    """Regression: within a color, every element's underlay sewed
    first and then every element's top stitching -- a word was
    crossed twice, doubling its trims. Two letters 40mm apart: the
    needle must not leave letter A until A's satin is done."""
    from src.pathing.order import order_by_color_then_distance
    a_under = StitchBlock(UNDERLAY_RUN, [(0, 0), (0, 10)], 0, "A")
    a_top = StitchBlock(SATIN, [(0, 10), (1, 10), (0, 0), (1, 0)], 0, "A")
    b_under = StitchBlock(UNDERLAY_RUN, [(40, 0), (40, 10)], 0, "B")
    b_top = StitchBlock(SATIN, [(40, 10), (41, 10), (40, 0), (41, 0)], 0, "B")
    ordered = order_by_color_then_distance([a_under, b_under, a_top, b_top],
                                           z_order_by_element={"A": 0, "B": 0})
    assert [b.element_id for b in ordered] == ["A", "A", "B", "B"]
    assert [b.stitch_type for b in ordered] == [UNDERLAY_RUN, SATIN, UNDERLAY_RUN, SATIN]


def test_same_layer_elements_sew_nearest_first_not_discovery_order():
    """Three letters listed C, A, B (contour-discovery order) but laid
    out A B C left to right must sew A, B, C from a needle at the
    origin."""
    from src.pathing.order import order_by_color_then_distance
    def letter(name, x):
        return StitchBlock(SATIN, [(x, 0), (x + 1, 0), (x, 8), (x + 1, 8)], 0, name)
    ordered = order_by_color_then_distance(
        [letter("C", 40), letter("A", 0), letter("B", 20)],
        z_order_by_element={"A": 0, "B": 0, "C": 0})
    assert [b.element_id for b in ordered] == ["A", "B", "C"]


def test_explicit_layer_order_still_wins_over_proximity():
    from src.pathing.order import order_by_color_then_distance
    near = StitchBlock(FILL, [(0, 0), (5, 0)], 0, "near")
    far = StitchBlock(FILL, [(50, 0), (55, 0)], 0, "far")
    ordered = order_by_color_then_distance([near, far],
                                           z_order_by_element={"near": 5, "far": 1})
    assert [b.element_id for b in ordered] == ["far", "near"]


def test_branching_satin_network_sews_as_one_continuous_pass():
    """Regression: a bold "H" trimmed between its own three strokes,
    and 54 of the cartoon face's 88 trims were inside single elements.
    A network now travels down each branch and satins back, so no two
    consecutive blocks inside the element are apart by more than a
    stitch, and every branch is both travelled and satined."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    from src.regions.model import Region
    h_shape = unary_union([box(0, 0, 3, 20), box(9, 0, 12, 20), box(0, 8.5, 12, 11.5)])
    region = Region(polygon=h_shape, color_index=0, region_id="H")
    fabric = get_preset("twill")
    classification = classify_region(region, fabric)
    assert classification.stitch_type == SATIN
    assert len(classification.medial.branch_columns()) > 1

    blocks = build_blocks_for_region(region, classification, fabric)
    assert all(b.sequence is not None for b in blocks)
    # Every link starts exactly where the last one ended.
    assert max(_gap(a, b) for a, b in zip(blocks, blocks[1:])) < 1e-6
    n_travel = sum(1 for b in blocks if b.stitch_type == "underlay_satin")
    n_satin = sum(1 for b in blocks if b.stitch_type == SATIN)
    assert n_travel == n_satin == len(classification.medial.branch_columns())


def test_two_runs_of_the_same_input_produce_identical_bytes(tmp_path):
    """The whole pipeline, twice, on a real multi-letter fixture: the
    DST and PES files must match byte for byte."""
    from src.pipeline import digitize_image
    src = os.path.join(INPUTS, "text_with_bowls.png")
    first = digitize_image(src, "twill", str(tmp_path / "first"))
    second = digitize_image(src, "twill", str(tmp_path / "second"))
    for key in ("dst", "pes"):
        with open(first[key], "rb") as f1, open(second[key], "rb") as f2:
            assert f1.read() == f2.read()


# --- small-feature policy ----------------------------------------------

def test_size_floor_judges_the_feature_not_its_height():
    """Regression: the floor was judged on bounding-box height alone,
    so a 35mm horizontal stroke 5mm tall was rejected while the same
    stroke standing upright passed. A 4mm dot is still rejected, and
    the rejection now says what size fixes it."""
    from src.regions.scope import check_min_feature_size
    assert check_min_feature_size([35.0, 12.0], design_height_mm=40.0) is None
    finding = check_min_feature_size([4.0, 30.0], design_height_mm=40.0)
    assert finding is not None and finding.reject
    assert "60mm tall (1.5x)" in finding.message


def test_feature_report_names_the_remedy_for_each_unrenderable_region():
    """A 5mm dot inside a hole of a 30mm disc, plus a disc whose
    highlight cut-out leaves a 1mm ring: the report must say the dot
    is too small (scale factor 1.2 to reach 6mm, merges into the
    disc) and the ring is too narrow (drop the child to widen it)."""
    from shapely.geometry import Point as P, Polygon
    from src.regions.model import Region
    from src.validate.features import TOO_NARROW, TOO_SMALL, assess_features
    fabric = get_preset("twill")
    dot = P(0, 0).buffer(2.5)
    disc = Polygon(P(0, 0).buffer(15).exterior, [P(0, 0).buffer(3.5).exterior.coords])
    ring = Polygon(P(50, 0).buffer(4).exterior, [P(50, 0).buffer(3).exterior.coords])
    highlight = P(50, 0).buffer(2.5)
    regions = [Region(disc, 0, region_id="disc"), Region(dot, 1, region_id="dot"),
               Region(ring, 2, region_id="ring"), Region(highlight, 3, region_id="glint")]
    classified = [(r, classify_region(r, fabric)) for r in regions]
    # The policy judges a *fill* by its band width; a 1mm ring the
    # classifier would satin is fine as satin, so pin it as fill here
    # (what a human's stitch-type override would do) to test the
    # narrow-fill remedy itself.
    from dataclasses import replace
    classified = [(r, replace(c, stitch_type=FILL) if r.region_id == "ring" else c)
                  for r, c in classified]

    issues = {i.region_id: i for i in assess_features(classified, 30.0, fabric)}
    assert "disc" not in issues
    assert issues["dot"].kind == TOO_SMALL
    assert issues["dot"].scale_factor == pytest.approx(1.2, abs=0.01)
    assert issues["dot"].scale_to_height_mm == pytest.approx(36.0, abs=0.5)
    assert issues["dot"].merges_into == "disc"
    assert "36mm tall" in issues["dot"].message

    assert issues["ring"].kind == TOO_NARROW
    assert issues["ring"].children == ["glint"]
    assert issues["ring"].widened_to_mm == pytest.approx(8.0, abs=0.2)
    assert "drop the 1 region(s) inside it (glint)" in issues["ring"].message


def test_dropping_a_region_is_a_human_choice_that_fills_the_hole_it_sat_in(tmp_path):
    """Nothing is dropped without a RegionOverride.drop; with one, the
    dropped region produces no stitches and the region whose hole it
    sat in is filled straight over it."""
    from shapely.geometry import Point as P, Polygon
    from src.pipeline import build_and_export
    from src.regions.model import Region, RegionSet
    from src.review.corrections import RegionOverride
    fabric = get_preset("twill")
    disc = Polygon(P(0, 0).buffer(15).exterior, [P(0, 0).buffer(3.5).exterior.coords])
    dot = P(0, 0).buffer(2.5)
    region_set = RegionSet(
        regions=[Region(disc, 0, region_id="disc"), Region(dot, 1, region_id="dot")],
        colors=[ThreadColor("navy", (0, 0, 80)), ThreadColor("white", (255, 255, 255))],
        width_mm=30, height_mm=30)

    kept = build_and_export(region_set, fabric, str(tmp_path / "kept"), 0.0, [])
    assert [i["region_id"] for i in kept["feature_issues"]] == ["dot"]
    assert kept["summary"]["thread_colors_selected"] == 2
    assert not any(r["dropped"] for r in kept["regions"])

    dropped = build_and_export(region_set, fabric, str(tmp_path / "dropped"), 0.0, [],
                               corrections={"dot": RegionOverride(drop=True)})
    meta = {r["id"]: r for r in dropped["regions"]}
    assert meta["dot"]["dropped"] and meta["dot"]["corrected"]
    assert dropped["feature_issues"] == []
    assert dropped["corrections_applied"] == ["dot"]
    # The disc's hole is filled: more fill stitches, and the dot's
    # color never sews (one color in the file, no color change).
    assert dropped["stitch_count"] > kept["stitch_count"] - 100
    assert dropped["audit"]["color_changes"] == 0
    assert kept["audit"]["color_changes"] == 1
    disc_audit = next(r for r in dropped["audit"]["regions"] if r["region_id"] == "disc")
    disc_before = next(r for r in kept["audit"]["regions"] if r["region_id"] == "disc")
    assert disc_audit["area_mm2"] > disc_before["area_mm2"] + 30


# --- stitch physics ------------------------------------------------------

def test_wide_satin_is_split_so_no_stitch_exceeds_the_machine_maximum():
    """Regression: an 8mm-wide satin stroke on the cartoon face wrote
    123 stitches over the 7mm practical maximum. Each crossing of a
    wide column now carries staggered intermediate penetrations."""
    from src.stitches.satin import generate_satin
    from src.stitches.model import MAX_STITCH_LENGTH_MM
    rail_a = [(x, 0.0) for x in range(0, 31, 5)]
    rail_b = [(x, 9.0) for x in range(0, 31, 5)]
    points = generate_satin(rail_a, rail_b, density_mm=0.4)
    longest = max(_thread_mm([p, q]) for p, q in zip(points, points[1:]))
    assert longest <= MAX_STITCH_LENGTH_MM
    # Still spans the full column: every crossing reaches both rails.
    assert min(y for _, y in points) == pytest.approx(0.0, abs=0.01)
    assert max(y for _, y in points) == pytest.approx(9.0, abs=0.01)
    # Split points are staggered, not lined up into a seam.
    mids = sorted({round(y, 1) for _, y in points if 0.5 < y < 8.5})
    assert len(mids) >= 3


def test_fill_rows_are_pull_compensated_along_the_stitch_direction():
    """Fills had no pull compensation (satin did). Rows at 0 degrees
    across a 20mm square must extend past the drawn edge along x by
    half the compensation each side, and not at all along y."""
    from shapely.geometry import box
    from src.stitches.fill import generate_fill
    square = box(0, 0, 20, 20)
    plain = [p for run in generate_fill(square, 0.0, 0.4, 3.0) for p in run]
    comp = [p for run in generate_fill(square, 0.0, 0.4, 3.0, pull_compensation_mm=0.6) for p in run]
    assert max(x for x, _ in plain) == pytest.approx(20.0, abs=0.01)
    assert max(x for x, _ in comp) == pytest.approx(20.3, abs=0.01)
    assert min(x for x, _ in comp) == pytest.approx(-0.3, abs=0.01)
    assert max(y for _, y in comp) <= 20.0 + 1e-6
    assert min(y for _, y in comp) >= 0.0 - 1e-6


def test_the_written_file_has_no_sub_minimum_stitch(tmp_path):
    """Regression, and the reason testbench/check_dst.py exists: the
    audit measured the in-memory plan, but a file stores coordinates
    on a 1/10mm grid. A 0.30mm stitch running at 45 degrees has
    0.212mm components, each of which snaps to 0.2mm -- a 0.283mm
    stitch in the delivered file. The cartoon face shipped 125 of them
    while the audit reported zero. Measured here on the DST read back
    off disk, which is what the machine runs."""
    import pyembroidery as pe
    from src.pipeline import digitize_image
    out_stem = str(tmp_path / "out")
    digitize_image(os.path.join(INPUTS, "text_with_bowls.png"), "twill", out_stem)

    pattern = pe.EmbPattern.read_dst(f"{out_stem}.dst")
    prev = None
    shortest = None
    for x, y, cmd in pattern.stitches:
        kind = cmd & pe.COMMAND_MASK
        if kind == pe.STITCH:
            if prev is not None:
                length = math.hypot(x - prev[0], y - prev[1]) / 10.0
                shortest = length if shortest is None else min(shortest, length)
            prev = (x, y)
        elif kind == pe.JUMP:
            prev = None   # the entry point after a jump is not a stitch
    assert shortest is not None
    assert shortest >= MIN_STITCH_LENGTH_MM - 1e-9, (
        f"written DST contains a {shortest:.3f}mm stitch")


def test_short_stitches_spread_the_inner_edge_of_a_tight_curve():
    """Regression: on a curve the inner rail is shorter than the outer,
    so evenly spaced crossings pile their inner needle points on top of
    one another -- measured to 0.013mm apart on a letter bowl, and
    invisible to the minimum-stitch guard because those two points are
    not consecutive in stitch order. On fabric that perforates the
    inner edge until the thread cuts it.

    A tight arc here: without short stitches a quarter of the inner
    penetrations land closer than the machine minimum."""
    import math as _m
    from src.stitches.satin import generate_satin
    radius, width, sweep = 3.0, 2.0, _m.pi
    n = 60
    inner = [((radius - width / 2) * _m.cos(sweep * i / n),
              (radius - width / 2) * _m.sin(sweep * i / n)) for i in range(n + 1)]
    outer = [((radius + width / 2) * _m.cos(sweep * i / n),
              (radius + width / 2) * _m.sin(sweep * i / n)) for i in range(n + 1)]

    points = generate_satin(inner, outer, density_mm=0.35)
    inner_side = points[0::2]
    gaps = [_m.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(inner_side, inner_side[1:])]
    assert min(gaps) >= MIN_STITCH_LENGTH_MM * 0.9, (
        f"inner edge still bunches to {min(gaps):.3f}mm")

    # The column must still be covered: the outer edge is untouched, and
    # every crossing still reaches it.
    outer_side = points[1::2]
    outer_radii = [_m.hypot(x, y) for x, y in outer_side]
    assert min(outer_radii) >= radius + width / 2 - 0.05


def test_satin_density_target_accounts_for_pull_compensation():
    """The audit judged satin against a bare 2/density, which ignores
    pull compensation -- real thread the preset asked for, and 13% of
    the total on a 1.1mm letter stroke. Ten narrow strokes across two
    fixtures were reported over-dense while doing exactly as told."""
    from src.validate.audit import _target_density
    fabric = get_preset("twill")
    bare = 2.0 / fabric.satin_density_mm
    assert _target_density(SATIN, fabric, None, False, width_mm=0.0) == pytest.approx(bare)
    narrow = _target_density(SATIN, fabric, None, False, width_mm=1.1)
    wide = _target_density(SATIN, fabric, None, False, width_mm=6.0)
    assert narrow > wide > bare
    assert narrow == pytest.approx(bare * (1.1 + fabric.pull_compensation_mm) / 1.1)
