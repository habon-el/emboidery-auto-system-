"""Rebuilds a web-UI job's stitch plan from its persisted job spec
(src/jobs.py), applying whatever per-region corrections the spec
carries. Reruns region extraction from scratch rather than caching it
-- safe because the pipeline is deterministic (src/regions/color_reduce.py,
src/regions/medial.py), so an uncorrected region always comes back with
the exact same classification it had before this rebuild.
"""
from src.jobs import JobSpec
from src.params.presets import get_preset
from src.pipeline import build_and_export, load_scaled_region_set
from src.review.corrections import override_from_stored


def rebuild_job(spec: JobSpec, out_stem: str) -> dict:
    fabric = get_preset(spec.fabric)
    region_set, warnings = load_scaled_region_set(
        spec.input_path, spec.force, spec.width_mm, spec.height_mm)
    corrections = {region_id: override_from_stored(d)
                   for region_id, d in spec.corrections.items()}
    return build_and_export(region_set, fabric, out_stem, spec.border_width_mm,
                             warnings, corrections)
