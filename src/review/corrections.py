"""Per-region manual corrections applied on top of the automatic
classification -- the manual review workflow's editable fields (stitch
type, angle, density, underlay, border width, layer order, thread
color). See src/review/rebuild.py for how these get applied and
src/jobs.py for how a job's corrections are persisted between requests.
"""
from dataclasses import asdict, dataclass, replace

from src.params.classify import Classification
from src.params.presets import FabricPreset
from src.stitches.model import FILL, RUNNING, SATIN

VALID_STITCH_TYPES = {FILL, SATIN, RUNNING}


class CorrectionValidationError(ValueError):
    """Raised on bad input from the review form -- numeric validation
    must happen before anything gets rebuilt, per the manual-review
    workflow's requirements."""


@dataclass
class RegionOverride:
    stitch_type: str | None = None
    angle_deg: float | None = None
    density_mm: float | None = None      # fill row spacing or satin density, depending on final type
    underlay: bool | None = None         # None = leave the fabric default (on)
    border_width_mm: float | None = None
    z_order: int | None = None
    thread_rgb: tuple[int, int, int] | None = None
    # Force the machine's automatic thread trimmer to cut immediately
    # before this region regardless of travel distance -- None leaves
    # the automatic distance-based rule (src/pathing/route.py) in
    # charge; True/False forces a cut on/off at this region's start.
    force_trim: bool | None = None

    def is_noop(self) -> bool:
        return all(v is None for v in asdict(self).values())


def _parse_float(raw: dict, key: str, min_value: float | None = None) -> float | None:
    val = (raw.get(key) or "").strip()
    if not val:
        return None
    try:
        f = float(val)
    except ValueError:
        raise CorrectionValidationError(f"'{key}' must be a number, got {val!r}.")
    if min_value is not None and f < min_value:
        raise CorrectionValidationError(f"'{key}' must be >= {min_value}, got {f}.")
    return f


_TRI_BOOL = {"": None, "unchanged": None, "on": True, "true": True,
             "off": False, "false": False}


def _parse_tri_bool(raw: dict, key: str) -> bool | None:
    val = (raw.get(key) or "").strip().lower()
    if val and val not in _TRI_BOOL:
        raise CorrectionValidationError(f"'{key}' must be on/off, got {raw.get(key)!r}.")
    return _TRI_BOOL.get(val)


def parse_region_override(raw: dict) -> RegionOverride:
    """raw is one region's correction fields straight from the review
    form's POST data (plain strings; an empty/missing value means
    "leave this as the automatic decision", not zero)."""
    stitch_type = (raw.get("stitch_type") or "").strip() or None
    if stitch_type and stitch_type not in VALID_STITCH_TYPES:
        raise CorrectionValidationError(
            f"'stitch_type' must be one of {sorted(VALID_STITCH_TYPES)}, got {stitch_type!r}.")

    angle_deg = _parse_float(raw, "angle_deg")
    # A row spacing/density of 0 or negative isn't "denser," it's a
    # divide-by-zero or an inverted design -- reject rather than let it
    # silently through (the same numeric-validation principle as
    # src/regions/scale.py's target-size checks).
    density_mm = _parse_float(raw, "density_mm", min_value=0.05)
    border_width_mm = _parse_float(raw, "border_width_mm", min_value=0.0)

    underlay = _parse_tri_bool(raw, "underlay")
    force_trim = _parse_tri_bool(raw, "force_trim")

    z_order_raw = (raw.get("z_order") or "").strip()
    z_order = None
    if z_order_raw:
        try:
            z_order = int(z_order_raw)
        except ValueError:
            raise CorrectionValidationError(f"'z_order' must be a whole number, got {z_order_raw!r}.")

    thread_rgb = None
    hexval = (raw.get("thread_rgb") or "").strip().lstrip("#")
    if hexval:
        if len(hexval) != 6:
            raise CorrectionValidationError(
                f"'thread_rgb' must be a 6-digit hex color, got {raw.get('thread_rgb')!r}.")
        try:
            thread_rgb = (int(hexval[0:2], 16), int(hexval[2:4], 16), int(hexval[4:6], 16))
        except ValueError:
            raise CorrectionValidationError(
                f"'thread_rgb' must be a valid hex color, got {raw.get('thread_rgb')!r}.")

    return RegionOverride(stitch_type=stitch_type, angle_deg=angle_deg, density_mm=density_mm,
                           underlay=underlay, border_width_mm=border_width_mm,
                           z_order=z_order, thread_rgb=thread_rgb, force_trim=force_trim)


