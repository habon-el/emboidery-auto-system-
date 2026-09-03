"""Persisted job state for the web UI's manual-review workflow.

Only the *inputs* to a digitize request get persisted (input path,
fabric, border, resize target, force flag, and per-region corrections)
-- not the computed regions/classifications themselves. That's enough
to redo the whole thing later from a fresh browser request with no
server-side session state, because the pipeline is deterministic (see
src/regions/color_reduce.py and src/regions/medial.py's seeded
randomness): the same input always re-extracts to the exact same
regions, so an uncorrected region comes back with the exact same
classification it had before, and only the corrected regions actually
change on a rebuild.
"""
import json
import os
from dataclasses import asdict, dataclass, field

from src.stitches.model import DEFAULT_FILL_STYLE

SPEC_FILENAME = "job_spec.json"


@dataclass
class JobSpec:
    input_path: str
    fabric: str
    border_width_mm: float = 0.0
    force: bool = False
    width_mm: float | None = None
    height_mm: float | None = None
    # The design-wide default fill pattern (src/stitches/model.py's
    # FILL_STYLES), chosen once at upload; a per-region correction can
    # still override just one region (RegionOverride.fill_style below).
    default_fill_style: str = DEFAULT_FILL_STYLE
    # region_id -> a RegionOverride's fields, i.e. dataclasses.asdict()
    # of the result of src/review/corrections.py's parse_region_override()
    # -- already validated and type-converted (bool/float/int/tuple, not
    # the raw HTML-form strings) by the time it's stored here. Build
    # this dict via parse_region_override() + asdict(), never by
    # stuffing raw form fields straight in -- override_from_stored()
    # (used to read it back out) expects already-typed values.
    corrections: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "JobSpec":
        return JobSpec(
            input_path=d["input_path"], fabric=d["fabric"],
            border_width_mm=d.get("border_width_mm", 0.0),
            force=d.get("force", False),
            width_mm=d.get("width_mm"), height_mm=d.get("height_mm"),
            default_fill_style=d.get("default_fill_style", DEFAULT_FILL_STYLE),
            corrections=d.get("corrections", {}))


def spec_path(job_dir: str) -> str:
    return os.path.join(job_dir, SPEC_FILENAME)


def save_job_spec(job_dir: str, spec: JobSpec) -> str:
    path = spec_path(job_dir)
    with open(path, "w") as f:
        json.dump(spec.to_dict(), f, indent=2)
    return path


def load_job_spec(job_dir: str) -> JobSpec:
    with open(spec_path(job_dir)) as f:
        return JobSpec.from_dict(json.load(f))


def has_job_spec(job_dir: str) -> bool:
    return os.path.exists(spec_path(job_dir))
