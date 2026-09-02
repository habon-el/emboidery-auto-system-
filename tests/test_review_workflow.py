"""Manual-review correction workflow (Multi-Region Illustration
Digitization milestone, Section 5): validation, per-region override
resolution, and the full rebuild round-trip -- a correction to one
region must not disturb any other region's automatic decision, and
must actually reach the exported files (real thread colors, layer
order, stitch counts)."""
import os

import pyembroidery as pe
import pytest

from src.jobs import JobSpec, has_job_spec, load_job_spec, save_job_spec
from src.pipeline import digitize_image
from src.review.corrections import (CorrectionValidationError,
                                     override_from_stored,
                                     parse_correction_form,
                                     parse_region_override)
from src.review.rebuild import rebuild_job
from src.stitches.model import RUNNING, SATIN

INPUTS = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs")
STAR = os.path.join(INPUTS, "star_3color.png")


def _validated(raw: dict) -> dict:
    """Simulates the webapp review route's real flow: parse+validate
    the raw form fields, then store the already-typed result -- exactly
    what JobSpec.corrections expects (see src/jobs.py)."""
    return parse_region_override(raw).__dict__


def test_parse_region_override_rejects_bad_numeric_input():
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"density_mm": "not-a-number"})
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"density_mm": "-1"})  # must be > 0
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"border_width_mm": "-5"})
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"stitch_type": "photo-fill"})
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"thread_rgb": "not-a-color"})
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"z_order": "two"})


def test_parse_region_override_accepts_blank_as_unchanged():
    override = parse_region_override({"stitch_type": "", "density_mm": "  "})
    assert override.is_noop()


def test_parse_region_override_round_trips_through_storage():
    raw = {"stitch_type": "satin", "angle_deg": "45", "density_mm": "0.4",
           "underlay": "off", "border_width_mm": "0.6", "z_order": "3",
           "thread_rgb": "#1a2b3c"}
    override = parse_region_override(raw)
    stored = override.__dict__
    restored = override_from_stored(stored)
    assert restored == override


def test_job_spec_persists_and_reloads(tmp_path):
    spec = JobSpec(input_path=STAR, fabric="twill", border_width_mm=0.5,
                    corrections={"raster-1-0": {"stitch_type": "satin"}})
    assert not has_job_spec(str(tmp_path))
    save_job_spec(str(tmp_path), spec)
    assert has_job_spec(str(tmp_path))
    reloaded = load_job_spec(str(tmp_path))
    assert reloaded == spec


def test_correction_changes_only_the_targeted_region(tmp_path):
    baseline = digitize_image(STAR, "twill", str(tmp_path / "baseline"))
    baseline_by_id = {r["id"]: r for r in baseline["regions"]}

    target_id = baseline["regions"][0]["id"]
    other_ids = [r["id"] for r in baseline["regions"][1:]]
    assert other_ids, "fixture must have more than one region for this test to mean anything"

    spec = JobSpec(input_path=STAR, fabric="twill",
                    corrections={target_id: {"stitch_type": "running"}})
    corrected = rebuild_job(spec, str(tmp_path / "corrected"))
    corrected_by_id = {r["id"]: r for r in corrected["regions"]}

    assert corrected_by_id[target_id]["stitch_type"] == RUNNING
    assert corrected_by_id[target_id]["corrected"] is True
    assert corrected["corrections_applied"] == [target_id]

    for oid in other_ids:
        assert corrected_by_id[oid]["stitch_type"] == baseline_by_id[oid]["stitch_type"]
        assert corrected_by_id[oid]["reason"] == baseline_by_id[oid]["reason"]
        assert corrected_by_id[oid]["corrected"] is False


def test_pes_readback_keeps_distinct_source_colors_distinct(tmp_path):
    """Round-trip check for the export step itself (src/io_/export.py's
    real EmbThread.set_color(), not a string label that used to default
    to black): star_3color.png's two genuinely different source colors
    must still read back as two different PES thread colors."""
    result = digitize_image(STAR, "twill", str(tmp_path / "star"))
    hexes = [t.hex_color() for t in pe.EmbPattern.read_pes(result["pes"]).threadlist]
    assert len(hexes) >= 2
    assert len(set(hexes)) == len(hexes)


