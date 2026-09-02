# emboidery-auto-system-

> **Note:** this project's active development has moved to
> [the-auto_embroidory](https://github.com/habon-el/the-auto_embroidory),
> which is kept up to date first. This repo is mirrored from it.

## Auto-Digitizing Embroidery Editor (MVP)

An auto-digitizing embroidery editor: converts a clean logo/text image into
a real, sew-able machine embroidery file (DST + PES), with a stitch-level
preview. CLI-first, Python 3.11+.

**Scope (see build spec for full detail):** clean vector/raster input,
2-4 flat colors, running/satin/fill stitches, auto underlay, fabric-preset
density/angle, sew-order pathing, DST/PES export via `pyembroidery`.
Photos, gradients, 3D/puff, and sub-6mm text are out of scope and are
flagged rather than silently digitized.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Usage

```bash
# M0 spine: hand-built shape, no image input, proves the export path
python -m src.cli demo --shape circle --fabric twill --out testbench/out/demo

# Full pipeline: digitize a real logo/text image
python -m src.cli digitize path/to/logo.png --fabric twill --out testbench/out/design
```

Each run writes `<out>.dst`, `<out>.pes`, and `<out>_preview.png`, and
prints the stitch count and an estimated run time.

Fabric presets: `twill` (default, stable woven), `fleece`, `knit`
(placeholder, conservative — see `src/params/presets.py` for caveats).

`digitize` also accepts `--border MM` for an optional denser fill ring
stitched along each fill region's own edge (a bolder/more raised-looking
border via stitch density and stacking order — not literal foam 3D,
which stays out of scope; see `src/stitches/border.py`).

Every `digitize` run also prints an analysis summary line, e.g.:

```
Analysis: 8 visual colors detected · 6 thread colors selected · 4 filled regions
· 2 satin columns · 1 running-stitch details · 1 texture zones · 0 warning(s) requiring review
```

("Visual colors" vs. "thread colors" differ when perceptually-identical
shades get merged, and each region's classification carries a matched
real thread color and a confidence score — see **Multi-Region
Illustration Digitization** below.)

### Multi-Region Illustration Digitization

The step up from "clean flat-color logo converter" toward illustrations
with many regions, holes, overlaps, and mixed stitch-type needs (badges,
mascots, layered icons) — not arbitrary photographs, which stay a
separate, later milestone (photo-realistic digitizing needs a
structurally different stitch technique: halftone/density-based tone
simulation, not more color clustering).

What's in place:

- **Perceptual color reduction** (`src/regions/color_reduce.py`): colors
  are clustered in CIELab space (Delta-E, not raw RGB), with anti-aliasing
  edge pixels absorbed into their nearest real color by pixel-count
  rather than forced to survive as their own tiny cluster — raises the
  practical ceiling from 4 flat colors to 8-12 without fragmenting a
  clean logo's edges. Fully deterministic: the same image always
  quantizes the same way (a self-contained, seeded k-means — no
  hidden/global RNG state left to vary run to run).
- **Thread-palette matching** (`src/params/thread_palette.py`): each
  final color is matched to the nearest color in a small sample thread
  palette by Delta-E, surfaced alongside the source color rather than
  silently substituted.
- **Line-art detection** (`src/params/classify.py`): a region whose true
  average width — area over its *full* medial-axis skeleton length, not
  just the bounding-rectangle proxy — is hairline-thin gets running
  stitch even when its bounding box isn't elongated at all (a winding
  line-art stroke, not unlike a spiral). This is a topology-independent
  measurement, so it doesn't misfire on a branching-but-filled shape
  (a star, a plus sign) the way a naive perimeter-based test would.
- **Texture-zone flagging** (`src/regions/texture.py`): flags regions
  whose *original* (pre-quantization) interior pixels show real local
  variance — a drawn fur/scale/wood-grain pattern quantization flattened
  away — sampled away from each region's own anti-aliased edge so an
  ordinary flat region's boundary softness isn't misread as texture.
- **Classification reason + confidence** (`src/params/classify.py`):
  every stitch-type decision carries a plain-language reason and a
  0-1 confidence score (how far the deciding measurement sits from its
  threshold), rolled up into the "N warning(s) requiring review" count.
- **Per-region analysis table** in the web UI: a read-only view of every
  region's stitch type, matched thread, confidence, and texture flag.
  This is the "see the decisions" half of a correction workflow — an
  interactive editor to *change* a region's stitch type/density/angle/
  thread/layer order and re-render just that region is the next step on
  top of this, not yet built.

Known limitation: color reduction's k-means fit is capped at a bounded
sample of pixels and the final per-pixel assignment is O(pixels ×
colors), which is fine for a typical logo/text image but not yet
performance-tuned for a several-megapixel input — a very large upload
will be slower to analyze (and to reject, if it turns out to be a photo)
than a small one.

### Web UI (local only)

A small local Flask app wraps the same pipeline with a browser UI:
upload an image, pick a fabric preset and border width, see the
preview and download the .dst/.pes.

```bash
pip install -r requirements.txt   # picks up Flask
python -m webapp.app
# open http://127.0.0.1:5000
```

Everything runs on your machine; nothing is uploaded anywhere else.

### Tests

```bash
pytest
./run_tests.sh   # full suite + batch digitize over testbench/inputs/
```

### Physical validation

A screen preview cannot catch push-pull distortion, puckering, or real
satin edge quality. See `testbench/SEWOUT_CHECKLIST.md` before calling any
preset production-ready.

### Project layout

See `src/` (io_, regions, stitches, params, pathing, preview, validate,
cli.py), `tests/`, and `testbench/` (inputs/expected/out).
