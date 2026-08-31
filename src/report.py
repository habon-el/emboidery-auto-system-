"""Shared "write files + print summary" step used by every CLI command."""
import os

from src.io_.export import write_pattern
from src.preview.render import render_preview
from src.preview.runtime import estimate_runtime_seconds, format_runtime
from src.preview.stitch_export import export_stitch_json
from src.stitches.model import StitchPlan


def write_and_report(plan: StitchPlan, out_stem: str) -> dict:
    """Writes the DST/PES/preview/stitch-player-JSON files, prints the CLI
    summary, and returns the same info as a dict so non-CLI callers (e.g.
    the web UI in webapp/app.py) can use it without scraping stdout."""
    out_dir = os.path.dirname(out_stem)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    paths = write_pattern(plan, out_stem)
    preview_path = render_preview(plan, f"{out_stem}_preview.png")
    stitches_json_path = export_stitch_json(plan, f"{out_stem}_stitches.json")
    runtime_s = estimate_runtime_seconds(plan)
    stitch_count = plan.stitch_count()

    print(f"Wrote {paths['dst']}")
    print(f"Wrote {paths['pes']}")
    print(f"Wrote {preview_path}")
    print(f"Stitch count: {stitch_count}")
    print(f"Estimated run time: {format_runtime(runtime_s)}")

    return {
        "dst": paths["dst"],
        "pes": paths["pes"],
        "preview": preview_path,
        "stitches_json": stitches_json_path,
        "stitch_count": stitch_count,
        "runtime_seconds": runtime_s,
        "runtime_formatted": format_runtime(runtime_s),
    }
