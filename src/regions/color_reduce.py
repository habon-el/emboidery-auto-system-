"""Reduce a raster image to a small set of flat colors via perceptual
(CIELab) k-means clustering with a Delta-E merge pass.

Clustering in raw RGB (the original M1 approach, capped at 4 colors)
perceptually misbehaves past that ceiling: RGB Euclidean distance
doesn't track how people actually perceive color difference, so it
either merges colors a human would call clearly different, or splits
one color into two purely from anti-aliasing noise. CIELab space is
built specifically so that Euclidean distance in it approximates
perceptual difference (Delta-E) -- clustering there, then merging any
two clusters closer than a Delta-E threshold, raises the practical
color ceiling to 8-12 flat colors while staying accurate to what a
person would actually call "the same color" (Multi-Region Illustration
Digitization milestone, item 3).

Still reports mean_error the same way as before (RGB reconstruction
error against the original raster) since src/regions/scope.py's
photo/gradient detection is tuned against that specific number.

A real raster logo is virtually never perfectly flat at the pixel level
-- anti-aliased edges leave a thin gradient of intermediate shades
between each flat color and its neighbor. Raising raw_k from 4 to 12
gives k-means enough cluster slots that those gradient pixels can end up
as their own small clusters instead of being absorbed into a big
neighboring one (which is what implicitly happened at k=4, almost by
accident). A pairwise Delta-E merge alone doesn't reliably fix this,
because a smooth gradient's *steps* can each individually exceed the
merge threshold even though the gradient as a whole is edge noise, not
a real color. So merging happens in two passes: first, any cluster that
covers only a small fraction of the image's pixels is folded into its
nearest surviving neighbor regardless of Delta-E (the "this is too
small to be a real color, not too different" case -- see
_absorb_small_clusters); only then does a Delta-E pass fold any
remaining large-but-perceptually-duplicate clusters together.
"""
import cv2
import numpy as np

RAW_CLUSTERS = 12               # upper bound on distinct clusters k-means looks for
MERGE_DELTA_E = 6.0             # clusters closer than this (Delta-E) are folded together
SMALL_CLUSTER_FRACTION = 0.004  # clusters covering less of the image than this are
                                 # treated as edge/anti-aliasing noise, not a real color
MIN_COLORS = 1


def _delta_e(lab_a: np.ndarray, lab_b: np.ndarray) -> float:
    return float(np.linalg.norm(lab_a.astype(np.float32) - lab_b.astype(np.float32)))


KMEANS_SEED = 1729
KMEANS_FIT_SAMPLE_CAP = 20_000  # fit centers on at most this many pixels


def _kmeans_lab(samples: np.ndarray, k: int, seed: int = KMEANS_SEED,
                 max_iters: int = 30) -> tuple[np.ndarray, np.ndarray]:
    """A small, fully self-contained, deterministic k-means (k-means++
    init + Lloyd's algorithm) over Lab samples.

    cv2.kmeans looked like the obvious choice here, but its PP-center
    seeding draws from OpenCV's own internal RNG/threaded reduction, and
    in practice that made the *same* input image quantize into a
    different palette from one run to the next -- with raw_k raised to
    12, small differences in exactly where cluster boundaries land
    change which pixels an anti-aliased edge's gradient ends up
    belonging to, which cascades into a visibly different region shape
    and stitch count for a design that hasn't changed at all. A numpy
    implementation seeded once, with no hidden global RNG or
    parallel-reduction ordering to depend on, makes "digitize the same
    file twice" actually produce the same file -- worth the modest
    reimplementation given how much that guarantee matters here.

    Fits centers on a capped, seeded random subsample (k-means quality
    barely changes past a few thousand samples, and this keeps the O(n*k)
    fit step cheap even on a large image), then assigns every pixel in
    the full image to its nearest fitted center.
    """
    rng = np.random.RandomState(seed)
    n = samples.shape[0]

    if n > KMEANS_FIT_SAMPLE_CAP:
        fit_idx = rng.choice(n, size=KMEANS_FIT_SAMPLE_CAP, replace=False)
        fit_samples = samples[fit_idx]
    else:
        fit_samples = samples

    centers = _kmeans_pp_init(fit_samples, k, rng)
    for _ in range(max_iters):
        labels_fit = _nearest_center(fit_samples, centers)
        new_centers = centers.copy()
        for j in range(k):
            members = fit_samples[labels_fit == j]
            if len(members) > 0:
                new_centers[j] = members.mean(axis=0)
        if np.allclose(new_centers, centers, atol=1e-3):
            centers = new_centers
            break
        centers = new_centers

    full_labels = _nearest_center(samples, centers)
    return full_labels, centers.astype(np.float32)


def _kmeans_pp_init(samples: np.ndarray, k: int,
                     rng: np.random.RandomState) -> np.ndarray:
    n = samples.shape[0]
    centers = np.empty((k, samples.shape[1]), dtype=np.float64)
    centers[0] = samples[rng.randint(n)]
    closest_sq = np.full(n, np.inf)
    for i in range(1, k):
        diff = samples - centers[i - 1]
        d2 = np.einsum("ij,ij->i", diff, diff)
        closest_sq = np.minimum(closest_sq, d2)
        total = closest_sq.sum()
        probs = (closest_sq / total) if total > 0 else np.full(n, 1.0 / n)
        centers[i] = samples[rng.choice(n, p=probs)]
    return centers


