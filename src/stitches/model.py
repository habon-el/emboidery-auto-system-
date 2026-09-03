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

# Fill *styles* -- how a FILL-type region's interior is actually covered,
# independent of the stitch-type decision above. A human (or a customer,
# via the same dropdown) picks one of these instead of the system always
# defaulting to one look; see src/stitches/fill.py for what each one
# actually stitches and testbench/generate_fill_previews.py for the real
# rendered swatch shown next to each choice in the web UI.
FILL_TATAMI = "tatami"
FILL_CONTOUR = "contour"
FILL_CROSSHATCH = "crosshatch"
FILL_BRICK = "brick"
FILL_STYLES = (FILL_TATAMI, FILL_CONTOUR, FILL_CROSSHATCH, FILL_BRICK)
DEFAULT_FILL_STYLE = FILL_TATAMI

# One shared fill *direction* for every filled region in a design,
# rather than each region deriving its own angle from its own medial
# axis (src/regions/medial.py's angle_deg).
#
# Per-shape angles are mathematically reasonable and visually wrong: in
# a real "Hello world!" run, H and w came out stitched horizontally,
# e/o/o vertically, r at -69 degrees and d at -44 -- five directions in
# a single word. Embroidery thread is directional, so each of those
# reflects light differently and the word reads as a set of mismatched
# letters rather than one piece of lettering. Real digitizers give a
# word (or any text block) one angle for exactly that reason -- it's
# what "set stitch angle lines to control light reflection" means.
#
# 45 degrees is the standard default: unlike 0/90 it doesn't line up
# with the fabric's own weave (where fill rows can sink between the
# threads), and it reads evenly under light from any direction.
#
# None restores per-shape angles, which is still the right choice for
# an illustration whose shapes genuinely should flow in their own
# directions (a mascot's limbs, a swoosh) rather than text.
UNIFORM_FILL_ANGLE_DEG = 45.0

FILL_STYLE_LABELS = {
    FILL_TATAMI: "Tatami (standard rows)",
    FILL_CONTOUR: "Contour (follows the shape's edge)",
    FILL_CROSSHATCH: "Cross-Hatch (two-direction)",
    FILL_BRICK: "Brick (staggered rows)",
}


@dataclass
class StitchBlock:
    stitch_type: str
    points_mm: list[Point]
    color_index: int = 0
    # Region/element id this block belongs to, so pathing can keep blocks
    # from the same region adjacent and a human can re-sequence by element.
    element_id: str = ""
    # Overrides the machine's automatic thread trimmer for the travel
    # immediately before this block: None (default) leaves the
    # automatic distance rule in charge (src/pathing/route.py); True
    # forces a cut even if the gap is short; False suppresses a cut
    # even if the gap is long enough that the automatic rule would
    # normally call for one (the machine still jumps there -- it just
    # doesn't cut the thread first, leaving a float). Set by a manual
    # region correction (src/review/corrections.py's force_trim).
    force_trim_before: bool | None = None

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
