"""force_trim_before (manual "cut the scissors here" override, Section 5
follow-up): a region correction that forces the machine's thread
trimmer to fire at a specific point regardless of the automatic
distance-based rule."""
import pyembroidery as pe

from src.io_.export import stitch_plan_to_pattern
from src.jobs import JobSpec
from src.pathing.route import TRIM_THRESHOLD_MM
from src.review.corrections import CorrectionValidationError, parse_region_override
from src.review.rebuild import rebuild_job
from src.stitches.model import RUNNING, StitchBlock, StitchPlan, ThreadColor


def _close_blocks(force_trim_before: bool) -> StitchPlan:
    gap = TRIM_THRESHOLD_MM / 2  # well under the automatic trim threshold
    a = StitchBlock(RUNNING, [(0.0, 0.0), (2.0, 0.0)], color_index=0, element_id="a")
    b = StitchBlock(RUNNING, [(2.0 + gap, 0.0), (4.0 + gap, 0.0)], color_index=0,
                     element_id="b", force_trim_before=force_trim_before)
    return StitchPlan(blocks=[a, b], colors=[ThreadColor(name="c", rgb=(10, 10, 10))])


def test_close_blocks_do_not_trim_by_default():
    pattern = stitch_plan_to_pattern(_close_blocks(force_trim_before=False))
    kinds = [cmd & pe.COMMAND_MASK for _x, _y, cmd in pattern.stitches]
    assert pe.TRIM not in kinds


def test_force_trim_before_cuts_despite_short_gap():
    pattern = stitch_plan_to_pattern(_close_blocks(force_trim_before=True))
    kinds = [cmd & pe.COMMAND_MASK for _x, _y, cmd in pattern.stitches]
    assert pe.TRIM in kinds


def test_parse_force_trim_tri_state():
    assert parse_region_override({"force_trim": ""}).force_trim is None
    assert parse_region_override({"force_trim": "on"}).force_trim is True
    assert parse_region_override({"force_trim": "off"}).force_trim is False


def test_parse_force_trim_rejects_garbage():
    import pytest
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"force_trim": "maybe"})


def test_result_reports_trim_count(tmp_path):
    import os
    star = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs", "star_3color.png")
    spec = JobSpec(input_path=star, fabric="twill")
    result = rebuild_job(spec, str(tmp_path / "star"))
    assert isinstance(result["trim_count"], int)
    assert result["trim_count"] >= 0
