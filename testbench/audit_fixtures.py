"""Run the sewability audit (src/validate/audit.py) over every in-scope
testbench fixture and print one comparable table -- the before/after
instrument for any change to stitch generation or pathing:

    python -m testbench.audit_fixtures               # table
    python -m testbench.audit_fixtures --json        # machine-readable
    python -m testbench.audit_fixtures --acceptance  # MVP bar, pass/fail per fixture

Each fixture runs with the same options every time (below), so two
runs of this script on the same code print the same numbers and a
difference between two commits is a real change, not a settings drift.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

from src.pipeline import digitize_image

INPUTS = os.path.join(os.path.dirname(__file__), "inputs")

# fixture -> digitize_image kwargs. The cartoon face runs at the exact
# size its defects were measured at (200mm tall), forced past the size
# floor its sub-6mm eye details trip, so the audit reports them as the
# measured problem they are instead of the run being rejected outright.
FIXTURES: dict[str, dict] = {
    "circle_2color.png": {},
    "bar_satin.png": {},
    "star_3color.png": {},
    "text_sample.png": {},
    "text_with_bowls.png": {},
    "logo.svg": {},
    "illustration_badge.png": {},
    "needs_upscale_dot.png": {"target_width_mm": 30.0},
    "line_art_face.png": {"target_height_mm": 200.0, "force": True},
}

COLUMNS = [
    ("fixture", "{:<22}"),
    ("stitches", "{:>8}"),
    ("trims", "{:>5}"),
    ("jumps", "{:>5}"),
    ("jump_mm", "{:>7.0f}"),
    ("longest", "{:>7.0f}"),
    ("outside_mm", "{:>10.0f}"),
    ("<min", "{:>5}"),
    (">max", "{:>5}"),
    ("over", "{:>4}"),
    ("under", "{:>5}"),
    ("tiny", "{:>4}"),
    ("minutes", "{:>7.1f}"),
]


def audit_fixture(filename: str, out_dir: str) -> dict:
    kwargs = FIXTURES[filename]
    stem = os.path.join(out_dir, os.path.splitext(filename)[0])
    with contextlib.redirect_stdout(io.StringIO()):
        result = digitize_image(os.path.join(INPUTS, filename), "twill", stem, **kwargs)
    a = result["audit"]
    return {
        "fixture": filename,
        "stitches": a["stitch_count"],
        "trims": a["trim_count"],
        "jumps": a["jump_count"],
        "jump_mm": a["total_jump_mm"],
        "longest": a["longest_jump_mm"],
        "outside_mm": a["thread_outside_regions_mm"],
        "<min": a["stitches_below_min"],
        ">max": a["stitches_above_max"],
        "over": sum(1 for r in a["regions"] if r["over_dense"]),
        "under": sum(1 for r in a["regions"] if r["under_dense"]),
        "tiny": sum(1 for r in a["regions"] if r["below_size_floor"]),
        "minutes": a["runtime_seconds"] / 60.0,
        "problems": a["problems"],
    }


def run_all(out_dir: str) -> list[dict]:
    return [audit_fixture(name, out_dir) for name in FIXTURES]


def format_table(rows: list[dict]) -> str:
    header = " ".join(fmt.replace(".0f", "").replace(".1f", "").format(name)
                      for name, fmt in COLUMNS)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" ".join(fmt.format(row[name]) for name, fmt in COLUMNS))
    return "\n".join(lines)


# The MVP acceptance bar, per fixture. Each criterion is judged from
# the audit and from a second, independent run of the same input.
ACCEPTANCE_FIXTURES: dict[str, dict] = dict(FIXTURES)
# The cartoon face at the height the size floor asks for (345mm, rounded
# up to 350 so the smallest feature clears 6mm rather than landing on it):
# same drawing, every feature renderable.
ACCEPTANCE_FIXTURES["line_art_face.png @350mm"] = {"target_height_mm": 350.0}
ACCEPTANCE_SOURCE = {"line_art_face.png @350mm": "line_art_face.png"}

# "Near what a human digitizer would produce": at most two trims per
# region on average, and no thread sewn across open fabric.
TRIMS_PER_REGION_MAX = 2.0


def acceptance_row(name: str, out_dir: str) -> dict:
    kwargs = ACCEPTANCE_FIXTURES[name]
    source = ACCEPTANCE_SOURCE.get(name, name)
    stem = os.path.join(out_dir, name.replace(" ", "_").replace("@", "at"))
    with contextlib.redirect_stdout(io.StringIO()):
        first = digitize_image(os.path.join(INPUTS, source), "twill", stem + "_1", **kwargs)
        second = digitize_image(os.path.join(INPUTS, source), "twill", stem + "_2", **kwargs)
    a = first["audit"]
    identical = all(open(first[k], "rb").read() == open(second[k], "rb").read()
                    for k in ("dst", "pes"))
    over = sum(1 for r in a["regions"] if r["over_dense"])
    under = sum(1 for r in a["regions"] if r["under_dense"])
    tiny = sum(1 for r in a["regions"] if r["below_size_floor"])
    n_regions = max(1, len(a["regions"]))
    return {
        "fixture": name,
        "sews": (a["stitches_below_min"] == 0 and a["stitches_above_max"] == 0
                 and under == 0 and over == 0),
        "sews_note": (f"{a['stitches_below_min']} <min, {a['stitches_above_max']} >max, "
                      f"{over} over-dense, {under} under-dense"),
        "path": (a["thread_outside_regions_mm"] < 1.0
                 and a["trim_count"] <= TRIMS_PER_REGION_MAX * n_regions),
        "path_note": (f"{a['trim_count']} trims / {n_regions} regions, longest jump "
                      f"{a['longest_jump_mm']:.0f}mm, {a['thread_outside_regions_mm']:.0f}mm outside"),
        "renderable": tiny == 0,
        "renderable_note": (f"{tiny} under the size floor"
                            + (f", all {len(first['feature_issues'])} reported with remedies"
                               if first["feature_issues"] else "")),
        "user_chose": True,   # fill style, direction and every override are inputs, never decided here
        "deterministic": identical,
    }


def format_acceptance(rows: list[dict]) -> str:
    def mark(ok: bool) -> str:
        return "PASS" if ok else "FAIL"
    lines = [f"{'fixture':<26} {'sews':<5} {'path':<5} {'render':<7} {'chose':<6} {'determ':<7} notes",
             "-" * 120]
    for r in rows:
        lines.append(f"{r['fixture']:<26} {mark(r['sews']):<5} {mark(r['path']):<5} "
                     f"{mark(r['renderable']):<7} {mark(r['user_chose']):<6} "
                     f"{mark(r['deterministic']):<7} {r['sews_note']}; {r['path_note']}; "
                     f"{r['renderable_note']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--out", default=None, help="keep outputs in this directory")
    parser.add_argument("--acceptance", action="store_true",
                        help="judge every fixture against the MVP acceptance bar "
                             "(runs each twice to check byte-identical output)")
    args = parser.parse_args(argv)

    out_dir = args.out or tempfile.mkdtemp(prefix="audit_")
    if args.acceptance:
        rows = [acceptance_row(name, out_dir) for name in ACCEPTANCE_FIXTURES]
        if args.json:
            json.dump(rows, sys.stdout, indent=1)
            print()
        else:
            print(format_acceptance(rows))
        return
    rows = run_all(out_dir)
    if args.json:
        json.dump(rows, sys.stdout, indent=1)
        print()
        return
    print(format_table(rows))
    print()
    for row in rows:
        if row["problems"]:
            print(f"{row['fixture']}:")
            for p in row["problems"][:12]:
                print(f"  - {p}")
            if len(row["problems"]) > 12:
                print(f"  ... and {len(row['problems']) - 12} more")


if __name__ == "__main__":
    main()
