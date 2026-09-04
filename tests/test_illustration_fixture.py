"""Multi-region illustration fixture (Multi-Region Illustration
Digitization milestone, Section 6): a layered badge with a true hole,
thin line art, and 6 source colors reducing to fewer selected threads.
See testbench/generate_samples.py's make_illustration_badge() docstring
for why texture-zone detection is unit-tested separately instead of via
this fixture."""
import os

from src.params.classify import classify_region
from src.params.presets import get_preset
from src.pipeline import digitize_image
from src.regions.pipeline import load_and_extract_regions
from src.stitches.model import FILL, RUNNING
from testbench.generate_samples import make_illustration_badge

INPUT = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs",
                      "illustration_badge.png")


def _ensure_fixture():
    if not os.path.exists(INPUT):
        make_illustration_badge()


def test_raw_vs_merged_color_counts_differ():
    """6 drawn colors (two near-duplicate pairs) should perceptually
    reduce to fewer selected thread colors."""
    _ensure_fixture()
    rs = load_and_extract_regions(INPUT, strict=False)
    assert rs.raw_color_count > rs.merged_color_count
    assert len(rs.colors) == 4  # navy+navy_dup, gold+gold_dup, crimson, teal


def test_hole_is_preserved_as_a_true_polygon_hole():
    _ensure_fixture()
    rs = load_and_extract_regions(INPUT, strict=False)
    assert any(len(r.polygon.interiors) > 0 for r in rs.regions)


def test_z_order_is_one_layer_per_color():
    """Raster regions of one color come from mutually-exclusive pixel
    masks and can never overlap, so they share a layer; layers follow
    color order. (Each region used to get its own slot in contour-
    discovery order, which forced pathing to sew a word's letters in
    whatever order the contour finder met them -- see
    src/pathing/order.py.)"""
    _ensure_fixture()
    rs = load_and_extract_regions(INPUT, strict=False)
    z_orders = [r.z_order for r in rs.regions]
    assert z_orders == sorted(z_orders)
    by_color = {}
    for r in rs.regions:
        by_color.setdefault(r.color_index, set()).add(r.z_order)
    assert all(len(layers) == 1 for layers in by_color.values())
    assert len(set(z_orders)) == len(by_color)


def test_thin_swoosh_is_classified_as_line_art_running_stitch():
    _ensure_fixture()
    rs = load_and_extract_regions(INPUT, strict=False)
    fabric = get_preset("twill")
    classifications = [classify_region(r, fabric).stitch_type for r in rs.regions]
    assert RUNNING in classifications


def test_every_region_carries_a_confidence_value():
    _ensure_fixture()
    rs = load_and_extract_regions(INPUT, strict=False)
    fabric = get_preset("twill")
    for r in rs.regions:
        c = classify_region(r, fabric)
        assert 0.0 <= c.confidence <= 1.0
        assert c.reason


def test_full_pipeline_produces_multi_region_analysis(tmp_path):
    """End-to-end: the illustration digitizes (with --force, since its
    deliberately small filigree detail -- a real badge's fine features --
    trips the plain min-feature-size check) into a plan whose analysis
    summary reflects multiple region kinds, not just one flat fill."""
    _ensure_fixture()
    result = digitize_image(INPUT, "twill", str(tmp_path / "badge"), force=True)
    assert result["summary"]["filled_regions"] >= 1
    assert result["summary"]["running_stitch_details"] >= 1
    assert any(reg["stitch_type"] == FILL for reg in result["regions"])
    assert any(reg["stitch_type"] == RUNNING for reg in result["regions"])
    assert all(reg["thread_name"] for reg in result["regions"])
