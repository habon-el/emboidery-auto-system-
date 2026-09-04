"""Tie-in/tie-out lock stitches (src/io_/export.py): a real gap in the
previous fill/satin/running pipeline -- every TRIM used to cut a bare
thread end with nothing anchoring it, which is how a trimmed end works
loose off the machine. Real digitizing software's standard practice
(and this project's own embroidery-research doc, step 6: tie-out ->
trim -> jump -> tie-in) is a tiny there-and-back stitch right at every
cut, on both sides of it."""
import pytest
import pyembroidery as pe

from src.io_.export import TIE_STITCH_LENGTH_MM, stitch_plan_to_pattern
from src.io_.units import quantize_mm
from src.pathing.route import TRIM_THRESHOLD_MM
from src.stitches.model import RUNNING, StitchBlock, StitchPlan, ThreadColor

THREAD = ThreadColor(name="c", rgb=(10, 10, 10))


def _kinds_and_points(pattern):
    return [((x / 10, y / 10), cmd & pe.COMMAND_MASK) for x, y, cmd in pattern.stitches]


def test_no_tie_stitches_when_nothing_is_trimmed():
    """A plain jump (gap under the trim threshold) is still the same
    physically continuous thread -- nothing to anchor, so the stitch
    count should be exactly the two blocks' own points plus one JUMP,
    no extra tie stitches."""
    gap = TRIM_THRESHOLD_MM / 2
    a = StitchBlock(RUNNING, [(0.0, 0.0), (2.0, 0.0)], color_index=0, element_id="a")
    b = StitchBlock(RUNNING, [(2.0 + gap, 0.0), (4.0 + gap, 0.0)], color_index=0, element_id="b")
    plan = StitchPlan(blocks=[a, b], colors=[THREAD])
    pattern = stitch_plan_to_pattern(plan)
    kinds = [cmd & pe.COMMAND_MASK for _x, _y, cmd in pattern.stitches]
    assert pe.TRIM not in kinds
    # 2 + 2 real points, 1 JUMP, 1 END -- no tie stitches inflate this.
    assert len(pattern.stitches) == 6  # a0, a1, JUMP, b0, b1, END


def test_tie_out_backtracks_then_returns_to_the_cut_point():
    gap = TRIM_THRESHOLD_MM + 1
    a = StitchBlock(RUNNING, [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0)], color_index=0, element_id="a")
    b = StitchBlock(RUNNING, [(4.0 + gap, 0.0), (6.0 + gap, 0.0)], color_index=0, element_id="b")
    plan = StitchPlan(blocks=[a, b], colors=[THREAD])
    pattern = stitch_plan_to_pattern(plan)
    points = _kinds_and_points(pattern)

    trim_idx = next(i for i, (_pt, k) in enumerate(points) if k == pe.TRIM)
    # The two stitches right before the TRIM are the tie-out: a small
    # step backward along the direction of travel, then back to the
    # exact point that gets cut.
    (back_pt, back_kind), (cut_pt, cut_kind) = points[trim_idx - 2], points[trim_idx - 1]
    assert back_kind == pe.STITCH and cut_kind == pe.STITCH
    assert cut_pt == (4.0, 0.0)  # the actual last point of block a
    # Snapped to the file's 1/10mm grid, like every written
    # coordinate (src/io_/units.py's quantize_mm).
    assert back_pt[0] == pytest.approx(quantize_mm(4.0 - TIE_STITCH_LENGTH_MM))
    assert points[trim_idx][0] == (4.0, 0.0)  # TRIM fires at the cut point


def test_tie_in_steps_forward_then_returns_to_the_entry_point():
    gap = TRIM_THRESHOLD_MM + 1
    a = StitchBlock(RUNNING, [(0.0, 0.0), (2.0, 0.0)], color_index=0, element_id="a")
    entry = 2.0 + gap
    b = StitchBlock(RUNNING, [(entry, 0.0), (entry + 2.0, 0.0)], color_index=0, element_id="b")
    plan = StitchPlan(blocks=[a, b], colors=[THREAD])
    pattern = stitch_plan_to_pattern(plan)
    points = _kinds_and_points(pattern)

    jump_idx = next(i for i, (_pt, k) in enumerate(points) if k == pe.JUMP)
    assert points[jump_idx][0] == (entry, 0.0)
    (fwd_pt, fwd_kind), (back_pt, back_kind) = points[jump_idx + 1], points[jump_idx + 2]
    assert fwd_kind == pe.STITCH and back_kind == pe.STITCH
    assert back_pt == (entry, 0.0)  # returns exactly to the entry point
    assert fwd_pt[0] == pytest.approx(quantize_mm(entry + TIE_STITCH_LENGTH_MM))
    # The block's real second point still follows, unchanged.
    assert points[jump_idx + 3] == ((entry + 2.0, 0.0), pe.STITCH)


def test_color_change_trim_also_gets_tie_out_and_tie_in():
    a = StitchBlock(RUNNING, [(0.0, 0.0), (2.0, 0.0)], color_index=0, element_id="a")
    b = StitchBlock(RUNNING, [(2.0, 0.0), (4.0, 0.0)], color_index=1, element_id="b")
    plan = StitchPlan(blocks=[a, b], colors=[THREAD, THREAD])
    pattern = stitch_plan_to_pattern(plan)
    kinds = [cmd & pe.COMMAND_MASK for _x, _y, cmd in pattern.stitches]
    assert kinds.count(pe.TRIM) >= 1
    assert kinds.count(pe.COLOR_CHANGE) == 1
    # Extra tie stitches around the color-change cut, beyond the two
    # blocks' own 4 real points.
    assert len(pattern.stitches) > 4 + 1 + 1  # +TRIM +COLOR_CHANGE, plus ties


def test_no_double_tie_out_when_color_change_and_distance_trim_coincide():
    """A color change always trims; if the following block also happens
    to be far enough away to trigger the automatic distance-trim too,
    the same cut shouldn't get tied out twice."""
    gap = TRIM_THRESHOLD_MM + 1
    a = StitchBlock(RUNNING, [(0.0, 0.0), (2.0, 0.0)], color_index=0, element_id="a")
    b = StitchBlock(RUNNING, [(2.0 + gap, 0.0), (4.0 + gap, 0.0)], color_index=1, element_id="b")
    plan = StitchPlan(blocks=[a, b], colors=[THREAD, THREAD])
    pattern = stitch_plan_to_pattern(plan)
    points = _kinds_and_points(pattern)
    # Exactly one tie-out pair (the two STITCH commands immediately
    # before the TRIM) -- not two, even though both the color change
    # and the distance rule call for a cut at this same transition.
    trim_idx = next(i for i, (_pt, k) in enumerate(points) if k == pe.TRIM)
    (back_pt, back_kind), (cut_pt, cut_kind) = points[trim_idx - 2], points[trim_idx - 1]
    assert back_kind == pe.STITCH and cut_kind == pe.STITCH
    assert cut_pt == (2.0, 0.0)
    assert back_pt == pytest.approx((quantize_mm(2.0 - TIE_STITCH_LENGTH_MM), 0.0))
    # And the point right before that pair is block a's own real last
    # stitch, not a second tie-out.
    assert points[trim_idx - 3] == ((2.0, 0.0), pe.STITCH)
