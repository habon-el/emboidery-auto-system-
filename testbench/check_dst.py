"""Measure any finished embroidery file the way a machine will run it.

    python -m testbench.check_dst design.dst
    python -m testbench.check_dst old.dst new.dst      # compare two files

Unlike testbench/audit_fixtures.py, which re-runs this pipeline, this
reads a *finished* DST or PES off disk -- so it works on output from an
older version of this tool, on a file a customer sent, or on one another
package produced. Same yardstick for all of them.

What it reports, and why a machine cares:

* stitches / trims / colour changes -- a trim is a mechanical cut plus a
  re-start, the slowest and least reliable moment in a sew-out.
* jump travel -- how far the needle hops without stitching, and the
  longest single hop.
* stitches under the machine minimum -- the needle doesn't clear its own
  previous hole, the thread piles up and breaks.
* stitches over the practical maximum -- the stitch lies loose and snags
  in wear.

It cannot judge density (that needs the design's regions, which a
finished file doesn't carry) or whether the design looks right. Use
testbench/audit_fixtures.py for those.
"""
import argparse
import math
import os
import sys

import pyembroidery as pe

from src.io_.units import UNITS_PER_MM
from src.preview.runtime import (SECONDS_PER_COLOR_CHANGE, SECONDS_PER_TRIM,
                                  STITCHES_PER_MINUTE, format_runtime)
from src.stitches.model import MAX_STITCH_LENGTH_MM, MIN_STITCH_LENGTH_MM


def read_pattern(path: str) -> pe.EmbPattern:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dst":
        return pe.EmbPattern.read_dst(path)
    if ext == ".pes":
        return pe.EmbPattern.read_pes(path)
    return pe.read(path)


def measure(path: str) -> dict:
    pattern = read_pattern(path)
    lengths: list[float] = []
    jumps: list[float] = []
    trims = colour_changes = 0
    prev = None

    for x, y, cmd in pattern.stitches:
        kind = cmd & pe.COMMAND_MASK
        pos = (x / UNITS_PER_MM, y / UNITS_PER_MM)
        if kind == pe.STITCH:
            if prev is not None:
                lengths.append(math.hypot(pos[0] - prev[0], pos[1] - prev[1]))
            prev = pos
        elif kind == pe.JUMP:
            if prev is not None:
                jumps.append(math.hypot(pos[0] - prev[0], pos[1] - prev[1]))
            # A jump lands the needle without penetrating; the stitch
            # after it is an entry point, not a stitch of real length.
            prev = None
        elif kind == pe.TRIM:
            trims += 1
        elif kind == pe.COLOR_CHANGE:
            colour_changes += 1

    stitch_count = sum(1 for _, _, c in pattern.stitches
                       if c & pe.COMMAND_MASK == pe.STITCH)
    runtime = (stitch_count / STITCHES_PER_MINUTE * 60.0
               + colour_changes * SECONDS_PER_COLOR_CHANGE
               + trims * SECONDS_PER_TRIM)
    return {
        "file": os.path.basename(path),
        "stitches": stitch_count,
        "trims": trims,
        "colour_changes": colour_changes,
        "jumps": len(jumps),
        "jump_travel_mm": sum(jumps),
        "longest_jump_mm": max(jumps) if jumps else 0.0,
        "thread_m": sum(lengths) / 1000,
        "shortest_mm": min(lengths) if lengths else 0.0,
        "longest_stitch_mm": max(lengths) if lengths else 0.0,
        "under_min": sum(1 for L in lengths if L < MIN_STITCH_LENGTH_MM - 1e-6),
        "over_max": sum(1 for L in lengths if L > MAX_STITCH_LENGTH_MM + 1e-6),
        "runtime": format_runtime(runtime),
    }


ROWS = [
    ("stitches", "stitches", "{:,}"),
    ("trims", "trims (thread cuts)", "{:,}"),
    ("colour_changes", "colour changes", "{:,}"),
    ("jumps", "jumps", "{:,}"),
    ("jump_travel_mm", "jump travel (mm)", "{:,.0f}"),
    ("longest_jump_mm", "longest jump (mm)", "{:,.0f}"),
    ("under_min", f"stitches under {MIN_STITCH_LENGTH_MM}mm (thread breaks)", "{:,}"),
    ("over_max", f"stitches over {MAX_STITCH_LENGTH_MM}mm (snags)", "{:,}"),
    ("shortest_mm", "shortest stitch (mm)", "{:.2f}"),
    ("longest_stitch_mm", "longest stitch (mm)", "{:.1f}"),
    ("thread_m", "thread used (m)", "{:.1f}"),
    ("runtime", "estimated run time", "{}"),
]


def report(results: list[dict]) -> str:
    width = max(len(label) for _, label, _ in ROWS) + 2
    header = " ".join(f"{r['file']:>16}" for r in results)
    lines = [" " * width + header, "-" * (width + len(header))]
    for key, label, fmt in ROWS:
        cells = " ".join(f"{fmt.format(r[key]):>16}" for r in results)
        lines.append(f"{label:<{width}}{cells}")

    if len(results) == 2:
        before, after = results
        lines.append("")
        lines.append("What changed (a machine runs the second file):")
        for key, label, _ in ROWS:
            b, a = before[key], after[key]
            if isinstance(b, str) or b == a:
                continue
            direction = "fewer" if a < b else "more"
            if key in ("stitches", "thread_m"):
                direction = "less" if a < b else "more"
            lines.append(f"  {label}: {b:,.0f} -> {a:,.0f}  ({direction})"
                         if not isinstance(b, str) else "")
    return "\n".join(line for line in lines if line is not None)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="one or two .dst/.pes files")
    args = parser.parse_args(argv)

    results = []
    for path in args.files:
        if not os.path.exists(path):
            print(f"No such file: {path}", file=sys.stderr)
            raise SystemExit(1)
        results.append(measure(path))
    print(report(results))


if __name__ == "__main__":
    main()
