"""M0 golden-file test: hand-built circle -> DST/PES -> readback structure.

This is the spine acceptance test from the build spec: it proves a real,
sew-able file comes out the other end, not just a plausible-looking
preview. If pyembroidery can't read back what we wrote, the milestone
isn't done.
"""
import pyembroidery as pe
import pytest

from src.io_.export import write_pattern
from src.params.presets import get_preset
from src.pathing.order import order_by_color_then_distance
from src.stitches.model import StitchPlan
from src.stitches.shapes import DEMO_THREAD, build_demo_blocks

# Golden values for the M0 demo circle on the twill preset. A tolerance
# window rather than an exact match, since fill point count is sensitive
# to floating point row-walking, not to anything semantically wrong.
# Re-centred from 910 when the perimeter underlay stopped keeping every
# one of the circle polygon's vertices as a needle point (sub-minimum
# stitches -- see src/stitches/running.py); the fill itself is unchanged.
EXPECTED_STITCH_COUNT = 655
STITCH_COUNT_TOLERANCE = 40
EXPECTED_RADIUS_MM = 15.0
BOUNDS_TOLERANCE_MM = 0.5


def _build_demo_plan(fabric_name="twill"):
    fabric = get_preset(fabric_name)
    blocks = build_demo_blocks("circle", fabric)
    ordered = order_by_color_then_distance(blocks)
    return StitchPlan(blocks=ordered, colors=[DEMO_THREAD])


def test_demo_plan_stitch_count_in_range():
    plan = _build_demo_plan()
    assert abs(plan.stitch_count() - EXPECTED_STITCH_COUNT) <= STITCH_COUNT_TOLERANCE


def test_demo_plan_bounds_match_circle_radius():
    plan = _build_demo_plan()
    minx, miny, maxx, maxy = plan.bounds_mm()
    assert minx == pytest.approx(-EXPECTED_RADIUS_MM, abs=BOUNDS_TOLERANCE_MM)
    assert miny == pytest.approx(-EXPECTED_RADIUS_MM, abs=BOUNDS_TOLERANCE_MM)
    assert maxx == pytest.approx(EXPECTED_RADIUS_MM, abs=BOUNDS_TOLERANCE_MM)
    assert maxy == pytest.approx(EXPECTED_RADIUS_MM, abs=BOUNDS_TOLERANCE_MM)


def test_dst_and_pes_round_trip(tmp_path):
    plan = _build_demo_plan()
    out_stem = str(tmp_path / "demo")
    paths = write_pattern(plan, out_stem)

    dst = pe.EmbPattern.read_dst(paths["dst"])
    pes = pe.EmbPattern.read_pes(paths["pes"])

    # A single-color design should read back with zero color changes and
    # a stitch count matching what we asked pyembroidery to write, within
    # rounding from the mm -> 1/10mm unit conversion plus the JUMP/TRIM
    # and tie-in/tie-out lock stitches (src/io_/export.py) a real cut
    # between this demo's underlay and fill blocks adds -- neither is
    # part of plan.stitch_count() (which only counts StitchBlock points).
    assert dst.count_color_changes() == 0
    assert pes.count_color_changes() == 0
    assert abs(len(dst.stitches) - plan.stitch_count()) <= 10
    assert abs(len(pes.stitches) - plan.stitch_count()) <= 10

    minx, miny, maxx, maxy = (v / 10 for v in dst.bounds())
    assert minx == pytest.approx(-EXPECTED_RADIUS_MM, abs=BOUNDS_TOLERANCE_MM)
    assert maxx == pytest.approx(EXPECTED_RADIUS_MM, abs=BOUNDS_TOLERANCE_MM)


def test_multi_color_plan_gets_color_change(tmp_path):
    """Two blocks with different color_index must produce exactly one
    COLOR_CHANGE command when written out."""
    fabric = get_preset("twill")
    blocks_a = build_demo_blocks("circle", fabric)
    for b in blocks_a:
        b.color_index = 0
    blocks_b = build_demo_blocks("circle", fabric)
    for b in blocks_b:
        b.color_index = 1
        b.points_mm = [(x + 40, y) for x, y in b.points_mm]

    ordered = order_by_color_then_distance(blocks_a + blocks_b)
    plan = StitchPlan(blocks=ordered, colors=[DEMO_THREAD, DEMO_THREAD])

    out_stem = str(tmp_path / "two_color")
    paths = write_pattern(plan, out_stem)
    dst = pe.EmbPattern.read_dst(paths["dst"])
    assert dst.count_color_changes() == 1
