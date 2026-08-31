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
