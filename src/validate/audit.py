"""Sewability audit: what a production digitizer would reject a design
for, measured on the actual command stream rather than eyeballed off a
preview image.

Until this existed, "is the output any good?" was answered by looking
at a PNG -- which is how a design with 122 trims and 190mm jumps
shipped without anyone noticing. Every number here is measured on the
same StitchPlan that src/io_/export.py turns into the DST/PES file, so
the audit judges what the machine will actually do, and the same
design audits identically on every run (the pipeline is deterministic;
this is a pure function of its output).

What it measures, and why each one matters on a machine:

* Travel: JUMP/TRIM counts, total and longest jump, and thread sewn
  *outside* every region (a stitch across open fabric is a float the
  customer sees; a jump there is fine). Trims are the slow, unreliable
  part of a sew-out -- each one is a mechanical cut plus a re-start,
  and a trimmer misfire is the most common machine stop.
* Stitch length: anything under the machine minimum jams the needle
  in its own thread (breaks); anything over the practical maximum
  snags and loops. Counted from the exported command stream so tie
  stitches and every split are included.
* Density: mm of top-stitch thread per mm^2 of each region, compared
  against what the fabric preset asked for. Well over target breaks
  needles and puckers the fabric; well under shows fabric through.
* Size floor: every region below the minimum feature height, with its
  measured size -- what silently ruined the pupils and highlights on
  a cartoon face at 200mm.
* Run time and thread use, so the cost of a bad path shows up in
  minutes rather than in a warning nobody reads.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pyembroidery as pe
from shapely.geometry import Point as ShapelyPoint
from shapely.ops import unary_union
from shapely.prepared import prep

from src.io_.export import stitch_plan_to_pattern
from src.io_.units import UNITS_PER_MM
from src.params.classify import Classification
from src.params.presets import FabricPreset
from src.preview.runtime import estimate_runtime_seconds
from src.regions.model import Region
from src.regions.scope import MIN_FEATURE_HEIGHT_MM
from src.stitches.model import (BORDER, FILL, FILL_CROSSHATCH,
                                 MAX_STITCH_LENGTH_MM, MIN_STITCH_LENGTH_MM,
                                 RUNNING, SATIN, StitchPlan)

# Density is judged relative to the preset's own target, not an
# absolute: a fill at 1.5x the requested thread-per-area is over-dense
# (needle breakage, puckering) and one at 0.6x is showing fabric.
DENSITY_OVER_FACTOR = 1.5
DENSITY_UNDER_FACTOR = 0.6

# A stitch counts as "outside every region" when its midpoint lies
# beyond this margin of the union of all region polygons. Pull
# compensation and rail offsets legitimately put needle points a
# fraction of a mm past a shape's mathematical edge; this is wider than
# that and far narrower than any real crossing.
OUTSIDE_MARGIN_MM = 0.6

_TOP_STITCH_TYPES = (FILL, SATIN, RUNNING, BORDER)


@dataclass
class RegionAudit:
    region_id: str
    stitch_type: str
    area_mm2: float
    height_mm: float
    # Narrowest dimension: the minimum rotated rectangle's short side.
    # A region's height can clear the floor while the region itself is
    # a hairline (a 30mm-tall stroke 0.8mm wide).
    narrowest_mm: float
    stitch_count: int
    # mm of top-stitch thread (underlay excluded) per mm^2 of region.
    density_mm_per_mm2: float
    target_density_mm_per_mm2: float
    below_size_floor: bool
    over_dense: bool
    under_dense: bool


@dataclass
class SewabilityAudit:
    stitch_count: int = 0
    color_changes: int = 0
    jump_count: int = 0
    trim_count: int = 0
    total_jump_mm: float = 0.0
    longest_jump_mm: float = 0.0
    # Thread actually sewn (not jumped) across open fabric.
    thread_outside_regions_mm: float = 0.0
    stitch_min_mm: float = 0.0
    stitch_max_mm: float = 0.0
    stitch_mean_mm: float = 0.0
    stitches_below_min: int = 0
    stitches_above_max: int = 0
    thread_length_mm: float = 0.0
    runtime_seconds: float = 0.0
    regions: list[RegionAudit] = field(default_factory=list)

    @property
    def regions_below_size_floor(self) -> list[RegionAudit]:
        return [r for r in self.regions if r.below_size_floor]

    @property
    def over_dense_regions(self) -> list[RegionAudit]:
        return [r for r in self.regions if r.over_dense]

    @property
    def under_dense_regions(self) -> list[RegionAudit]:
        return [r for r in self.regions if r.under_dense]

    def problems(self) -> list[str]:
        """The rejection list: each entry is a concrete reason a
        production digitizer would send this file back."""
        out = []
        if self.stitches_below_min:
            out.append(f"{self.stitches_below_min} stitch(es) under the "
                       f"{MIN_STITCH_LENGTH_MM}mm machine minimum (shortest "
                       f"{self.stitch_min_mm:.2f}mm) -- thread breaks.")
        if self.stitches_above_max:
            out.append(f"{self.stitches_above_max} stitch(es) over the "
                       f"{MAX_STITCH_LENGTH_MM}mm practical maximum (longest "
                       f"{self.stitch_max_mm:.1f}mm) -- loose, snags in wear.")
        if self.thread_outside_regions_mm > 1.0:
            out.append(f"{self.thread_outside_regions_mm:.0f}mm of thread sewn "
                       f"across open fabric outside every region.")
        for r in self.over_dense_regions:
            out.append(f"Region {r.region_id} ({r.stitch_type}) is over-dense: "
                       f"{r.density_mm_per_mm2:.1f} mm/mm^2 against a "
                       f"{r.target_density_mm_per_mm2:.1f} target.")
        for r in self.under_dense_regions:
            out.append(f"Region {r.region_id} ({r.stitch_type}) is under-dense: "
                       f"{r.density_mm_per_mm2:.1f} mm/mm^2 against a "
                       f"{r.target_density_mm_per_mm2:.1f} target -- fabric shows.")
        for r in self.regions_below_size_floor:
            out.append(f"Region {r.region_id} is under the {MIN_FEATURE_HEIGHT_MM}mm "
                       f"minimum feature size ({r.height_mm:.1f}mm tall, narrowest "
                       f"{r.narrowest_mm:.1f}mm).")
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["problems"] = self.problems()
        return d


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _narrowest_mm(polygon) -> float:
    rect = polygon.minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        return 0.0
    c = list(rect.exterior.coords)
    return min(_dist(c[0], c[1]), _dist(c[1], c[2]))


def _target_density(stitch_type: str, fabric: FabricPreset, fill_style: str | None,
                     texture_zone: bool, width_mm: float = 0.0) -> float:
    """mm of thread per mm^2 the preset asks for. A tatami row every
    row_spacing puts 1/row_spacing mm of thread across each mm^2; the
    two-pass styles (cross-hatch, or the automatic texture pass in
    src/stitches/build.py) add a second layer at 1.6x the spacing. A
    satin zigzag crosses the column twice per density step.

    Satin's target accounts for pull compensation, which genuinely
    lengthens every crossing by that much and so is thread the preset
    asked for, not thread to flag: on a 1.1mm letter stroke the 0.15mm
    twill compensation is 13% more thread. Judging satin against a
    bare 2/density reported ten narrow strokes across two fixtures as
    over-dense when each was doing exactly what it was told."""
    if stitch_type == SATIN:
        crossings_per_mm = 2.0 / fabric.satin_density_mm
        if width_mm <= 0:
            return crossings_per_mm
        return crossings_per_mm * (width_mm + fabric.pull_compensation_mm) / width_mm
    if stitch_type == FILL:
        base = 1.0 / fabric.fill_row_spacing_mm
        if fill_style == FILL_CROSSHATCH or texture_zone:
            base += 1.0 / (fabric.fill_row_spacing_mm * 1.6)
        return base
    return 0.0  # running stitch: a line, not an area


def audit_plan(plan: StitchPlan, fabric: FabricPreset,
               classifications: list[tuple[Region, Classification]],
               fill_style_by_element: dict[str, str] | None = None
               ) -> SewabilityAudit:
    audit = SewabilityAudit()
    fill_style_by_element = fill_style_by_element or {}

    # --- travel and stitch lengths, from the real command stream -------
    # The same STITCH/JUMP/TRIM/COLOR_CHANGE sequence the DST/PES
    # writers get, tie stitches included -- not re-derived from blocks.
    pattern = stitch_plan_to_pattern(plan)
    lengths: list[float] = []
    prev = None
    jump_landing = None
    for x, y, cmd in pattern.stitches:
        kind = cmd & pe.COMMAND_MASK
        pos = (x / UNITS_PER_MM, y / UNITS_PER_MM)
        if kind == pe.STITCH:
            if prev is not None:
                lengths.append(_dist(prev, pos))
            elif jump_landing is not None and _dist(jump_landing, pos) > 1e-9:
                # Entry after a jump that lands short of the first
                # needle point: the thread floats that distance too.
                pass
            prev = pos
            jump_landing = None
        elif kind == pe.JUMP:
            if prev is not None:
                gap = _dist(prev, pos)
                audit.jump_count += 1
                audit.total_jump_mm += gap
                audit.longest_jump_mm = max(audit.longest_jump_mm, gap)
            # A JUMP lands the needle without penetrating; the STITCH
            # that follows is the new run's entry penetration (usually
            # at the very same point), not a stitch of measurable
            # length -- so it starts a fresh run rather than measuring
            # a 0mm "stitch" from the landing point.
            prev = None
            jump_landing = pos
        elif kind == pe.TRIM:
            audit.trim_count += 1
        elif kind == pe.COLOR_CHANGE:
            audit.color_changes += 1

    audit.stitch_count = sum(1 for _, _, cmd in pattern.stitches
                             if cmd & pe.COMMAND_MASK == pe.STITCH)
    if lengths:
        audit.stitch_min_mm = min(lengths)
        audit.stitch_max_mm = max(lengths)
        audit.stitch_mean_mm = sum(lengths) / len(lengths)
        # Strictly under the floor, with a hair of tolerance so a stitch
        # generated *at* 0.3mm and rounded to 1/10mm units isn't flagged.
        audit.stitches_below_min = sum(1 for L in lengths if L < MIN_STITCH_LENGTH_MM - 1e-6)
        audit.stitches_above_max = sum(1 for L in lengths if L > MAX_STITCH_LENGTH_MM + 1e-6)
        audit.thread_length_mm = sum(lengths)
    audit.runtime_seconds = estimate_runtime_seconds(plan, audit.trim_count)

    # --- thread sewn outside every region --------------------------------
    polygons = [region.polygon for region, _ in classifications]
    if polygons:
        covered = prep(unary_union(polygons).buffer(OUTSIDE_MARGIN_MM))
        outside = 0.0
        for block in plan.blocks:
            pts = block.points_mm
            for a, b in zip(pts, pts[1:]):
                mid = ShapelyPoint((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if not covered.contains(mid):
                    outside += _dist(a, b)
        audit.thread_outside_regions_mm = outside

    # --- per-region density and size -------------------------------------
    top_thread_by_element: dict[str, float] = {}
    stitches_by_element: dict[str, int] = {}
    for block in plan.blocks:
        pts = block.points_mm
        stitches_by_element[block.element_id] = (
            stitches_by_element.get(block.element_id, 0) + len(pts))
        if block.stitch_type in _TOP_STITCH_TYPES:
            top_thread_by_element[block.element_id] = (
                top_thread_by_element.get(block.element_id, 0.0)
                + sum(_dist(a, b) for a, b in zip(pts, pts[1:])))

    for region, classification in classifications:
        rid = region.region_id
        area = region.polygon.area
        minx, miny, maxx, maxy = region.polygon.bounds
        height = maxy - miny
        density = top_thread_by_element.get(rid, 0.0) / area if area > 0 else 0.0
        target = _target_density(classification.stitch_type, fabric,
                                 fill_style_by_element.get(rid), region.texture_zone,
                                 classification.medial.avg_width_mm)
        audit.regions.append(RegionAudit(
            region_id=rid,
            stitch_type=classification.stitch_type,
            area_mm2=round(area, 2),
            height_mm=round(height, 2),
            narrowest_mm=round(_narrowest_mm(region.polygon), 2),
            stitch_count=stitches_by_element.get(rid, 0),
            density_mm_per_mm2=round(density, 2),
            target_density_mm_per_mm2=round(target, 2),
            below_size_floor=0 < max(maxx - minx, height) < MIN_FEATURE_HEIGHT_MM,
            over_dense=target > 0 and density > target * DENSITY_OVER_FACTOR,
            under_dense=target > 0 and density < target * DENSITY_UNDER_FACTOR,
        ))
    return audit


def format_audit_summary(audit: SewabilityAudit) -> str:
    minutes, secs = divmod(int(round(audit.runtime_seconds)), 60)
    lines = [
        f"Sewability: {audit.stitch_count} stitches, {audit.trim_count} trims, "
        f"{audit.jump_count} jumps ({audit.total_jump_mm:.0f}mm total, longest "
        f"{audit.longest_jump_mm:.0f}mm), {audit.color_changes} color changes, "
        f"~{minutes}m {secs:02d}s, {audit.thread_length_mm / 1000:.1f}m of thread.",
        f"  stitch length {audit.stitch_min_mm:.2f}-{audit.stitch_max_mm:.1f}mm "
        f"(mean {audit.stitch_mean_mm:.2f}); {audit.stitches_below_min} under "
        f"{MIN_STITCH_LENGTH_MM}mm, {audit.stitches_above_max} over "
        f"{MAX_STITCH_LENGTH_MM}mm; {audit.thread_outside_regions_mm:.0f}mm sewn "
        f"outside regions; {len(audit.over_dense_regions)} over-dense, "
        f"{len(audit.under_dense_regions)} under-dense, "
        f"{len(audit.regions_below_size_floor)} under the size floor.",
    ]
    return "\n".join(lines)
