# Sew-Out Checklist

A screen preview can't catch push-pull distortion, puckering, or real
satin edge quality (Section 8/9). Before calling any fabric preset
production-ready, sew a physical sample and work through this checklist.
Every number in `src/params/presets.py` is a conservative starting
default, not a measured value -- this is the loop that turns it into one.

## What "done" looks like

For each preset (`twill`, `fleece`, `knit`), you should be able to point
to a dated entry below with photos/measurements before trusting that
preset for a real order.

## Per-fabric procedure

1. **Stabilizer**: use what you'd actually use in production for this
   fabric (cutaway for knit/stretch, tearaway for stable wovens, etc).
   Note which one -- results don't transfer across stabilizers.
2. **Sew the design**: use `python -m src.cli demo --shape circle --fabric
   <preset> --out testbench/out/sewout_<preset>` (or a real logo via
   `digitize`) and actually stitch it out on the target fabric.
3. **Measure push-pull distortion**: digitize a shape with a known
   dimension (e.g. the demo circle is a 30mm-diameter circle). After
   sewing, measure the actual diameter along and across the fill/satin
   direction. Record the delta in mm -- this is what
   `pull_compensation_mm` in the preset should be tuned against.
4. **Check puckering**: look at the fabric around the design, not just
   the design itself. Visible puckering usually means underlay is
   insufficient or density is too tight for that fabric -- adjust
   `fill_underlay_inset_mm` / `fill_row_spacing_mm`.
5. **Check satin edge crispness**: edges should be clean, not fuzzy or
   gapped. Fuzzy edges suggest `satin_density_mm` is too loose; visible
   fabric show-through at the edge suggests missing/insufficient
   `satin_underlay`.
6. **Check minimum legible text**: sew the smallest text you intend to
   support on this fabric and confirm it's actually legible off the
   machine, not just in the preview. If it isn't, the fabric needs a
   larger minimum cap height than the tool's generic 6mm floor
   (Section 2) -- note that here, not in code, until it's confirmed.
7. **Record the correction back into the preset**: once you know the
   right numbers, update the relevant fields in
   `src/params/presets.py` and note it in the log below (with the
   sew-out date) so the change has a paper trail.

## Sew-out log

| Date | Preset | Stabilizer | Push-pull (mm) | Puckering? | Satin edge | Min legible text | Notes / preset changes made |
|------|--------|-----------|-----------------|------------|------------|-------------------|------------------------------|
|      |        |           |                 |            |            |                   | *(no sew-outs recorded yet)* |

## Not yet validated

As of this MVP, **no preset has been physically sewn and measured**.
Treat `twill`/`fleece`/`knit` as reasonable starting points, not proven
fabric-physics models -- especially `knit`, which is a placeholder for
stretch fabric (out of scope per Section 2) and has not been validated
on an actual knit/stretch substrate with proper stabilizing.
