"""Thread-palette matching (Multi-Region Illustration Digitization
milestone, item 4): nearest real thread by Delta-E, not raw RGB."""
from src.params.thread_palette import ISACORD_SAMPLE, match_thread


def test_exact_palette_color_matches_itself():
    name, code, rgb = ISACORD_SAMPLE[0]
    m = match_thread(rgb)
    assert m.name == name
    assert m.code == code
    assert m.delta_e < 0.5
    assert not m.low_confidence


def test_far_off_color_is_flagged_low_confidence():
    # A vivid color far from anything in the sample palette.
    m = match_thread((0, 255, 255))
    assert m.low_confidence
    assert m.delta_e > 12.0


def test_match_is_nearest_not_first():
    # Sanity: white and black are both in the palette; a near-black
    # should match black, not fall through to an unrelated first entry.
    m = match_thread((10, 10, 12))
    assert m.name == "Black"
