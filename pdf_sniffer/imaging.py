# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Pixel-level helpers: red-ink masks, connected components and circle (ring) fitting.

Only numpy is used, so the whole program stays small and portable.
"""
from dataclasses import dataclass

import numpy as np


class TooMuchInk(Exception):
    """Raised when a mask has so many runs that component labelling would be unreasonably slow."""


MAX_RUNS = 400_000


# --------------------------------------------------------------------------- masks
def dilate(mask, n=1):
    """Binary dilation with a (2n+1) x (2n+1) square, done separably."""
    out = mask
    for _ in range(n):
        p = np.pad(out, ((0, 0), (1, 1)))
        out = p[:, :-2] | p[:, 1:-1] | p[:, 2:]
        p = np.pad(out, ((1, 1), (0, 0)))
        out = p[:-2] | p[1:-1] | p[2:]
    return out


def _red_core(rgb, strong_diff, weak_diff):
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    d = r - np.maximum(g, b)
    # Pure reds have g ~ b; oranges / browns have g well above b and are rejected here.
    hue_ok = np.abs(g - b) <= (0.45 * d)
    base = (r >= 100) & hue_ok
    return base & (d >= strong_diff), base & (d >= weak_diff)


def red_mask(rgb, strong_diff=70, weak_diff=35, chunk_rows=800):
    """Boolean mask of 'red ink' pixels in an HxWx3 uint8 array.

    Strongly red pixels are always kept; weakly red pixels (anti-aliased edges,
    JPEG fade) are kept only when they touch a strong one.
    """
    h = rgb.shape[0]
    out = np.zeros(rgb.shape[:2], dtype=bool)
    for y0 in range(0, h, chunk_rows):
        y1 = min(h, y0 + chunk_rows)
        # one extra row either side so the weak-edge dilation is seamless across chunks
        a, b = max(0, y0 - 1), min(h, y1 + 1)
        strong, weak = _red_core(rgb[a:b], strong_diff, weak_diff)
        m = strong | (weak & dilate(strong))
        out[y0:y1] = m[y0 - a:(y1 - a)]
    return out


# --------------------------------------------------------------- connected components
@dataclass
class Component:
    x0: int
    y0: int
    x1: int  # exclusive
    y1: int  # exclusive
    area: int

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0


def label_components(mask):
    """8-connected components of a boolean mask, via run-length union-find.

    Returns a list of Component (bounding box + pixel count).  Fast for the sparse
    masks we deal with because Python only loops over runs, not pixels.
    """
    h, w = mask.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    d = np.diff(padded, axis=1)
    ys, s = np.nonzero(d == 1)
    _, e = np.nonzero(d == -1)
    n = len(ys)
    if n == 0:
        return []
    if n > MAX_RUNS:
        raise TooMuchInk(f"{n} runs")

    parent = list(range(n))

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    s_l, e_l = s.tolist(), e.tolist()
    # row boundaries
    bounds = np.searchsorted(ys, np.arange(h + 1)).tolist()
    for y in range(1, h):
        cur_lo, cur_hi = bounds[y], bounds[y + 1]
        prev_lo, prev_hi = bounds[y - 1], bounds[y]
        if cur_lo == cur_hi or prev_lo == prev_hi:
            continue
        p = prev_lo
        for j in range(cur_lo, cur_hi):
            sj, ej = s_l[j], e_l[j]
            while p < prev_hi and e_l[p] < sj:
                p += 1
            q = p
            while q < prev_hi and s_l[q] <= ej:
                rq, rj = find(q), find(j)
                if rq != rj:
                    parent[rq] = rj
                q += 1

    roots = np.fromiter((find(i) for i in range(n)), dtype=np.int64, count=n)
    uniq, ids = np.unique(roots, return_inverse=True)
    k = len(uniq)
    x0 = np.full(k, w, dtype=np.int64)
    x1 = np.zeros(k, dtype=np.int64)
    y0 = np.full(k, h, dtype=np.int64)
    y1 = np.zeros(k, dtype=np.int64)
    np.minimum.at(x0, ids, s)
    np.maximum.at(x1, ids, e)
    np.minimum.at(y0, ids, ys)
    np.maximum.at(y1, ids, ys + 1)
    area = np.bincount(ids, weights=(e - s), minlength=k).astype(np.int64)
    return [Component(int(a), int(b), int(c), int(d_), int(f))
            for a, b, c, d_, f in zip(x0, y0, x1, y1, area)]


# ------------------------------------------------------------------------ ring fitting
@dataclass
class Ring:
    cx: float
    cy: float
    r_out: float
    r_in: float
    coverage: float


def _cast_rays(mask, cx, cy, r, n_rays):
    h, w = mask.shape
    ang = np.linspace(0.0, 2.0 * np.pi, n_rays, endpoint=False)
    steps = np.arange(r * 1.25, 0.0, -0.5)  # outside -> inside
    xs = np.rint(cx + np.outer(np.cos(ang), steps)).astype(np.int64)
    ys = np.rint(cy + np.outer(np.sin(ang), steps)).astype(np.int64)
    inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    vals = np.zeros(xs.shape, dtype=bool)
    vals[inside] = mask[ys[inside], xs[inside]]
    hit = vals.any(axis=1)
    first = vals.argmax(axis=1)
    idx = np.arange(steps.size)[None, :]
    gaps = (~vals) & (idx > first[:, None])
    end = np.where(gaps.any(axis=1), gaps.argmax(axis=1), steps.size - 1)
    return ang, steps, hit, first, end


def fit_ring(mask, cx, cy, r, n_rays=96, max_thickness=0.30, tol=0.12):
    """Test whether the red ink around (cx, cy) forms a thin, closed circle of radius ~r.

    Returns a Ring (with a least-squares refined centre/radius) or None.
    """
    for _ in range(2):  # second pass uses the refined centre
        ang, steps, hit, first, end = _cast_rays(mask, cx, cy, r, n_rays)
        r_hit = steps[first]
        good = hit & (np.abs(r_hit - r) <= tol * r)
        if good.sum() < 8:
            return None
        px = cx + r_hit[good] * np.cos(ang[good])
        py = cy + r_hit[good] * np.sin(ang[good])
        a = np.column_stack([px, py, np.ones_like(px)])
        sol, *_ = np.linalg.lstsq(a, -(px ** 2 + py ** 2), rcond=None)
        ncx, ncy = -sol[0] / 2.0, -sol[1] / 2.0
        rr2 = ncx ** 2 + ncy ** 2 - sol[2]
        if rr2 <= 0:
            return None
        cx, cy, r = float(ncx), float(ncy), float(np.sqrt(rr2))
    ang, steps, hit, first, end = _cast_rays(mask, cx, cy, r, n_rays)
    r_hit = steps[first]
    good = hit & (np.abs(r_hit - r) <= tol * r)
    coverage = float(good.mean())
    if coverage < 0.5:
        return None
    thickness = (steps[first] - steps[end])[good]
    if np.median(thickness) > max_thickness * r:
        return None  # a filled disc or a very fat blob, not an outlined ring
    r_in = float(np.median(steps[end][good]))
    return Ring(cx, cy, float(np.median(r_hit[good])), r_in, coverage)


def find_rings(mask, min_diameter, max_diameter, min_coverage=0.85):
    """Find ring-shaped (circle outline) red components in a mask.

    The mask is lightly dilated first so a ring broken by thin gaps still forms one component.
    """
    work = dilate(mask, 1)
    rings = []
    for c in label_components(work):
        d = max(c.w, c.h)
        if d < min_diameter or d > max_diameter:
            continue
        if not 0.8 <= c.w / c.h <= 1.25:
            continue
        ring = fit_ring(work, (c.x0 + c.x1 - 1) / 2.0, (c.y0 + c.y1 - 1) / 2.0, d / 2.0)
        if ring and ring.coverage >= min_coverage:
            rings.append(ring)
    # concentric duplicates (double rings, inner outline): keep the biggest
    rings.sort(key=lambda g: -g.r_out)
    kept = []
    for g in rings:
        if all(np.hypot(g.cx - k.cx, g.cy - k.cy) > 0.5 * k.r_out for k in kept):
            kept.append(g)
    return kept
