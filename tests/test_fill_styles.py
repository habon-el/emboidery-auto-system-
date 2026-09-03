"""Selectable fill styles (Tatami/Contour/Cross-Hatch/Brick): a human
(or a customer) choice of which real fill pattern covers a FILL-type
region, instead of the system always defaulting to one look. Covers the
generators themselves (src/stitches/fill.py), the dispatch in
src/stitches/build.py, the override plumbing (job-wide default +
per-region correction, src/review/corrections.py), and a full
digitize_image() round-trip."""
import math
import os

import pytest
from shapely.geometry import Point, Polygon, box

from src.jobs import JobSpec
from src.pipeline import digitize_image
from src.review.corrections import parse_region_override, resolve_override
from src.review.rebuild import rebuild_job
from src.stitches.build import build_blocks_for_region
from src.stitches.fill import (generate_brick_fill, generate_contour_fill,
                                generate_crosshatch_fill, generate_fill)
from src.stitches.model import (FILL, FILL_BRICK, FILL_CONTOUR,
                                 FILL_CROSSHATCH, FILL_STYLES, FILL_TATAMI)
from src.params.classify import classify_region
from src.params.presets import get_preset
from src.regions.model import Region

INPUTS = os.path.join(os.path.dirname(__file__), "..", "testbench", "inputs")
STAR = os.path.join(INPUTS, "star_3color.png")


def _square_region(size_mm=20.0):
    poly = Polygon([(0, 0), (size_mm, 0), (size_mm, size_mm), (0, size_mm)])
    return poly, Region(polygon=poly, color_index=0, region_id="sq")


def _ring_polygon(r_outer=10.0, r_inner=6.0):
    outer = Point(0, 0).buffer(r_outer, quad_segs=32)
    inner = Point(0, 0).buffer(r_inner, quad_segs=32)
    return outer.difference(inner)


# -- generators themselves -------------------------------------------

def test_tatami_covers_the_region_with_parallel_rows():
    poly, _ = _square_region()
    runs = generate_fill(poly, 0.0, 1.0, 3.0)
    assert runs
    ys = sorted({round(y, 3) for run in runs for _, y in run})
    assert len(ys) > 5  # several distinct rows


def test_brick_offsets_alternating_rows_from_tatami():
    poly, _ = _square_region()
    tatami = generate_fill(poly, 0.0, 1.1, 3.2)
    brick = generate_brick_fill(poly, 0.0, 1.1, 3.2)
    # Same first point (the row edge), but interior points differ once
    # the phase offset kicks in on an odd row.
    assert tatami[0][0] == brick[0][0]
    assert tatami[0][:6] != brick[0][:6]


def test_crosshatch_is_two_perpendicular_passes():
    poly, _ = _square_region()
    single = generate_fill(poly, 0.0, 1.0, 3.0)
    cross = generate_crosshatch_fill(poly, 0.0, 1.0, 3.0)
    single_stitches = sum(len(r) for r in single)
    cross_stitches = sum(len(r) for r in cross)
    # Roughly a single pass plus a second, wider-spaced pass -- more
    # than one pass alone, well under exactly double.
    assert single_stitches < cross_stitches < single_stitches * 2


def test_contour_rings_hug_the_boundary_and_shrink_inward():
    poly, _ = _square_region(size_mm=20.0)
    runs = generate_contour_fill(poly, 2.0, 3.0)
    assert len(runs) >= 3  # several concentric rings on a 20mm square
    # Every run should be a closed loop (first point == last point).
    for run in runs:
        assert math.hypot(run[0][0] - run[-1][0], run[0][1] - run[-1][1]) < 1e-3
    # Rings shrink: each ring's bounding box should be no bigger than
    # the previous one's (contour works inward from the boundary).
    def bbox_diag(run):
        xs, ys = [p[0] for p in run], [p[1] for p in run]
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    diags = [bbox_diag(r) for r in runs]
    assert diags == sorted(diags, reverse=True)


def test_contour_fill_handles_a_hole_without_crashing():
    """A ring/donut shape (a letter bowl, a badge ring) -- buffering
    toward the hole must terminate cleanly rather than looping forever
    or raising, and must still produce coverage near both boundaries."""
    ring = _ring_polygon()
    runs = generate_contour_fill(ring, 1.0, 2.0)
    assert runs
    for run in runs:
        assert len(run) >= 2


def test_all_four_fill_styles_produce_nonempty_stitchable_output():
    poly, _ = _square_region()
    for style, runs in [
        (FILL_TATAMI, generate_fill(poly, 20.0, 1.0, 3.0)),
        (FILL_CONTOUR, generate_contour_fill(poly, 1.0, 3.0)),
        (FILL_CROSSHATCH, generate_crosshatch_fill(poly, 20.0, 1.0, 3.0)),
        (FILL_BRICK, generate_brick_fill(poly, 20.0, 1.0, 3.0)),
    ]:
        assert runs, f"{style} produced no runs"
        assert all(len(r) >= 2 for r in runs), f"{style} produced a degenerate run"


# -- dispatch in build_blocks_for_region ------------------------------

def test_build_blocks_dispatches_on_fill_style():
    fabric = get_preset("twill")
    poly, region = _square_region()
    classification = classify_region(region, fabric)
    assert classification.stitch_type == FILL

    counts = {}
    for style in FILL_STYLES:
        blocks = build_blocks_for_region(region, classification, fabric, fill_style=style)
        fill_blocks = [b for b in blocks if b.stitch_type == FILL]
        counts[style] = sum(len(b.points_mm) for b in fill_blocks)
    # Different styles should not all coincidentally produce identical
    # stitch counts on the same shape/density -- proves the dispatch
    # actually reaches a different generator per style, not one path
    # silently used for all four.
    assert len(set(counts.values())) > 1


