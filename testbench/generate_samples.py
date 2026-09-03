"""Generate synthetic in-scope (and one deliberately out-of-scope) sample
input files for testbench/inputs/. Run once:

    python -m testbench.generate_samples

All samples are generated here, not sourced from any real logo/brand, so
there's no provenance/IP question -- noted per Section 8.
"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(__file__), "inputs")
DPI = 150.0
PX_PER_MM = DPI / 25.4
FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def mm(v: float) -> int:
    return int(round(v * PX_PER_MM))


def save(img: Image.Image, name: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    img.save(path, dpi=(DPI, DPI))
    print(f"wrote {path}  ({img.width}x{img.height}px @ {DPI:.0f} DPI)")


def make_circle_2color():
    size = mm(40)
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    r = mm(15)
    c = size // 2
    draw.ellipse([c - r, c - r, c + r, c + r], fill=(20, 90, 170))
    save(img, "circle_2color.png")


def make_bar_satin():
    w, h = mm(50), mm(30)
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    # A thin rotated bar -- classic satin-column candidate.
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bar_draw = ImageDraw.Draw(bar)
    bar_draw.rounded_rectangle(
        [mm(5), h // 2 - mm(3), w - mm(5), h // 2 + mm(3)],
        radius=mm(3), fill=(180, 20, 20, 255))
    bar = bar.rotate(12, resample=Image.BICUBIC, center=(w / 2, h / 2))
    img.paste(Image.new("RGB", (w, h), "white"), (0, 0))
    img.paste(bar, (0, 0), bar)
    save(img, "bar_satin.png")


def make_star_3color():
    import math
    size = mm(45)
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2

    def star_points(r_outer, r_inner, n=5, rotation=-90):
        pts = []
        for i in range(n * 2):
            r = r_outer if i % 2 == 0 else r_inner
            angle = math.radians(rotation + i * 360 / (n * 2))
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        return pts

    draw.polygon(star_points(mm(18), mm(7)), fill=(210, 160, 10))
    draw.ellipse([cx - mm(4), cy - mm(4), cx + mm(4), cy + mm(4)],
                 fill=(30, 30, 30))
    save(img, "star_3color.png")


def make_text_sample():
    text = "HI"
    cap_height_mm = 12.0
    font_size = int(cap_height_mm * PX_PER_MM * 1.4)  # rough cap-height fudge
    font = ImageFont.truetype(FONT_PATH, font_size)
    pad = mm(6)
    tmp = Image.new("L", (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(10, 10, 10))
    save(img, "text_sample.png")


def make_text_with_bowls():
    """"Hello World" at ordinary small-text size -- unlike text_sample.png's
    "HI", this hits letters with a hole (e, o, o, o, d), which is exactly
    the shape a real bug misclassified as thin running-stitch line art
    instead of a filled glyph (see test_letter_bowl_with_hole_is_fill_not_running)."""
    text = "Hello World"
    cap_height_mm = 10.0
    font_size = int(cap_height_mm * PX_PER_MM * 1.2)
    font = ImageFont.truetype(FONT_PATH, font_size)
    pad = mm(6)
    tmp = Image.new("L", (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(20, 20, 20))
    save(img, "text_with_bowls.png")


def make_out_of_scope_smalltext():
    """Deliberately below the 6mm minimum cap height -- exercises the
    scope-rejection guardrail (Section 2/9), not a normal success case."""
    text = "tiny"
    cap_height_mm = 3.0
    font_size = int(cap_height_mm * PX_PER_MM * 1.4)
    font = ImageFont.truetype(FONT_PATH, font_size)
    pad = mm(6)
    tmp = Image.new("L", (1, 1))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(10, 10, 10))
    save(img, "out_of_scope_smalltext.png")


def make_needs_upscale_dot():
    """A small flat circle: native height under the 6mm minimum cap
    height, but well over the ~2mm^2 noise floor so it survives
    extraction rather than being dropped as noise. Exercises the
    resize-vs-reject interaction (src/pipeline.py's
    load_scaled_region_set): the *source* image's native size here is
    too small on its own, but requesting a big enough --width-mm should
    scale it past the minimum instead of being rejected on that native
    size before the resize ever gets a chance to fix it -- a real bug
    found from a user's actual too-small upload (a serif "Hello world!"
    whose exclamation-mark dot was a disproportionately tiny native
    detail) that used to reject regardless of any --width-mm given."""
    diameter_mm = 4.0
    pad = mm(4)
    size = mm(diameter_mm) + 2 * pad
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    r = mm(diameter_mm) // 2
    c = size // 2
    draw.ellipse([c - r, c - r, c + r, c + r], fill=(20, 90, 170))
    save(img, "needs_upscale_dot.png")


def make_illustration_badge():
    """Multi-region illustration fixture (Multi-Region Illustration
    Digitization milestone): a layered badge with a true hole (the
    ring cut through to the disc under it), a thin line-art swoosh, a
    texture-zone patch, and 6 source colors -- two near-duplicate pairs
    that should perceptually reduce to fewer selected thread matches."""
    import math

    w, h = mm(60), mm(78)
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    cx, cy = w / 2, mm(30)

    navy = (28, 63, 110)
    navy_dup = (29, 64, 111)    # near-duplicate of navy -- should merge
    gold = (210, 160, 10)
    gold_dup = (212, 162, 12)   # near-duplicate of gold -- should merge
    crimson = (180, 40, 40)
    teal = (20, 130, 120)

    # Outer badge disc.
    r_outer = mm(24)
    draw.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], fill=navy)

    # Ring with a true hole cut through to the disc underneath.
    r_ring_out, r_ring_in = mm(19), mm(13)
    draw.ellipse([cx - r_ring_out, cy - r_ring_out, cx + r_ring_out, cy + r_ring_out], fill=gold)
    draw.ellipse([cx - r_ring_in, cy - r_ring_in, cx + r_ring_in, cy + r_ring_in], fill=navy_dup)

    # Center star, sitting inside the hole.
    def star_points(r_o, r_i, n=5, rotation=-90):
        pts = []
        for i in range(n * 2):
            r = r_o if i % 2 == 0 else r_i
            angle = math.radians(rotation + i * 360 / (n * 2))
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        return pts

    draw.polygon(star_points(mm(9), mm(3.5)), fill=crimson)

    # Thin line-art swoosh, clearly separate from the disc (not touching
    # or fusing with it) so it stays its own thin element rather than
    # welding into one blob with the ring's gold fill.
    swoosh_y = cy + r_outer + mm(8)
    swoosh = []
    for i in range(60):
        t = i / 59
        x = cx - r_outer * 0.9 + t * r_outer * 1.8
        y = swoosh_y + mm(4) * math.sin(t * math.pi * 2.2)
        swoosh.append((x, y))
    draw.line(swoosh, fill=gold_dup, width=max(1, mm(0.8)), joint="curve")

    # Fourth flat color (teal): rounds out the "6 source colors" set.
    # An earlier version of this fixture tried to also make this patch
    # double as a texture zone by adding pixel-level shading -- dropped
    # after tuning showed a real, inherent conflict on a clean synthetic
    # PNG: shading strong enough for src/regions/texture.py's local-
    # variance detector to register also crosses the color-reduction
    # merge threshold, which fragments the patch into slivers the
    # area-noise-floor filter then (correctly) drops. A real photographed
    # or scanned texture has that variance already baked in at a scale a
    # clean vector-drawn PNG doesn't reproduce without also faking
    # quantization noise. Texture-zone detection itself is covered
    # directly by tests/test_texture.py's synthetic arrays instead.
    patch_cx, patch_cy, patch_r = cx, cy - r_outer * 0.82, mm(6)
    draw.ellipse([patch_cx - patch_r, patch_cy - patch_r,
                  patch_cx + patch_r, patch_cy + patch_r], fill=teal)

    save(img, "illustration_badge.png")


def make_logo_svg():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="70mm" height="40mm" viewBox="0 0 700 400">
  <rect x="0" y="0" width="700" height="400" fill="#ffffff"/>
  <circle cx="180" cy="200" r="140" fill="#1c5aaa"/>
  <rect x="380" y="90" width="260" height="220" rx="30" fill="#d2a00a"/>
</svg>
"""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "logo.svg")
    with open(path, "w") as f:
        f.write(svg)
    print(f"wrote {path}")


def main():
    make_circle_2color()
    make_bar_satin()
    make_star_3color()
    make_text_sample()
    make_text_with_bowls()
    make_out_of_scope_smalltext()
    make_needs_upscale_dot()
    make_logo_svg()
    make_illustration_badge()


if __name__ == "__main__":
    main()