def parse_correction_form(form: dict, region_ids: set[str]) -> dict[str, "RegionOverride"]:
    """Groups a flat `{region_id}::{field}` form dict (the review page's
    field-naming scheme, one <form> covering every region at once) by
    region and validates each region's fields -- raising
    CorrectionValidationError with every region's problems combined
    into one message if *any* are invalid, so nothing gets applied
    unless the whole submission validates (per the manual-review
    workflow's "validate numeric input" / "apply only the requested
    region corrections" requirements).

    region_ids restricts which regions a submission may target, so a
    stray or tampered field name can't address a region that doesn't
    exist in this job.
    """
    grouped: dict[str, dict] = {}
    for key, value in form.items():
        if "::" not in key:
            continue
        region_id, field = key.split("::", 1)
        if region_id not in region_ids:
            continue
        grouped.setdefault(region_id, {})[field] = value

    errors: list[str] = []
    overrides: dict[str, RegionOverride] = {}
    for region_id, raw in grouped.items():
        try:
            overrides[region_id] = parse_region_override(raw)
        except CorrectionValidationError as e:
            errors.append(f"region '{region_id}': {e}")
    if errors:
        raise CorrectionValidationError("; ".join(errors))
    return overrides


def override_from_stored(d: dict) -> RegionOverride:
    """Reconstructs a RegionOverride from its persisted (JSON-round-
    tripped) form -- a plain dict, with thread_rgb coming back as a
    list rather than a tuple."""
    thread_rgb = d.get("thread_rgb")
    return RegionOverride(
        stitch_type=d.get("stitch_type"), angle_deg=d.get("angle_deg"),
        density_mm=d.get("density_mm"), underlay=d.get("underlay"),
        border_width_mm=d.get("border_width_mm"), z_order=d.get("z_order"),
        thread_rgb=tuple(thread_rgb) if thread_rgb is not None else None,
        force_trim=d.get("force_trim"))


def resolve_override(classification: Classification, fabric: FabricPreset,
                      default_border_width_mm: float, override: RegionOverride | None
                      ) -> tuple[Classification, FabricPreset, float, bool]:
    """Returns (classification, fabric, border_width_mm, include_underlay)
    to actually build one region's blocks with -- the automatic
    decision stands for every field the override leaves as None."""
    if override is None:
        return classification, fabric, default_border_width_mm, True

    stitch_type = override.stitch_type or classification.stitch_type
    angle_deg = override.angle_deg if override.angle_deg is not None else classification.angle_deg
    if stitch_type != classification.stitch_type or angle_deg != classification.angle_deg:
        note = " [manually overridden]"
        classification = replace(
            classification, stitch_type=stitch_type, angle_deg=angle_deg,
            reason=classification.reason + note if not classification.reason.endswith(note) else classification.reason,
            confidence=1.0 if override.stitch_type else classification.confidence,
            redirected_from_satin=False)

    if override.density_mm is not None:
        if stitch_type == SATIN:
            fabric = replace(fabric, satin_density_mm=override.density_mm)
        else:
            fabric = replace(fabric, fill_row_spacing_mm=override.density_mm)

    border_width_mm = (override.border_width_mm if override.border_width_mm is not None
                        else default_border_width_mm)
    include_underlay = override.underlay if override.underlay is not None else True

    return classification, fabric, border_width_mm, include_underlay
