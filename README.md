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
  (a layer among regions of the same color -- every raster region of a
  color shares one, since same-color raster regions can never overlap)
  that the sew order (`src/pathing/order.py`) treats as a hard
  constraint, overridable per region in the manual review workflow
  below. Regions on the same layer sew nearest-first.

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
  intend. If you hit a "minimum feature size" rejection on an image that
  looks normal-sized to you, this is almost always why (the rejection
  itself now says what height would clear the floor): give an
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

### Complex shapes: fill never sews across open fabric

Row segments are joined into a continuous run only when the stitch
connecting them actually stays **inside** the shape
(`src/stitches/fill.py`'s `_runs_from_segments`); otherwise the run
ends and `src/pathing/route.py` puts a real jump there.

This used to be a distance guess instead — join anything closer than
2.5x a stitch length. That's harmless on a convex blob, which is why
simple test shapes never caught it, but wrong on anything concave or
multi-part: running a multi-region badge illustration through the
pipeline showed up to **271mm of thread per region being sewn straight
across open fabric** — through a star's notches, across a ring's hole —
in individual stitches up to 7.4mm long, because those gaps happened to
fall under the threshold.

The containment test runs against the shape grown by a hair
(`CONTAINMENT_EPSILON_MM`): a connector running exactly *along* an edge
is geometrically ambiguous, and without that nudge shapely flips
between "inside" and "outside" on floating-point jitter, splitting
edge-hugging runs at random and costing a needless trim each time.

### Curved satin outlines (line art)

Outlining a curve with a satin column is *the* fundamental technique for
cartoon and line-art digitizing, and the pipeline could not do it. The
satin test required a shape to fill at least 55% of its own bounding
rectangle, which only a **straight** band ever does — a curve fills
almost none of it. Running a cartoon face through the pipeline, every
black outline measured elongation 14x–30x with rectangularity
0.04–0.30, so all of them fell through to fill and came out as mushy
blobs instead of crisp lines.

A stroke is now recognised from its own medial axis instead
(`src/params/classify.py`): long relative to its width measured along
its **centerline** rather than across a bounding box, near-constant
width down that length, and an area that matches centerline × width.

Three things make that safe:

- **A column per stroke.** Line art doesn't extract as tidy separate
  strokes — every outline touches its neighbours, so a whole black
  layer comes out as one connected branching region, of which a single
  column could only trace 33%. The skeleton is split at its junctions
  and each branch gets its own column (`_split_into_branches`).
- **Satin only when it covers the whole stroke.** Anything the columns
  can't fully cover falls back to fill, which covers everything by
  construction. Without this a letter "o" — a ring whose skeleton
  can't always be reassembled into one loop — came out stitched as a
  "c".
- **Thin strokes only** (`STROKE_MAX_WIDTH_MM`). Rails derived from a
  medial axis approximate the true boundary, and at a badge ring's 10mm
  width that approximation shows as a ragged, flaring edge where a
  plain fill was clean. Wide bands keep the old behaviour.

Shapes a single column can't honestly represent still fill: a star or a
plus sign, whose branches are as wide as they are long, and any blob.

A side effect worth knowing: **text now comes out as satin columns**
rather than tatami fill, which is what a real digitizer would do for
lettering — letter bowls ("o", "e") still fill, since their rings fail
the coverage gate above.

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

### Sewability audit, sew order, and the small-feature policy

Every digitize result carries a **sewability audit** (`src/validate/audit.py`,
`result["audit"]`, shown on the web UI's result page): what a production
digitizer would reject the file for, measured on the exported command
stream rather than eyeballed off a preview -- trims, jumps and longest
jump, thread sewn across open fabric outside every region, the stitch-
length distribution against the 0.3mm machine minimum and 7mm practical
maximum, each region's top-stitch density against the fabric preset's
own target, regions under the size floor, run time and thread use.

```bash
python -m testbench.audit_fixtures               # one comparable table over every fixture
python -m testbench.audit_fixtures --acceptance  # the MVP bar, pass/fail per fixture
python -m testbench.check_dst old.dst new.dst    # measure any finished file, or compare two
```

`check_dst` reads a *finished* DST/PES off disk rather than re-running
the pipeline, so it works on output from an older version of this tool,
on a file a customer sent, or on one another package produced -- the
same yardstick for all of them. It is how the sub-minimum-stitch bug
below was caught.

The audit is the before/after instrument for anything that touches
stitch generation or pathing. It found, and the fixes are measured by it:

- **Satin was stitched at 2-4x the preset's density.** A pixel skeleton
  steps in 45-degree increments; offsetting rails along its jagged
  normals turned a 34mm column into 150mm of rail zigzag, and stitch
  count followed rail length. The centerline is now smoothed over about
  one width before rails are offset (`src/regions/medial.py`).
- **Every output carried sub-0.3mm stitches** (2,000 on the cartoon face):
  `resample_path` kept every pixel-resolution vertex as a needle point.
  Stitches are now placed by arc length, corners kept only where the
  path genuinely turns, and the export refuses to write a stitch under
  the machine minimum however it arrived (`src/stitches/running.py`,
  `src/io_/export.py`).
- **Sew order** (`src/pathing/order.py`): fill colors first (largest
  first), outline colors last; each element finishes (underlay, top
  stitching, border) before the next starts; the nearest free element
  sews next; and a branching satin network -- a letter with a crossbar,
  connected line art -- sews as one continuous pass, travelling down each
  branch and satining back, so nothing inside it is ever trimmed
  (`src/stitches/satin_network.py`). A word's trims went 17 -> 5; the
  cartoon face's 116 -> 64 with jump travel 5.4m -> 2.4m. The summary
  reports `color_sew_order`.
- **Split satin** past the 7mm maximum and **pull compensation on fills**
  (rows extend along their direction by the preset's amount, as satin
  rails always have).
- **Short stitches on tight curves.** On a curve the inner rail is
  shorter than the outer, so evenly spaced crossings pile their inner
  needle points together -- measured 0.013mm apart on a letter bowl,
  and invisible to the minimum-stitch guard because those two points
  are not consecutive in stitch order. On fabric that perforates the
  inner edge until the thread cuts it. Where a rail bunches, alternate
  crossings now stop short of it, so the inner penetrations alternate
  between the rail and a point inset from it. Same-side gaps under the
  machine minimum: 25.1% -> 0.7% on a word, 7.7% -> 1.1% on the face.
- **Stitch lengths are checked on the file's own 1/10mm grid.** Every
  stitch format stores coordinates there, and a 0.30mm stitch running
  at 45 degrees has 0.212mm components that each snap to 0.2mm -- a
  0.283mm stitch in the delivered file. Checking the floats upstream
  let 125 of those into a cartoon-face DST the audit called clean.
  Points are now snapped before the minimum is enforced, and tie
  stitches are 0.45mm so they survive the snap.

The **small-feature policy** (`src/validate/features.py`) replaces the
bare-number rejection: the size floor is judged on a feature's overall
size (not its height alone), the rejection says the design height that
clears it, and a forced run lists every region that cannot render at
this size with numeric remedies -- scale to X mm, drop it (it merges
into whatever surrounds it), or for a fill squeezed thin by what sits
inside it, drop those instead. Nothing is applied on its own: a drop is
a per-region choice on the review page (`RegionOverride.drop`), recorded
like any other correction, and filling the hole the dropped region sat in.

### Known limitations

- **Satin over-density where strokes meet.** A letter's stroke branches
  each get a full column, and they overlap at the junction; the audit
  still reports a few short letters (an "e" at 6mm cap height) and
  small closed outlines at ~1.5x the preset's density. A human digitizer
  trims the branch ends back at the junction by hand.
- **Trims inside multi-part fills.** A fill broken up by holes (a face
  around its eyes) is sewn run by run; runs more than 6mm apart still
  trim. Real digitizers travel between them under a later-sewn region
  or along the edge, which is not done here.
- **A few inner-edge penetrations still bunch** where *both* rails are
  tight at once (about 1% of same-side gaps on the cartoon face). Short
  stitches only pull back one side of a crossing, since shortening both
  would leave a gap up the middle of the column.
- **SVG paint order is not captured** as `z_order`; every SVG region
  sits on one layer and sews nearest-first.

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
python -m testbench.audit_fixtures --acceptance   # the MVP bar, per fixture
```

### Physical validation

A screen preview cannot catch push-pull distortion, puckering, or real
satin edge quality. See `testbench/SEWOUT_CHECKLIST.md` before calling any
preset production-ready.

### Project layout

See `src/` (io_, regions, stitches, params, pathing, preview, validate,
cli.py), `tests/`, and `testbench/` (inputs/expected/out).
