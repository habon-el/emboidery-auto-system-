"""End-to-end golden-file tests: real sample input -> full digitize
pipeline -> DST/PES readback. Tolerant stitch-count ranges rather than
exact values, since small algorithm tuning shouldn't break the suite,
but the files must always be valid and roughly the expected size/shape.
"""
import os

import pyembroidery as pe
import pytest

from src.pipeline import digitize_image
from src.regions.model import DigitizeScopeError
from testbench.generate_samples import main as generate_samples

INPUTS = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs")

# (min_stitches, max_stitches, expected_color_count)
EXPECTED = {
    "circle_2color.png": (400, 1200, 1),
    "bar_satin.png": (350, 1200, 1),
    "star_3color.png": (250, 900, 2),
    # Text comes out as satin columns now, not tatami fill (see
    # src/params/classify.py's curved-stroke detection). Satin is denser
    # than fill, so both text fixtures land higher than they used to.
    "text_sample.png": (250, 800, 1),
    "text_with_bowls.png": (1100, 2200, 1),
    "logo.svg": (700, 2000, 2),
}


@pytest.fixture(scope="module", autouse=True)
def ensure_samples():
    if not os.path.exists(os.path.join(INPUTS, "circle_2color.png")):
        generate_samples()


@pytest.mark.parametrize("filename", list(EXPECTED))
def test_digitize_produces_valid_sewable_files(tmp_path, filename):
    min_stitches, max_stitches, expected_colors = EXPECTED[filename]
    out_stem = str(tmp_path / "out")

    digitize_image(os.path.join(INPUTS, filename), "twill", out_stem)

    assert os.path.exists(f"{out_stem}.dst")
    assert os.path.exists(f"{out_stem}.pes")
    assert os.path.exists(f"{out_stem}_preview.png")

    dst = pe.EmbPattern.read_dst(f"{out_stem}.dst")
    pes = pe.EmbPattern.read_pes(f"{out_stem}.pes")

    assert min_stitches <= len(dst.stitches) <= max_stitches
    assert min_stitches <= len(pes.stitches) <= max_stitches
    assert dst.count_color_changes() == expected_colors - 1


def test_bowled_letters_are_not_misclassified_as_running(tmp_path):
    """Regression test for a real reported bug: "Hello World" at normal
    small-text size used to digitize every bowled letter (e, o, o, o, d)
    as a scribbly running stitch instead of a filled glyph -- see
    test_m2_classify.py's test_letter_bowl_with_hole_is_fill_not_running
    for the root cause (a holed region's closed-loop medial axis)."""
    result = digitize_image(
        os.path.join(INPUTS, "text_with_bowls.png"), "twill", str(tmp_path / "out"))
    assert result["summary"]["running_stitch_details"] == 0


def test_out_of_scope_input_rejected_end_to_end(tmp_path):
    with pytest.raises(DigitizeScopeError):
        digitize_image(
            os.path.join(INPUTS, "out_of_scope_smalltext.png"),
            "twill", str(tmp_path / "out"))
