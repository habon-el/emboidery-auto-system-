"""Running stitch: resample a path to evenly-spaced needle points."""
import math

from .model import Point


def resample_path(path_mm: list[Point], stitch_length_mm: float,
                   closed: bool = False) -> list[Point]:
    """Walk path_mm and drop a needle point every stitch_length_mm.

    Always keeps the path's original vertices in as points too (so sharp
    corners aren't rounded off), it just fills the gaps between them.
    """
    if len(path_mm) < 2 or stitch_length_mm <= 0:
        return list(path_mm)

    pts = list(path_mm)
    if closed and pts[0] != pts[-1]:
        pts = pts + [pts[0]]

    out: list[Point] = [pts[0]]
    carry = 0.0  # distance already "used up" from the previous segment
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len == 0:
            continue
        dx, dy = (x1 - x0) / seg_len, (y1 - y0) / seg_len
        dist = stitch_length_mm - carry
        while dist < seg_len:
            out.append((x0 + dx * dist, y0 + dy * dist))
            dist += stitch_length_mm
        carry = seg_len - (dist - stitch_length_mm)
        out.append((x1, y1))
    return out
