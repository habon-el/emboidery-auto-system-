"""Out-of-scope input detection (Section 2/9): detect and clearly warn or
reject rather than silently producing a bad file.

These are heuristics, not certainty -- they're tuned to catch the clear
cases (photos, gradients, tiny text) without being so aggressive they
reject legitimate flat 2-4 color logos. Ambiguous cases get a warning
attached to the RegionSet instead of a hard reject, and it's on the
caller (CLI output) to make that visible.
"""
from dataclasses import dataclass

from src.regions.model import DigitizeScopeError

# Mean per-channel abs error between the original raster and its <=4
# color quantization. A flat logo/text image reduces almost losslessly;
# a photo or gradient leaves visible reconstruction error.
QUANTIZATION_WARN_ERROR = 10.0
QUANTIZATION_REJECT_ERROR = 25.0

MIN_FEATURE_HEIGHT_MM = 6.0  # Section 2: text below ~6mm cap height


@dataclass
class ScopeFinding:
    message: str
    reject: bool


def check_color_complexity(mean_quant_error: float) -> ScopeFinding | None:
    if mean_quant_error >= QUANTIZATION_REJECT_ERROR:
        return ScopeFinding(
            f"Reducing this image to 4 flat colors leaves a large color "
            f"error (avg {mean_quant_error:.1f}/255 per channel) -- this "
            f"looks like a photo, gradient, or shaded image, which is out "
            f"of scope for this tool (Section 2). Rejecting rather than "
            f"producing a low-quality stitch file.",
            reject=True,
        )
    if mean_quant_error >= QUANTIZATION_WARN_ERROR:
        return ScopeFinding(
            f"Reducing this image to 4 flat colors leaves a moderate "
            f"color error (avg {mean_quant_error:.1f}/255 per channel). "
            f"Results may not match the source closely -- this works best "
            f"on genuinely flat 2-4 color art.",
            reject=False,
        )
    return None


def check_min_feature_size(region_heights_mm: list[float]
                            ) -> ScopeFinding | None:
    tiny = [h for h in region_heights_mm if 0 < h < MIN_FEATURE_HEIGHT_MM]
    if not tiny:
        return None
    return ScopeFinding(
        f"{len(tiny)} region(s) are under the {MIN_FEATURE_HEIGHT_MM}mm "
        f"minimum cap height (smallest: {min(tiny):.1f}mm). Small text/"
        f"detail below this size does not digitize reliably (Section 2) "
        f"-- rejecting rather than producing an unreadable design.",
        reject=True,
    )


def apply_findings(findings: list[ScopeFinding | None], warnings: list[str],
                    strict: bool = True) -> None:
    """Append warning messages; raise on the first reject finding.

    strict=False (the --force CLI flag / web UI checkbox) downgrades a
    would-be rejection to a loud warning instead of stopping -- an
    explicit, informed override rather than removing the guardrail. The
    physical limitation this check is based on doesn't go away just
    because it isn't rejected anymore: it's still on the person running
    it with --force to judge whether the result is actually acceptable.
    """
    for f in findings:
        if f is None:
            continue
        if f.reject and strict:
            raise DigitizeScopeError(f.message)
        elif f.reject:
            warnings.append(f"[forced past scope check] {f.message}")
        else:
            warnings.append(f.message)