def _nearest_center(samples: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """O(n*k) time, O(n) memory -- loops over the (small, <=~12) centers
    rather than building an n x k distance matrix, so this stays cheap
    even for a several-megapixel image."""
    n = samples.shape[0]
    best_dist = np.full(n, np.inf)
    labels = np.zeros(n, dtype=np.int32)
    for j, c in enumerate(centers):
        diff = samples - c
        d2 = np.einsum("ij,ij->i", diff, diff)
        better = d2 < best_dist
        best_dist[better] = d2[better]
        labels[better] = j
    return labels


def _absorb_small_clusters(labels: np.ndarray, lab_centers: np.ndarray,
                            total_px: int, fraction: float
                            ) -> tuple[np.ndarray, np.ndarray]:
    """Repeatedly folds the smallest cluster below `fraction` of the
    image's pixels into its nearest (Delta-E) surviving neighbor,
    pixel-count-weighting the neighbor's center as it grows. Unlike a
    pairwise Delta-E merge, this doesn't require the small cluster to be
    perceptually *close* to anything -- only small, which is what a
    sliver of anti-aliasing edge pixels reliably is regardless of how
    much its color happens to have drifted from either true neighbor.
    """
    n = len(lab_centers)
    if n <= 1:
        return labels, lab_centers

    counts = np.bincount(labels, minlength=n).astype(np.float64)
    threshold = max(1.0, total_px * fraction)

    group_of = list(range(n))  # original cluster id -> current live group id
    live_center = {i: lab_centers[i].astype(np.float64) for i in range(n)}
    live_count = {i: counts[i] for i in range(n)}

    while len(live_center) > 1:
        smallest = min(live_center, key=lambda g: live_count[g])
        if live_count[smallest] >= threshold:
            break
        nearest = min((g for g in live_center if g != smallest),
                       key=lambda g: _delta_e(live_center[smallest], live_center[g]))
        c_small, c_near = live_count[smallest], live_count[nearest]
        live_center[nearest] = (
            (live_center[smallest] * c_small + live_center[nearest] * c_near)
            / (c_small + c_near))
        live_count[nearest] = c_small + c_near
        del live_center[smallest], live_count[smallest]
        group_of = [nearest if g == smallest else g for g in group_of]

    remaining = list(live_center.keys())
    new_id = {orig: idx for idx, orig in enumerate(remaining)}
    new_labels = np.array([new_id[group_of[label]] for label in labels])
    new_centers = np.array([live_center[orig] for orig in remaining], dtype=np.float32)
    return new_labels, new_centers


def _merge_close_clusters(labels: np.ndarray, lab_centers: np.ndarray, threshold: float
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Greedily unions clusters within `threshold` Delta-E of each other
    (union-find over pairwise distance), then remaps labels to the merged
    group indices. Returns (new_labels 0..m-1, merged Lab centers)."""
    n = len(lab_centers)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _delta_e(lab_centers[i], lab_centers[j]) < threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    root_to_new = {root: idx for idx, root in enumerate(groups)}
    remap = np.array([root_to_new[find(i)] for i in range(n)])
    new_labels = remap[labels]

    # Merged center = mean Lab of the folded clusters' original centers.
    # Unweighted is fine: these clusters were already within a "call it
    # the same color" Delta-E of each other, so a rigorous pixel-count
    # weighting wouldn't move the result meaningfully.
    new_centers = np.zeros((len(groups), 3), dtype=np.float32)
    for root, members in groups.items():
        new_centers[root_to_new[root]] = lab_centers[members].mean(axis=0)

    return new_labels, new_centers


def quantize(rgb: np.ndarray, raw_k: int = RAW_CLUSTERS,
             merge_delta_e: float = MERGE_DELTA_E,
             small_cluster_fraction: float = SMALL_CLUSTER_FRACTION
             ) -> tuple[np.ndarray, np.ndarray, float, int, int]:
    """Returns (label_map HxW int, palette kx3 uint8 RGB, mean_error,
    raw_cluster_count, merged_cluster_count).

    raw_cluster_count is how many distinct clusters k-means actually
    found before merging; merged_cluster_count is the final color count
    after folding perceptually-identical clusters together. These are
    reported separately -- not collapsed into one number -- so a caller
    can show "12 visual colors detected -> 8 thread colors selected"
    instead of hiding the merge step.
    """
    h, w, _ = rgb.shape
    n_unique = len(np.unique(rgb.reshape(-1, 3), axis=0))
    k = max(min(raw_k, n_unique), MIN_COLORS)

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    samples_lab = lab.reshape(-1, 3).astype(np.float64)

    labels, lab_centers = _kmeans_lab(samples_lab, k)
    raw_cluster_count = k

    absorbed_labels, absorbed_centers = _absorb_small_clusters(
        labels, lab_centers, h * w, small_cluster_fraction)
    merged_labels, merged_lab_centers = _merge_close_clusters(
        absorbed_labels, absorbed_centers, merge_delta_e)
    merged_cluster_count = len(merged_lab_centers)

    lab_palette = np.clip(merged_lab_centers, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    palette = cv2.cvtColor(lab_palette, cv2.COLOR_LAB2RGB).reshape(-1, 3)
    label_map = merged_labels.reshape(h, w)

    reconstructed = palette[label_map].astype(np.float32)
    mean_error = float(np.mean(np.abs(reconstructed - rgb.astype(np.float32))))

    return label_map, palette, mean_error, raw_cluster_count, merged_cluster_count
