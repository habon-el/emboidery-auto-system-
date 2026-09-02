"""End-to-end: digitize_image's result carries the Multi-Region
Illustration Digitization milestone's analysis summary (item 11's
"12 visual colors detected / 8 thread colors selected / ..." panel) and
per-region metadata (confidence, reason, thread match), not just the
exported files."""
import os

from src.pipeline import digitize_image

INPUTS = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs")


def test_result_carries_summary_and_region_metadata(tmp_path):
    result = digitize_image(
        os.path.join(INPUTS, "star_3color.png"), "twill", str(tmp_path / "out"))

    summary = result["summary"]
    assert summary["visual_colors_detected"] >= summary["thread_colors_selected"] > 0
    assert (summary["filled_regions"] + summary["satin_columns"]
            + summary["running_stitch_details"]) == len(result["regions"])

    for region in result["regions"]:
        assert region["stitch_type"] in ("fill", "satin", "running")
        assert 0.0 <= region["confidence"] <= 1.0
        assert region["reason"]
        assert region["thread_name"]  # every region's color got a thread match
        assert isinstance(region["needs_review"], bool)
