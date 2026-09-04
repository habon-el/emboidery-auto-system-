"""Resize-to-target-size: scale_region_set should hit the requested
artwork size exactly (measuring the actual content bounding box, not
the source canvas), and preserve that precision all the way through to
the final stitch plan and pyembroidery pattern (PES; DST has its own
documented small quantization drift from chained-jump encoding -- see
src/regions/scale.py and the digitize CLI's --width-mm help text)."""
import pyembroidery as pe
import pytest

from src.params.classify import classify_region
from src.params.presets import get_preset
from src.pathing.order import order_by_color_then_distance
from src.pipeline import digitize_image
from src.regions.model import DigitizeScopeError
from src.regions.pipeline import load_and_extract_regions
from src.regions.scale import scale_region_set
from src.stitches.build import build_blocks_for_region
from src.stitches.model import StitchPlan

INPUT = "testbench/inputs/circle_2color.png"


def test_scale_to_target_width_hits_exact_size():
    rs = load_and_extract_regions(INPUT)
    scaled, warnings = scale_region_set(rs, target_width_mm=80.0)
    assert not warnings
    assert scaled.width_mm == pytest.approx(80.0, abs=0.01)
    assert scaled.height_mm == pytest.approx(80.0, abs=0.01)  # circle: aspect 1:1


def test_scale_by_height_only_follows_aspect_ratio():
    rs = load_and_extract_regions(INPUT)
    scaled, _ = scale_region_set(rs, target_height_mm=50.0)
    assert scaled.height_mm == pytest.approx(50.0, abs=0.01)
    assert scaled.width_mm == pytest.approx(50.0, abs=0.01)


def test_no_target_size_is_a_no_op():
    rs = load_and_extract_regions(INPUT)
    scaled, warnings = scale_region_set(rs, None, None)
    assert scaled is rs
    assert warnings == []


def test_mismatched_aspect_ratio_warns():
    rs = load_and_extract_regions(INPUT)  # a circle: 1:1 aspect ratio
    _, warnings = scale_region_set(rs, target_width_mm=80.0, target_height_mm=40.0)
    assert warnings and "stretched" in warnings[0]


def test_scaled_design_survives_full_pipeline_and_pes_roundtrip(tmp_path):
    fabric = get_preset("twill")
    rs = load_and_extract_regions(INPUT)
    rs, _ = scale_region_set(rs, target_width_mm=80.0)

    blocks = []
    for region in rs.regions:
        c = classify_region(region, fabric)
        blocks.extend(build_blocks_for_region(region, c, fabric, 0.0))
    plan = StitchPlan(blocks=order_by_color_then_distance(blocks), colors=rs.colors)

    minx, miny, maxx, maxy = plan.bounds_mm()
    # The stitched footprint is deliberately a hair wider than the
    # drawn 80mm: fill rows extend along their direction by the
    # preset's pull compensation (src/stitches/fill.py's
    # pull_compensate), the same allowance satin has always had.
    slack = 0.05 + get_preset("twill").pull_compensation_mm
    assert (maxx - minx) == pytest.approx(80.0, abs=slack)
    assert (maxy - miny) == pytest.approx(80.0, abs=slack)

    from src.io_.export import write_pattern
    paths = write_pattern(plan, str(tmp_path / "resized"))
    pes = pe.EmbPattern.read_pes(paths["pes"])
    b = pes.bounds()
    assert (b[2] - b[0]) / 10 == pytest.approx(80.0, abs=0.5)
    assert (b[3] - b[1]) / 10 == pytest.approx(80.0, abs=0.5)


def test_negative_width_is_rejected():
    rs = load_and_extract_regions(INPUT)
    with pytest.raises(ValueError):
        scale_region_set(rs, target_width_mm=-50.0)


def test_zero_width_means_unspecified_not_an_error():
    """0 means "not given" (matches --border 0 = disabled elsewhere),
    not an error -- only an explicit negative value is invalid."""
    rs = load_and_extract_regions(INPUT)
    scaled, warnings = scale_region_set(rs, target_width_mm=0.0)
    assert scaled is rs
    assert warnings == []


def test_shrinking_below_minimum_feature_size_is_still_caught(tmp_path):
    """A source that passes the pre-scale min-cap-height check can still
    be shrunk below the stitchable minimum via --width-mm -- that must
    be caught post-scale too, not silently allowed through."""
    with pytest.raises(DigitizeScopeError):
        digitize_image("testbench/inputs/text_sample.png", "twill",
                        str(tmp_path / "shrunk"), target_width_mm=5.0)


def test_shrinking_below_minimum_can_still_be_forced(tmp_path):
    result = digitize_image("testbench/inputs/text_sample.png", "twill",
                             str(tmp_path / "shrunk"), target_width_mm=5.0, force=True)
    assert any("forced past scope check" in w for w in result["warnings"])


NEEDS_UPSCALE = "testbench/inputs/needs_upscale_dot.png"


def test_too_small_source_is_rejected_with_no_target_size(tmp_path):
    """Baseline: needs_upscale_dot.png's native size (~4mm) really is
    under the 6mm minimum on its own, with no resize requested."""
    with pytest.raises(DigitizeScopeError):
        digitize_image(NEEDS_UPSCALE, "twill", str(tmp_path / "native"))


def test_upscaling_a_too_small_source_is_not_rejected(tmp_path):
    """Regression test for a real bug found from a user's actual too-
    small upload: requesting a big enough --width-mm/target_width_mm
    used to still get rejected, because the pre-scale minimum-cap-
    height check (inside load_and_extract_regions) ran on the source
    image's native size *before* the resize that would have fixed it
    ever had a chance to run -- so a --width-mm big enough to produce a
    perfectly fine finished size couldn't actually get used. The only
    check that should matter is on the final, scaled geometry."""
    result = digitize_image(NEEDS_UPSCALE, "twill", str(tmp_path / "upscaled"),
                             target_width_mm=20.0)
    # Reaching here at all (no DigitizeScopeError) is the regression
    # check; also confirm no leftover warning about it.
    assert not any("minimum cap height" in w for w in result["warnings"])
    assert result["regions"][0]["stitch_type"] in ("fill", "satin")


def test_upscaling_still_catches_a_target_size_that_is_still_too_small(tmp_path):
    """The post-scale re-check must still fire when the *requested*
    size is itself still too small -- upscaling isn't a blanket bypass
    of the guardrail, only of checking the wrong (pre-resize) size."""
    with pytest.raises(DigitizeScopeError):
        digitize_image(NEEDS_UPSCALE, "twill", str(tmp_path / "still_small"),
                        target_width_mm=5.0)