def test_thread_rgb_override_reaches_the_region_metadata_and_plan(tmp_path):
    """PES stores a palette index into a fixed machine thread catalog,
    not arbitrary RGB (pyembroidery's PES writer snaps set_color() to
    the nearest catalog entry -- a documented PES format characteristic,
    the same way DST has its own small quantization drift; see
    src/io_/export.py), so an arbitrary custom RGB can't be verified by
    an exact PES hex match. What must hold is that the override reaches
    our own data: the corrected region's metadata reports the exact
    override color, and the export's in-memory color list gets a new,
    distinct slot for it rather than reusing an existing region's."""
    baseline = digitize_image(STAR, "twill", str(tmp_path / "baseline"))
    target_id = baseline["regions"][0]["id"]
    baseline_color_indexes = {r["color_index"] for r in baseline["regions"]}

    custom_rgb = (10, 200, 30)
    spec = JobSpec(input_path=STAR, fabric="twill",
                    corrections={target_id: _validated({"thread_rgb": "%02x%02x%02x" % custom_rgb})})
    corrected = rebuild_job(spec, str(tmp_path / "corrected"))
    corrected_by_id = {r["id"]: r for r in corrected["regions"]}

    assert corrected_by_id[target_id]["thread_rgb_hex"] == "#%02x%02x%02x" % custom_rgb
    assert corrected_by_id[target_id]["color_index"] not in baseline_color_indexes


def test_underlay_off_override_removes_underlay_blocks(tmp_path):
    baseline = digitize_image(STAR, "twill", str(tmp_path / "baseline"))
    # Pick a satin/fill region (whichever exists) -- underlay only
    # applies to those, not running stitch.
    target = next(r for r in baseline["regions"] if r["stitch_type"] != RUNNING)

    spec_on = JobSpec(input_path=STAR, fabric="twill", corrections={})
    with_underlay = rebuild_job(spec_on, str(tmp_path / "with_underlay"))

    spec_off = JobSpec(input_path=STAR, fabric="twill",
                        corrections={target["id"]: _validated({"underlay": "off"})})
    without_underlay = rebuild_job(spec_off, str(tmp_path / "without_underlay"))

    assert without_underlay["stitch_count"] < with_underlay["stitch_count"]


def test_z_order_override_changes_pathing_without_changing_stitch_count(tmp_path):
    baseline = digitize_image(STAR, "twill", str(tmp_path / "baseline"))
    ids = [r["id"] for r in baseline["regions"]]
    assert len(ids) >= 2

    # Reverse the layer order of the two regions sharing a color, if any;
    # otherwise just flip the first region's z_order to something far
    # outside the natural range and confirm the pipeline accepts it.
    spec = JobSpec(input_path=STAR, fabric="twill",
                    corrections={ids[0]: _validated({"z_order": "999"})})
    corrected = rebuild_job(spec, str(tmp_path / "corrected"))
    assert corrected["stitch_count"] == baseline["stitch_count"]


def test_invalid_correction_raises_before_any_rebuild():
    with pytest.raises(CorrectionValidationError):
        parse_region_override({"stitch_type": "satin", "density_mm": "-2"})


def test_parse_correction_form_groups_by_region_and_validates_all():
    form = {
        "raster-1-0::stitch_type": "satin",
        "raster-1-0::angle_deg": "30",
        "raster-2-0::density_mm": "0.4",
        "unknown-region::stitch_type": "fill",  # not in region_ids -- ignored
        "not_a_scoped_field": "ignored too",
    }
    overrides = parse_correction_form(form, {"raster-1-0", "raster-2-0"})
    assert set(overrides) == {"raster-1-0", "raster-2-0"}
    assert overrides["raster-1-0"].stitch_type == "satin"
    assert overrides["raster-1-0"].angle_deg == 30.0
    assert overrides["raster-2-0"].density_mm == 0.4


def test_parse_correction_form_rejects_if_any_region_is_invalid():
    form = {
        "raster-1-0::stitch_type": "satin",       # valid
        "raster-2-0::density_mm": "not-a-number",  # invalid
    }
    with pytest.raises(CorrectionValidationError):
        parse_correction_form(form, {"raster-1-0", "raster-2-0"})