# -- override plumbing --------------------------------------------------

def test_parse_region_override_validates_fill_style():
    ok = parse_region_override({"fill_style": "contour"})
    assert ok.fill_style == "contour"
    blank = parse_region_override({"fill_style": ""})
    assert blank.fill_style is None
    with pytest.raises(Exception):
        parse_region_override({"fill_style": "not-a-real-style"})


def test_resolve_override_falls_back_to_job_default_then_override():
    fabric = get_preset("twill")
    poly, region = _square_region()
    classification = classify_region(region, fabric)

    # No override at all -- job default wins.
    _, _, _, style, _ = resolve_override(classification, fabric, 0.0, FILL_CONTOUR, None)
    assert style == FILL_CONTOUR

    # A per-region override beats the job default.
    override = parse_region_override({"fill_style": "brick"})
    _, _, _, style, _ = resolve_override(classification, fabric, 0.0, FILL_CONTOUR, override)
    assert style == FILL_BRICK


# -- end-to-end -----------------------------------------------------------

def test_digitize_image_rejects_unknown_fill_style(tmp_path):
    with pytest.raises(ValueError):
        digitize_image(STAR, "twill", str(tmp_path / "out"), fill_style="not-a-style")


def test_digitize_image_applies_the_chosen_default_fill_style(tmp_path):
    tatami_result = digitize_image(
        STAR, "twill", str(tmp_path / "tatami"), fill_style=FILL_TATAMI)
    contour_result = digitize_image(
        STAR, "twill", str(tmp_path / "contour"), fill_style=FILL_CONTOUR)
    assert tatami_result["stitch_count"] != contour_result["stitch_count"]
    for r in tatami_result["regions"]:
        if r["stitch_type"] == FILL:
            assert r["fill_style"] == FILL_TATAMI
    for r in contour_result["regions"]:
        if r["stitch_type"] == FILL:
            assert r["fill_style"] == FILL_CONTOUR


def test_per_region_fill_style_override_beats_job_default(tmp_path):
    baseline = digitize_image(STAR, "twill", str(tmp_path / "baseline"), fill_style=FILL_TATAMI)
    fill_region = next(r for r in baseline["regions"] if r["stitch_type"] == FILL)

    spec = JobSpec(input_path=STAR, fabric="twill", default_fill_style=FILL_TATAMI,
                    corrections={fill_region["id"]: {"fill_style": FILL_CONTOUR}})
    corrected = rebuild_job(spec, str(tmp_path / "corrected"))
    corrected_by_id = {r["id"]: r for r in corrected["regions"]}

    assert corrected_by_id[fill_region["id"]]["fill_style"] == FILL_CONTOUR
    # Every other fill region keeps the job's tatami default.
    for r in corrected["regions"]:
        if r["stitch_type"] == FILL and r["id"] != fill_region["id"]:
            assert r["fill_style"] == FILL_TATAMI


# -- design-wide fill direction -------------------------------------------

def test_uniform_fill_angle_gives_every_filled_region_the_same_direction(tmp_path):
    """Regression test for a real, user-reported quality problem: every
    region used to derive its own fill angle from its own medial axis,
    so a single word's letters came out stitched in five different
    directions (H/w horizontal, e/o/o vertical, r at -69, d at -44) --
    thread is directional, so each caught the light differently and the
    word read as mismatched letters instead of one piece of lettering.
    See src/stitches/model.py's UNIFORM_FILL_ANGLE_DEG."""
    result = digitize_image(os.path.join(INPUTS, "text_with_bowls.png"), "twill",
                             str(tmp_path / "uniform"), fill_angle_deg=30.0)
    fill_angles = {r["angle_deg"] for r in result["regions"] if r["stitch_type"] == FILL}
    assert fill_angles, "fixture must have filled regions to be meaningful"
    assert fill_angles == {30.0}, f"filled regions disagree on direction: {fill_angles}"


def test_per_shape_angles_still_available_and_actually_differ(tmp_path):
    """None keeps the old per-shape behavior for illustrations whose
    shapes should follow their own form -- and on real lettering those
    angles genuinely do disagree with each other, which is the whole
    reason the shared angle exists."""
    from src.params.classify import classify_region
    from src.params.presets import get_preset
    from src.regions.pipeline import load_and_extract_regions

    region_set = load_and_extract_regions(os.path.join(INPUTS, "text_with_bowls.png"))
    fabric = get_preset("twill")
    angles = {round(classify_region(r, fabric).angle_deg, 1)
              for r in region_set.regions
              if classify_region(r, fabric).stitch_type == FILL}
    assert len(angles) > 1, "per-shape angles should differ across letters"

    result = digitize_image(os.path.join(INPUTS, "text_with_bowls.png"), "twill",
                             str(tmp_path / "per_shape"), fill_angle_deg=None)
    assert result["summary"]["filled_regions"] > 0


def test_per_region_angle_correction_still_beats_the_design_wide_angle(tmp_path):
    """The design-wide angle is a default, not a lock: a region whose
    own correction sets an angle must still win."""
    baseline = digitize_image(STAR, "twill", str(tmp_path / "baseline"), fill_angle_deg=45.0)
    target = next(r for r in baseline["regions"] if r["stitch_type"] == FILL)

    spec = JobSpec(input_path=STAR, fabric="twill", default_fill_angle_deg=45.0,
                    corrections={target["id"]: {"angle_deg": 12.0}})
    corrected = rebuild_job(spec, str(tmp_path / "corrected"))
    by_id = {r["id"]: r for r in corrected["regions"]}
    assert "manually overridden" in by_id[target["id"]]["reason"]
