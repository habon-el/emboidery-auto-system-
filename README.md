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
  A texture-flagged fill region gets a cross-hatched (two-direction)
  fill instead of one flat pass (`src/stitches/build.py`).
- **Classification reason + confidence** (`src/params/classify.py`):
  every stitch-type decision carries a plain-language reason and a
  0-1 confidence score (how far the deciding measurement sits from its
  threshold), rolled up into the "N warning(s) requiring review" count.
- **Region containment/layer order**: each region carries a `z_order`
  (draw/paint order — meaningful document order for SVG input, discovery
  order for raster) used both to display a sensible default layering and
  as a pathing tiebreak (`src/pathing/order.py`), overridable per region
  in the manual review workflow below.

### Selectable fill styles

Which fill regions actually get isn't decided unilaterally: you (or a
customer) pick from four real digitizing fill patterns, each shown as
an actual rendered stitch swatch rather than a name in a dropdown
(`testbench/generate_fill_previews.py`), so the choice is made with a
real visual reference:

- **Tatami** (standard rows) — parallel straight rows, offset row-to-row
  so needle holes don't line up into a visible seam. The default, and
  still the right choice for most flat blocks.
- **Contour** (follows the shape's edge) — concentric rings that hug
  the region's own curves instead of one straight-line angle picked
  once for the whole shape. This is what fixes two differently-curved
  neighboring letters/regions reading as pointing in unrelated
  directions under a single global angle.
- **Cross-Hatch** (two-direction) — two tatami passes at 90 degrees;
  denser, more stable on stretchy fabric. (Also still applied
  automatically to texture-flagged regions regardless of fill style —
  see Multi-Region Illustration Digitization above.)
- **Brick** (staggered rows) — tatami rows with alternating rows'
  needle points phase-shifted half a stitch length, for a softer, less
  visibly "laddered" look on a larger fill.

Pick a design-wide default at upload (`--fill-style` on the CLI, or the
picker on the web UI's upload form), then override just one problem
region afterward in **Manual region review** below without touching
the rest — the same "leave blank to keep the automatic/default choice"
pattern every other per-region correction already uses. See
`src/stitches/fill.py` for what each style actually generates and
`src/stitches/model.py`'s `FILL_STYLES`.

### One fill direction for the whole design

Separate from the *pattern* above is the fill **direction**, and it
matters just as much: embroidery thread is directional, so the angle a
shape is filled at decides how it catches the light.

Every region used to derive its own angle from its own medial axis.
That's mathematically reasonable and visually wrong — on a real
"Hello world!" the letters came out stitched in five different
directions at once:

| Letter | H | e | o | w | o | r | d |
|---|---|---|---|---|---|---|---|
| Angle | 173° | -99° | -99° | -176° | -98° | -69° | -44° |

H and w horizontal, e/o/o vertical, r and d diagonal — so each letter
caught the light differently and the word read as a set of mismatched
letters instead of one piece of lettering. Real digitizers give a word
or text block **one** angle for exactly this reason.

The default is now a single shared **45°** for every filled region in a
design (`src/stitches/model.py`'s `UNIFORM_FILL_ANGLE_DEG`) — 45°
because, unlike 0°/90°, it doesn't line up with the fabric's own weave
where fill rows can sink between the threads. Change it with
`--fill-angle DEG` (CLI) or the "Fill direction" dropdown (web UI), and
pass `--fill-angle per-shape` to restore per-region angles, which still
suit an illustration whose shapes should flow in their own directions
(a mascot's limbs, a swoosh) rather than text. A per-region angle
correction in **Manual region review** still overrides whatever the
design-wide setting is.

Satin columns are unaffected either way — a satin column takes its
direction from its own rails, not from this angle.

### Text & sizing tips

Two real, user-reported issues worth knowing about when digitizing text:

- **Set a "Finished size" instead of relying on the source image's own
  size.** A PNG/JPG without real DPI metadata (most screenshots and web
  exports) falls back to an assumed 96 DPI (`src/io_/load.py`) — which
  can make the tool measure a design as much smaller than you actually
  intend. If you hit a "minimum cap height" rejection on an image that
  looks normal-sized to you, this is almost always why: give an
  explicit `--width-mm`/`--height-mm` (CLI) or "Finished size" (web UI)
  for the actual physical size you want, rather than trial-and-error
  guessing at the source size. This now works correctly even from a
  too-small source (see below) — it didn't always.
- **Use a bold, simple sans-serif font for small text, not a thin serif
  one.** A regular-weight serif font's strokes (verticals in "H"/"l",
  hairline serifs) are thin *by design* — thin enough that at any
  practical embroidered-text size they fall under the 1.2mm hairline
  threshold and get digitized as a scribbly running stitch instead of a
  clean satin/fill column, which is what makes some letters in a design
  come out looking "off" or inconsistent next to others. This isn't a
  bug to fix in software -- it's the same reason real digitizers avoid
  thin/serif fonts for small embroidered text. A bold sans-serif (the
  same family this project's own test fixtures use) keeps every
  stroke thick enough to stitch cleanly at normal sizes.

A related bug is fixed: requesting a big-enough `--width-mm`/`--height-mm`
to upscale a too-small source past the 6mm minimum used to still get
rejected, because the rejection check ran on the *source* image's native
(often DPI-guessed) size before the resize that would have fixed it ever
ran (`src/pipeline.py`'s `load_scaled_region_set`). The check now
correctly runs on the size that actually matters — after scaling.

### Manual region review

A real correction workflow, not just a read-only report: every
`digitize` run through the web UI links to `/review/<job>`, which shows

- the preview with a clickable/highlighted overlay box per region,
- a summary table (visual/thread color counts, stitch-type counts,
  texture-zone count, warning count), and
- a per-region form to override stitch type, angle, density/row
  spacing, fill style, underlay on/off, border width, layer order,
  thread color, and where the machine's automatic thread trimmer cuts.

**Trim control** ("where the scissors will go"): every run reports a
real trim count (`result["trim_count"]`, counted from the actual
exported command stream) alongside the stitch count, and the Stitch
Player marks each trim with a red × distinct from a plain travel jump.
Trims are normally decided automatically by travel distance
(`src/pathing/route.py`), but a region's correction form can force one
("cut here" even on a short gap) or suppress one ("never cut here" even
on a long gap, leaving the machine to jump there with the thread still
attached) — see `StitchBlock.force_trim_before` and
`src/review/corrections.py`'s `force_trim` field.

Every trim also gets a **tie-in/tie-out lock stitch**: a tiny
there-and-back needle penetration right at the cut on both sides of it
(`src/io_/export.py`), so a trimmed thread end can't work loose off the
machine — standard practice in real digitizing software, and not
something a fabric preset or design choice tunes away (a cut thread end
needs anchoring regardless of fabric). Only an actual cut gets one; a
plain travel jump with no trim is still the same physically continuous
thread, so nothing needs anchoring there.

Leaving a field blank keeps the automatic decision; submitting only
changes the regions you touched (`src/review/corrections.py`) and
re-runs classification for every region fresh rather than caching
anything server-side — safe because extraction and classification are
deterministic (same input always re-extracts to the same regions), so
an uncorrected region always comes back with the exact decision it had
before. A correction rebuild re-exports DST/PES, the preview, and the
Stitch Player's command stream, and is validated *before* anything is
applied — an invalid field in one region's form blocks the whole
submission rather than partially applying it. See `src/jobs.py` for how
a job's corrections persist between requests and `src/review/rebuild.py`
for the rebuild itself.

### Known limitations

- **Raster preprocessing is minimal.** There's no EXIF auto-orientation,
  no alpha/GrabCut-based background separation beyond the existing
  border-pixel majority vote, and no CLAHE/bilateral pre-normalization
  before color reduction. A well-formed flat PNG/SVG works well; a
  photographed or heavily compressed source image is more likely to
  trip the photo/gradient rejection than it would with real
  preprocessing in front of it.
- Color reduction's k-means fit is capped at a bounded sample of pixels
  and the final per-pixel assignment is O(pixels × colors), which is
  fine for a typical logo/text image but not yet performance-tuned for
  a several-megapixel input — a very large upload will be slower to
  analyze (and to reject, if it turns out to be a photo) than a small one.
- The thread palette (`src/params/thread_palette.py`) is a small sample,
  not a full manufacturer catalog, and covers one brand's naming only.
- Photo-realistic digitizing (halftone/density-based tone simulation)
  is out of scope entirely — see the module docstring in
  `src/regions/color_reduce.py` and `src/regions/scope.py`'s
  photo/gradient rejection, which this milestone's color/texture work
  deliberately sits upstream of, not around.

### Web UI (local only)

A small local Flask app wraps the same pipeline with a browser UI:
upload an image, pick a fabric preset and border width, see the
preview and download the .dst/.pes, then jump into **Manual region
review** (below) to correct individual regions before committing.

```bash
pip install -r requirements.txt   # picks up Flask
python -m webapp.app
# open http://127.0.0.1:5000
```

Everything runs on your machine; nothing is uploaded anywhere else.

### Verifying an update (Windows + Linux)

If you're working across both a Windows machine and a Linux machine,
`scripts/verify.sh` (Linux/macOS) and `scripts\verify.bat` (Windows,
double-click it or run from cmd) are the same one-command routine on
each: pull the latest code, install/update dependencies, run the full
test suite, then start the web UI and open it in your browser. One
command, same result on either machine -- if it opens the browser, the
update is good; if a test fails, it stops there and tells you before
anything launches.

```bash
# Linux/macOS
./scripts/verify.sh
```

```bat
:: Windows
scripts\verify.bat
```

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
