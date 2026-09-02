"""Local web UI for the embroidery editor.

Run it with:

    source .venv/bin/activate
    pip install -r requirements.txt   # picks up Flask if not already installed
    python -m webapp.app

Then open http://127.0.0.1:5000 in a browser. Everything runs locally --
no data leaves your machine. This is a thin UI over src/pipeline.py; it
does not duplicate any digitizing logic.
"""
import os
import uuid

from flask import Flask, abort, request, send_from_directory
from werkzeug.utils import secure_filename

from src.params.presets import PRESETS
from src.pipeline import digitize_image
from src.regions.model import DigitizeScopeError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def _page(body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Embroidery Editor</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 780px;
         margin: 40px auto; padding: 0 20px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 1.6rem; }}
  .card {{ background: white; border: 1px solid #ddd; border-radius: 10px;
           padding: 24px; margin-bottom: 20px; }}
  label {{ display: block; margin: 14px 0 4px; font-weight: 600; font-size: 0.9rem; }}
  select, input[type=file], input[type=number] {{ padding: 8px; border-radius: 6px;
           border: 1px solid #ccc; width: 100%; box-sizing: border-box; }}
  button {{ margin-top: 20px; padding: 10px 22px; background: #1c5aaa; color: white;
            border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; }}
  button:hover {{ background: #164683; }}
  .warn {{ background: #fff8e1; border: 1px solid #f0d385; border-radius: 8px;
           padding: 12px 16px; margin: 12px 0; font-size: 0.9rem; }}
  .error {{ background: #fdecea; border: 1px solid #f2b8b5; border-radius: 8px;
            padding: 14px 16px; }}
  .stat {{ display: inline-block; margin-right: 24px; font-size: 0.95rem; }}
  .stat b {{ display: block; font-size: 1.3rem; }}
  img.preview {{ max-width: 100%; border: 1px solid #ddd; border-radius: 8px; }}
  a.download {{ display: inline-block; margin: 8px 12px 0 0; padding: 8px 16px;
                background: #eee; border-radius: 6px; text-decoration: none; color: #222; }}
  a.download:hover {{ background: #ddd; }}
  .back {{ font-size: 0.9rem; }}
  #stitchCanvas {{ border: 1px solid #ddd; border-radius: 8px; background: white;
                   display: block; max-width: 100%; }}
  .player-controls {{ display: flex; align-items: center; gap: 12px; margin-top: 10px;
                       flex-wrap: wrap; }}
  .player-controls button {{ margin: 0; padding: 8px 16px; }}
  .player-controls input[type=range] {{ flex: 1; min-width: 160px; }}
  .player-controls select {{ width: auto; padding: 6px; }}
  #stitchCounter {{ font-variant-numeric: tabular-nums; font-size: 0.9rem; color: #444; min-width: 90px; }}
  .legend {{ display: flex; gap: 16px; margin-top: 8px; font-size: 0.85rem; color: #555; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 14px; height: 3px; display: inline-block; }}
  .summary-bar {{ display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 14px 0;
                  font-size: 0.88rem; color: #333; }}
  .summary-bar b {{ color: #111; }}
  .summary-bar .review {{ color: #a94442; font-weight: 600; }}
  table.regions {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.85rem; }}
  table.regions th, table.regions td {{ text-align: left; padding: 6px 8px;
                                         border-bottom: 1px solid #eee; }}
  table.regions th {{ color: #666; font-weight: 600; font-size: 0.78rem;
                       text-transform: uppercase; letter-spacing: 0.02em; }}
  table.regions tr.needs-review {{ background: #fff8e1; }}
  .chip {{ display: inline-block; padding: 1px 8px; border-radius: 100px;
           font-size: 0.75rem; font-weight: 600; }}
  .chip.satin {{ background: #e3ecfa; color: #1c5aaa; }}
  .chip.fill {{ background: #eafaf0; color: #1a7a41; }}
  .chip.running {{ background: #f3ecfa; color: #6a3aa9; }}
  .thread-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px;
                 margin-right: 5px; vertical-align: -1px; box-shadow: 0 0 0 1px rgba(0,0,0,.15) inset; }}
  details.region-details summary {{ cursor: pointer; font-weight: 600; margin-top: 18px; }}
</style>
</head>
<body>
<h1>🪡 Embroidery Editor</h1>
{body}
</body>
</html>"""


UPLOAD_FORM = f"""
<div class="card">
  <p>Upload a clean, flat 2-4 color logo/text image (PNG/JPG/SVG). Photos
  and gradients will be rejected rather than digitized badly -- that's
  intentional.</p>
  <form action="/digitize" method="post" enctype="multipart/form-data">
    <label>Image file</label>
    <input type="file" name="image" accept=".png,.jpg,.jpeg,.svg" required>

    <label>Fabric preset</label>
    <select name="fabric">
      {"".join(f'<option value="{name}">{name}</option>' for name in sorted(PRESETS))}
    </select>

    <label>Finished size (mm, optional)</label>
    <div style="display:flex;gap:10px;">
      <input type="number" name="width_mm" placeholder="width" min="1" step="0.5">
      <input type="number" name="height_mm" placeholder="height" min="1" step="0.5">
    </div>
    <p style="font-size:0.85rem;color:#666;margin-top:4px;">
      Resize the artwork to this finished size before stitching (leave
      blank to use the source image's own size). Give just one and the
      other follows the aspect ratio; give both for an exact fit.
    </p>

    <label>Border width (mm, 0 = disabled)</label>
    <input type="number" name="border" value="0" min="0" max="10" step="0.5">
    <p style="font-size:0.85rem;color:#666;margin-top:4px;">
      A denser fill ring stitched along each shape's own edge, on top of
      its interior fill, for a bolder/more raised-looking border.
    </p>

    <label style="display:flex;align-items:center;gap:8px;font-weight:normal;">
      <input type="checkbox" name="force" value="1" style="width:auto;">
      Force -- digitize anyway if this looks like a photo or has detail
      below the minimum size, instead of rejecting
    </label>
    <p style="font-size:0.85rem;color:#666;margin-top:4px;">
      These checks exist because a needle physically can't render detail
      that small -- forcing past them doesn't change that, just skips
      the warning. Check the preview carefully if you use this.
    </p>

    <button type="submit">Digitize</button>
  </form>
</div>
"""


@app.route("/")
def index():
    return _page(UPLOAD_FORM)


# Plain (non f-string) JS template -- {{JOB_ID}} is replaced with str.replace,
# not str.format, so the JS's own { } braces need no escaping.
STITCH_PLAYER_JS = """
<script>
(function () {
  const jobId = "{{JOB_ID}}";
  const canvas = document.getElementById('stitchCanvas');
  const ctx = canvas.getContext('2d');
  const slider = document.getElementById('stitchSlider');
  const playBtn = document.getElementById('playBtn');
  const counter = document.getElementById('stitchCounter');
  const speedSel = document.getElementById('speedSel');

  let steps = [], colors = ['#000000'], playing = false;
  let minX = 0, minY = 0, pxPerMm = 4;

  fetch('/outputs/' + jobId + '/design_stitches.json')
    .then(r => r.json())
    .then(data => { steps = data.steps; colors = data.colors; setup(); })
    .catch(() => { counter.textContent = 'player unavailable'; });

  function setup() {
    let maxX = -Infinity, maxY = -Infinity;
    minX = Infinity; minY = Infinity;
    steps.forEach(s => {
      if (s.x < minX) minX = s.x; if (s.x > maxX) maxX = s.x;
      if (s.y < minY) minY = s.y; if (s.y > maxY) maxY = s.y;
    });
    const margin = 4;
    minX -= margin; minY -= margin; maxX += margin; maxY += margin;
    const wMm = Math.max(1, maxX - minX), hMm = Math.max(1, maxY - minY);
    pxPerMm = Math.min(640 / wMm, 480 / hMm, 16);
    canvas.width = Math.max(60, wMm * pxPerMm);
    canvas.height = Math.max(60, hMm * pxPerMm);

    slider.max = Math.max(0, steps.length - 1);
    slider.value = slider.max;
    render(parseInt(slider.value, 10));
  }

  function toPx(x, y) { return [(x - minX) * pxPerMm, (y - minY) * pxPerMm]; }

  function render(idx) {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    let colorIdx = 0, prev = null;
    for (let i = 0; i <= idx && i < steps.length; i++) {
      const s = steps[i];
      if (s.t === 'color_change') { colorIdx = (colorIdx + 1) % colors.length; prev = null; continue; }
      if (s.t === 'trim' || s.t === 'end') { prev = null; continue; }
      const [px, py] = toPx(s.x, s.y);
      if (prev) {
        ctx.beginPath();
        ctx.moveTo(prev[0], prev[1]);
        ctx.lineTo(px, py);
        if (s.t === 'jump') {
          ctx.strokeStyle = '#bbbbbb'; ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
        } else {
          ctx.strokeStyle = colors[colorIdx] || '#000000'; ctx.setLineDash([]); ctx.lineWidth = 1.6;
        }
        ctx.stroke();
      }
      prev = [px, py];
    }
    counter.textContent = (idx + 1) + ' / ' + steps.length;
  }

  slider.addEventListener('input', () => {
    playing = false; playBtn.textContent = '▶ Play';
    render(parseInt(slider.value, 10));
  });

  function tick() {
    if (!playing) return;
    const speed = parseInt(speedSel.value, 10);
    let idx = parseInt(slider.value, 10) + speed;
    if (idx >= steps.length - 1) { idx = steps.length - 1; playing = false; playBtn.textContent = '▶ Play'; }
    slider.value = idx;
    render(idx);
    if (playing) setTimeout(tick, 16);
  }

  playBtn.addEventListener('click', () => {
    if (parseInt(slider.value, 10) >= steps.length - 1) slider.value = 0;
    playing = !playing;
    playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
    if (playing) tick();
  });
})();
</script>
"""


def _stitch_player_html(job_id: str) -> str:
    js = STITCH_PLAYER_JS.replace("{{JOB_ID}}", job_id)
    return f"""
<div style="margin-top:20px;">
  <label style="margin-bottom:6px;">Stitch Player -- scrub or play back the actual sew order</label>
  <canvas id="stitchCanvas" width="640" height="480"></canvas>
  <div class="player-controls">
    <button type="button" id="playBtn">&#9654; Play</button>
    <input type="range" id="stitchSlider" min="0" max="0" value="0">
    <span id="stitchCounter">0 / 0</span>
    <select id="speedSel">
      <option value="1">1x</option>
      <option value="5" selected>5x</option>
      <option value="20">20x</option>
      <option value="60">60x</option>
    </select>
  </div>
  <div class="legend">
    <span><span class="swatch" style="background:#333;"></span>stitch</span>
    <span><span class="swatch" style="background:#bbb;border-top:1px dashed #999;"></span>jump/travel</span>
  </div>
</div>
{js}"""


def _analysis_summary_html(result: dict) -> str:
    """Read-only view of the Multi-Region Illustration Digitization
    milestone's analysis summary (item 11) -- the counts panel plus a
    per-region table with each classification's reason, confidence, and
    matched thread. Interactive per-region correction (changing stitch
    type/density/angle/etc. and re-rendering just that region) is the
    next step on top of this, not yet built -- this is the read-only
    "see the decisions" half of that flow.
    """
    s = result["summary"]
    review_class = "review" if s["warnings_requiring_review"] else ""
    summary_bar = f"""
<div class="summary-bar">
  <span><b>{s['visual_colors_detected']}</b> visual colors detected</span>
  <span><b>{s['thread_colors_selected']}</b> thread colors selected</span>
  <span><b>{s['filled_regions']}</b> filled regions</span>
  <span><b>{s['satin_columns']}</b> satin columns</span>
  <span><b>{s['running_stitch_details']}</b> running-stitch details</span>
  <span><b>{s['texture_zones']}</b> texture zones</span>
  <span class="{review_class}"><b>{s['warnings_requiring_review']}</b> warning(s) requiring review</span>
</div>"""

    def row(r: dict) -> str:
        cls = "needs-review" if r["needs_review"] else ""
        delta_note = (f" (Δ{r['thread_delta_e']:.1f})" if r["thread_delta_e"] > 0.5 else "")
        texture = "yes" if r["texture_zone"] else "&ndash;"
        return f"""<tr class="{cls}">
  <td>{r['id']}</td>
  <td><span class="chip {r['stitch_type']}">{r['stitch_type']}</span></td>
  <td><span class="thread-dot" style="background:{r['thread_rgb_hex']};"></span>{r['thread_name']}{delta_note}</td>
  <td>{r['confidence']:.2f}</td>
  <td>{texture}</td>
  <td style="color:#666;">{r['reason']}</td>
</tr>"""

    rows = "".join(row(r) for r in result["regions"])
    table = f"""
<details class="region-details" open>
  <summary>Per-region analysis ({len(result['regions'])} regions)</summary>
  <div style="overflow-x:auto;">
    <table class="regions">
      <tr><th>Region</th><th>Stitch type</th><th>Thread</th><th>Confidence</th><th>Texture</th><th>Why</th></tr>
      {rows}
    </table>
  </div>
</details>"""
    return summary_bar + table


def _parse_optional_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _run_and_render(job_id: str, input_path: str, fabric: str, border: float,
                     force: bool, width_mm: float | None = None,
                     height_mm: float | None = None) -> tuple[str, int]:
    job_dir = os.path.dirname(input_path)
    out_stem = os.path.join(job_dir, "design")

    try:
        result = digitize_image(input_path, fabric, out_stem,
                                 border_width_mm=border, force=force,
                                 target_width_mm=width_mm, target_height_mm=height_mm)
    except DigitizeScopeError as e:
        retry = "" if force else f"""
<form action="/force/{job_id}" method="post" style="margin-top:12px;">
  <input type="hidden" name="fabric" value="{fabric}">
  <input type="hidden" name="border" value="{border}">
  <input type="hidden" name="width_mm" value="{width_mm or ''}">
  <input type="hidden" name="height_mm" value="{height_mm or ''}">
  <button type="submit" style="background:#a94442;">Force digitize anyway</button>
</form>"""
        return _page(f'<div class="card error"><p><b>Rejected:</b> {e}</p>'
                      f'{retry}'
                      f'<p class="back"><a href="/">&larr; try another image</a></p>'
                      f'</div>'), 200
    except Exception as e:  # noqa: BLE001 -- surface any pipeline error to the UI, not a 500 page
        return _page(f'<div class="card error"><p><b>Error:</b> {e}</p>'
                      f'<p class="back"><a href="/">&larr; try another image</a></p></div>'), 500

    warnings_html = "".join(f'<div class="warn">⚠️ {w}</div>' for w in result["warnings"])

    return _page(f"""
<div class="card">
  <p class="stat"><b>{result['stitch_count']}</b>stitches</p>
  <p class="stat"><b>{result['runtime_formatted']}</b>est. run time</p>
  <p class="stat"><b>{fabric}</b>fabric</p>
  {warnings_html}
  {_analysis_summary_html(result)}
  <div style="margin-top:16px;">
    <img class="preview" src="/outputs/{job_id}/design_preview.png" alt="Stitch preview">
  </div>
  <div>
    <a class="download" href="/outputs/{job_id}/design.dst" download>Download .DST</a>
    <a class="download" href="/outputs/{job_id}/design.pes" download>Download .PES</a>
  </div>
  {_stitch_player_html(job_id)}
</div>
<p class="back"><a href="/">&larr; digitize another image</a></p>
"""), 200


@app.route("/digitize", methods=["POST"])
def digitize():
    file = request.files.get("image")
    if not file or file.filename == "":
        return _page('<div class="card error"><p>No file selected.</p>'
                      '<p class="back"><a href="/">&larr; back</a></p></div>'), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return _page(f'<div class="card error"><p>Unsupported file type '
                      f'"{ext}". Use PNG, JPG, or SVG.</p>'
                      f'<p class="back"><a href="/">&larr; back</a></p></div>'), 400

    fabric = request.form.get("fabric", "twill")
    if fabric not in PRESETS:
        fabric = "twill"
    try:
        border = float(request.form.get("border", "0") or 0)
    except ValueError:
        border = 0.0
    force = request.form.get("force") == "1"
    width_mm = _parse_optional_float(request.form.get("width_mm"))
    height_mm = _parse_optional_float(request.form.get("height_mm"))

    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(RESULTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, f"input{ext}")
    file.save(input_path)

    return _run_and_render(job_id, input_path, fabric, border, force, width_mm, height_mm)


@app.route("/force/<job_id>", methods=["POST"])
def force_digitize(job_id):
    """Re-run a rejected job with force=True, reusing the already-saved
    upload so the user doesn't have to pick the file again."""
    job_dir = os.path.join(RESULTS_DIR, secure_filename(job_id))
    if not os.path.isdir(job_dir):
        abort(404)
    matches = [f for f in os.listdir(job_dir) if f.startswith("input.")]
    if not matches:
        abort(404)
    input_path = os.path.join(job_dir, matches[0])

    fabric = request.form.get("fabric", "twill")
    if fabric not in PRESETS:
        fabric = "twill"
    try:
        border = float(request.form.get("border", "0") or 0)
    except ValueError:
        border = 0.0
    width_mm = _parse_optional_float(request.form.get("width_mm"))
    height_mm = _parse_optional_float(request.form.get("height_mm"))

    return _run_and_render(job_id, input_path, fabric, border, force=True,
                            width_mm=width_mm, height_mm=height_mm)


@app.route("/outputs/<job_id>/<path:filename>")
def outputs(job_id, filename):
    job_dir = os.path.join(RESULTS_DIR, job_id)
    if not os.path.isdir(job_dir):
        abort(404)
    return send_from_directory(job_dir, filename)


if __name__ == "__main__":
    os.makedirs(RESULTS_DIR, exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False)
