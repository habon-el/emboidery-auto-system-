"""Fabric presets.

All measurements are in millimetres. pyembroidery's native EmbPattern
coordinate unit is 1/10 mm (confirmed against DST's native resolution via
the M0 smoke test), so conversion happens once at export time
(see src/io_/units.py) -- everything upstream of that stays in mm.

These are conservative starting points, not physics. Real push-pull
compensation, density, and underlay tuning come from sewing out a sample
on each fabric and measuring distortion -- see testbench/SEWOUT_CHECKLIST.md.
Treat every number here as "safe default, pending sew-out," not as a
claim we've measured this fabric.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FabricPreset:
    name: str

    # Fill (tatami) stitching
    fill_row_spacing_mm: float       # distance between parallel fill rows
    fill_stitch_length_mm: float     # needle-point spacing along a fill row
    fill_underlay_inset_mm: float    # perimeter underlay inset from the fill edge

    # Satin column stitching
    satin_density_mm: float          # spacing between zigzag stitches along the rail
    satin_max_width_mm: float        # widths beyond this should be fill, not satin
    satin_underlay: bool             # add a centerline running-stitch underlay

    # Running stitch
    running_stitch_length_mm: float

    # Applied to fill/satin region boundaries before stitching, to counteract
    # thread pulling the fabric in (a fixed, conservative default -- not tuned
    # per-design; see Section 2/9 of the build spec).
    pull_compensation_mm: float

    notes: str = ""


PRESETS: dict[str, FabricPreset] = {
    "twill": FabricPreset(
        name="twill",
        fill_row_spacing_mm=0.4,
        fill_stitch_length_mm=3.0,
        fill_underlay_inset_mm=1.2,
        satin_density_mm=0.35,
        satin_max_width_mm=12.0,
        satin_underlay=True,
        running_stitch_length_mm=2.5,
        pull_compensation_mm=0.15,
        notes="Stable, tightly-woven cotton/poly blend. Baseline preset -- "
              "least underlay/compensation needed of the three.",
    ),
    "fleece": FabricPreset(
        name="fleece",
        fill_row_spacing_mm=0.45,
        fill_stitch_length_mm=3.2,
        fill_underlay_inset_mm=1.8,
        satin_density_mm=0.4,
        satin_max_width_mm=10.0,
        satin_underlay=True,
        running_stitch_length_mm=2.2,
        pull_compensation_mm=0.3,
        notes="Thick napped fabric. Wider underlay inset to compress the "
              "pile before top stitching; shorter running stitch length so "
              "stitches don't sink.",
    ),
    "knit": FabricPreset(
        name="knit",
        fill_row_spacing_mm=0.35,
        fill_stitch_length_mm=2.5,
        fill_underlay_inset_mm=1.5,
        satin_density_mm=0.3,
        satin_max_width_mm=8.0,
        satin_underlay=True,
        running_stitch_length_mm=2.0,
        pull_compensation_mm=0.4,
        notes="Stretch/knit-ish placeholder preset with denser underlay and "
              "the highest fixed compensation of the three. This is NOT a "
              "validated stretch-fabric physics model (out of scope per "
              "Section 2) -- treat it as a cautious starting point that "
              "still needs a stabilizer and a sew-out before production use.",
    ),
}


def get_preset(name: str) -> FabricPreset:
    try:
        return PRESETS[name]
    except KeyError as e:
        raise ValueError(
            f"Unknown fabric preset {name!r}. Available: {sorted(PRESETS)}"
        ) from e
