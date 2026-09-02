"""Shared stitch-plan data model.

A StitchBlock is one continuous run of needle penetrations of a single
kind (an underlay pass, a fill region, a satin column, a running line).
A StitchPlan is an ordered list of blocks plus the thread palette -- it is
the thing src/pathing turns into a machine-ready command stream and
src/io_/export turns into an actual pyembroidery EmbPattern.

All coordinates are design-space millimetres; conversion to pyembroidery's
native unit happens only in src/io_/export.py.
"""
from dataclasses import dataclass, field

Point = tuple[float, float]

# Stitch block kinds
RUNNING = "running"
SATIN = "satin"
FILL = "fill"
UNDERLAY_RUN = "underlay_run"
UNDERLAY_SATIN = "underlay_satin"
# An optional denser ring of fill stitched along a region's own edge, on
# top of its interior fill, for a bolder/more raised-looking border
# without switching fabric or thread (see src/stitches/border.py).
BORDER = "border"


@dataclass
class StitchBlock:
    stitch_type: str
    points_mm: list[Point]
    color_index: int = 0
    # Region/element id this block belongs to, so pathing can keep blocks
    # from the same region adjacent and a human can re-sequence by element.
    element_id: str = ""

    def is_empty(self) -> bool:
        return len(self.points_mm) < 2


@dataclass
class ThreadColor:
    name: str
    rgb: tuple[int, int, int] = (0, 0, 0)
    # Nearest real manufacturer thread (src/params/thread_palette.py),
    # filled in by the pipeline once the source color is known. rgb above
    # stays the exact source/design color (used for preview and export)
    # regardless of the match -- these fields are the *recommendation*,
    # surfaced separately so a large delta_e reads as "approximate," not
    # silently swapped in.
    matched_thread_name: str = ""
    matched_thread_code: str = ""
    thread_delta_e: float = 0.0


@dataclass
class StitchPlan:
    blocks: list[StitchBlock] = field(default_factory=list)
    colors: list[ThreadColor] = field(default_factory=list)

    def stitch_count(self) -> int:
        return sum(len(b.points_mm) for b in self.blocks)

    def bounds_mm(self) -> tuple[float, float, float, float]:
        xs = [x for b in self.blocks for x, _ in b.points_mm]
        ys = [y for b in self.blocks for _, y in b.points_mm]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))
