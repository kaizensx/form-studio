"""A photo with a reference object to a dimensioned profile: the part's outline as lines and arcs in millimetres.

The photo is taken square on to a flat part lying beside (and in the plane of) something whose size is known.

  1. Foreground: each pixel's distance in colour from the background (the median of the image's border), smoothed
     with a Gaussian (sigma 1 px); the threshold between background and objects by Otsu's method (Otsu 1979).
  2. Edges and contours: the threshold's level line traced by marching squares with the crossing interpolated
     along each pixel edge, so the outline is at sub-pixel positions (where a blurred step edge crosses half its
     height, which is where the edge is). Closed loops only; holes are the loops inside the part.
  3. Scale from the reference:
       card    an ISO/IEC 7810 ID-1 card, 85.60 x 53.98 mm. Its four sides are fitted as lines (total least
               squares on the outline away from the rounded corners), their intersections are the card's corners,
               and the homography of those four points onto the card's rectangle maps every pixel to millimetres
               in the card's plane: perspective in that plane is removed.
       coin    a circle of known diameter (a listed coin, or diameter_mm): scale only. An ellipse there means the
               camera was tilted, which a coin cannot correct; the axis ratio is reported.
       scale   two pixel points a known distance apart (two ruler marks read by the person): scale only.
  4. Lines and arcs: the outline is simplified (Douglas and Peucker 1973) at a tolerance above the pixel noise,
     runs of short segments that fit a circle become arcs (algebraic circle fit, Kasa 1976, checked by the
     geometric residual), the rest are lines fitted by total least squares, and neighbours are joined where they
     intersect. A loop that is one circle becomes a circle.
  5. A form.sketch2d profile (the plain data form/handsketch.py solves): points, lines, arcs and circles, horizontal
     and vertical where a line is within 1.5 degrees of an axis, and the dimensions.

Uncertainty, stated on every dimension (k = 2, about 95 %): an edge is located to u_edge = 0.5 px (assumed: the
blur and the threshold), so a length between two edges carries sqrt(2) u_edge; the scale carries the reference's
own tolerance and the same edge term over the reference's length. u(D)² = (sqrt(2) u_edge / s)² + (D u_s / s)².
Not in the figure, and said so: parallax when the part is thicker than the reference or not in its plane, lens
distortion, and for coin and scale references any tilt of the camera.

Every dimension is "estimated from the photo": a parameter built from it is *assumed*, never measured.

Pillow and numpy only (OpenCV is Apache-2.0 and scikit-image BSD, both usable under this project's licence; neither
is needed for these steps, so no dependency is added).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

VERSION = 1
EVIDENCE = "estimated from the photo"
CARD_MM = (85.60, 53.98)                     # ISO/IEC 7810:2019 ID-1 nominal
CARD_TOL_MM = (0.125, 0.055)                 # ISO/IEC 7810 ID-1: 85.47 to 85.72, 53.92 to 54.03
CARD_SOURCE = "ISO/IEC 7810:2019, ID-1: 85.60 x 53.98 mm (85.47 to 85.72 by 53.92 to 54.03)"
COINS = {                                    # diameter in mm
    "eur_0.01": 16.25, "eur_0.02": 18.75, "eur_0.05": 21.25, "eur_0.10": 19.75, "eur_0.20": 22.25, "eur_0.50": 24.25,
    "eur_1": 23.25, "eur_2": 25.75,
    "usd_0.01": 19.05, "usd_0.05": 21.21, "usd_0.10": 17.91, "usd_0.25": 24.26,
}
COIN_SOURCE = {"eur": "European Central Bank, common sides of euro coins (diameters)",
               "usd": "United States Mint, coin specifications (diameters)"}
COIN_TOL_MM = 0.1                            # assumed: wear and minting tolerance, no published figure used
U_EDGE_PX = 0.5                              # assumed: how well one edge is located
MAX_SIDE = 1800
HV_DEG = 1.5


class PhotoError(ValueError):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


# ── image to loops ───────────────────────────────────────────────────────────────────────────────────────────────

def load(path) -> tuple[np.ndarray, float]:
    """(the image as float RGB in 0..1, the factor it was shrunk by)."""
    from PIL import Image, ImageOps
    p = Path(str(path)).expanduser()
    if not p.is_file():
        raise PhotoError(f"No photo at {p}.")
    try:
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    except Exception as e:                                  # noqa: BLE001 - Pillow raises many things for a bad file
        raise PhotoError(f"{p.name} is not a picture Form Studio can read ({type(e).__name__}).") from None
    f = 1.0
    if max(im.size) > MAX_SIDE:
        f = MAX_SIDE / max(im.size)
        im = im.resize((max(1, round(im.size[0] * f)), max(1, round(im.size[1] * f))), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64) / 255.0, f


def _blur(a: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    r = max(1, int(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    p = np.pad(a, ((r, r), (0, 0)), mode="edge")
    a = sum(k[i] * p[i:i + a.shape[0]] for i in range(2 * r + 1))
    p = np.pad(a, ((0, 0), (r, r)), mode="edge")
    return sum(k[i] * p[:, i:i + a.shape[1]] for i in range(2 * r + 1))


def foreground(img: np.ndarray) -> tuple[np.ndarray, float]:
    """(each pixel's distance from the background colour, smoothed; Otsu's threshold on it)."""
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    bg = np.median(border, axis=0)
    d = _blur(np.sqrt(((img - bg) ** 2).sum(axis=2)))
    hist, edges = np.histogram(d, bins=256)
    mids = 0.5 * (edges[:-1] + edges[1:])
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids)
    mu0 = m0 / np.maximum(w0, 1)
    mu1 = (m0[-1] - m0) / np.maximum(w1, 1)
    k = int(np.argmax(w0 * w1 * (mu0 - mu1) ** 2))
    t = float(0.5 * (mu0[k] + mu1[k]))                      # midway between the two classes: half the step's height
    if float(mu1[k] - mu0[k]) < 0.04:
        raise PhotoError("The photo shows nothing that stands out from its background.",
                         "Photograph the part on a plain surface of a different colour, evenly lit.")
    return d, t


def contours(d: np.ndarray, t: float) -> list[np.ndarray]:
    """Closed level lines of d at t as (n, 2) arrays of (x, y) in pixels, y down, sub-pixel. The image is padded with
    background, so an object cut by the frame still closes (along the frame)."""
    g = np.pad(d, 1, mode="constant", constant_values=min(float(d.min()), t - 1.0)) - t
    g = np.where(g == 0.0, 1e-12, g)
    H, W = g.shape
    ins = g > 0
    code = (ins[:-1, :-1] * 1 + ins[:-1, 1:] * 2 + ins[1:, 1:] * 4 + ins[1:, :-1] * 8)
    ys, xs = np.nonzero((code > 0) & (code < 15))
    # edge ids: horizontal edge (y, x)-(y, x+1) -> 2 * (y * W + x); vertical edge (y, x)-(y+1, x) -> 2 * (y * W + x) + 1
    def eid(y, x, vertical):
        return 2 * (y * W + x) + (1 if vertical else 0)
    # per case: pairs of cell edges (0 top, 1 right, 2 bottom, 3 left) joined, the inside on the left of a -> b
    table = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: [(3, 0), (1, 2)], 6: [(0, 2)], 7: [(3, 2)],
             8: [(2, 3)], 9: [(2, 0)], 10: [(0, 1), (2, 3)], 11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)]}
    nxt: dict = {}
    for y, x, c in zip(ys.tolist(), xs.tolist(), code[ys, xs].tolist()):
        e = (eid(y, x, False), eid(y, x + 1, True), eid(y + 1, x, False), eid(y, x, True))
        for a, b in table[c]:
            nxt[e[a]] = e[b]

    def point(e):
        v, k = e % 2, e // 2
        y, x = divmod(k, W)
        if v:
            a, b = g[y, x], g[y + 1, x]
            return (x - 1.0, y - 1.0 + a / (a - b))
        a, b = g[y, x], g[y, x + 1]
        return (x - 1.0 + a / (a - b), y - 1.0)

    loops = []
    while nxt:
        start, e = next(iter(nxt)), None
        e = start
        pts = []
        while True:
            pts.append(point(e))
            n = nxt.pop(e, None)
            if n is None or n == start:
                break
            e = n
        if len(pts) >= 8 and n == start:
            loops.append(np.array(pts))
    return loops


def _retrace(d: np.ndarray, P: np.ndarray, t: float, pad: int = 6):
    """One object's outline and holes traced again at half the object's own height: (outline, positive area;
    [holes, negative area]) in the image's pixels."""
    x0, y0 = np.maximum(np.floor(P.min(axis=0)).astype(int) - pad, 0)
    x1, y1 = np.ceil(P.max(axis=0)).astype(int) + pad + 1
    crop = d[y0:y1, x0:x1]
    top = crop[crop > t]
    if not len(top):
        return P, []
    level = 0.5 * float(np.median(top))
    loops = [L + np.array([x0, y0], float) for L in contours(crop, level)]
    if not loops:
        return P, []
    big = max(loops, key=lambda L: abs(_area(L)))
    sign = 1.0 if _area(big) > 0 else -1.0
    c = P.mean(axis=0)
    if not (_inside(tuple(c), big) or abs(abs(_area(big)) / abs(_area(P)) - 1.0) < 0.2):
        return P, []
    holes = [L[::int(sign)] for L in loops if L is not big and _area(L) * sign < 0 and _inside(tuple(L.mean(axis=0)), big)]
    return big[::int(sign)], holes


def _area(P: np.ndarray) -> float:
    x, y = P[:, 0], P[:, 1]
    return float(0.5 * (x * np.roll(y, -1) - np.roll(x, -1) * y).sum())


def _perimeter(P: np.ndarray) -> float:
    return float(np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1).sum())


def _inside(pt, P: np.ndarray) -> bool:
    x, y = pt
    x0, y0 = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    cross = ((y0 > y) != (y1 > y)) & (x < (x1 - x0) * (y - y0) / np.where(y1 != y0, y1 - y0, 1e-30) + x0)
    return bool(cross.sum() % 2)


# ── fitting ──────────────────────────────────────────────────────────────────────────────────────────────────────

def fit_line(P: np.ndarray):
    """Total least squares: (a point on the line, its unit direction, the largest distance of a point from it)."""
    c = P.mean(axis=0)
    _u, _s, vt = np.linalg.svd(P - c, full_matrices=False)
    d = vt[0]
    n = np.array([-d[1], d[0]])
    return c, d, float(np.abs((P - c) @ n).max())


def fit_circle(P: np.ndarray):
    """(centre, radius, the largest radial residual): the algebraic fit of Kasa (1976), then two Gauss-Newton steps
    on the geometric distance."""
    x, y = P[:, 0], P[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones(len(P))])
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0], sol[1]
    r = math.sqrt(max(sol[2] + cx * cx + cy * cy, 1e-18))
    for _ in range(2):
        dx, dy = x - cx, y - cy
        rho = np.maximum(np.hypot(dx, dy), 1e-12)
        J = np.column_stack([-dx / rho, -dy / rho, -np.ones(len(P))])
        step, *_ = np.linalg.lstsq(J, -(rho - r), rcond=None)
        cx, cy, r = cx + step[0], cy + step[1], r + step[2]
    res = np.abs(np.hypot(x - cx, y - cy) - r)
    return np.array([cx, cy]), float(r), float(res.max())


def simplify(P: np.ndarray, tol: float) -> list[int]:
    """Douglas-Peucker on a closed loop: the indices kept, in order. Starts from the two points farthest apart."""
    n = len(P)
    i0 = int(np.argmax(np.linalg.norm(P - P.mean(axis=0), axis=1)))
    i1 = int(np.argmax(np.linalg.norm(P - P[i0], axis=1)))
    keep = {i0, i1}

    def run(a, b):                                           # indices a -> b going forward (cyclic)
        stack = [(a, b)]
        while stack:
            a, b = stack.pop()
            m = (b - a) % n
            if m < 2:
                continue
            idx = (a + np.arange(1, m)) % n
            A, B = P[a], P[b % n]
            ab = B - A
            L = np.linalg.norm(ab)
            Q = P[idx] - A
            dist = np.abs(Q[:, 0] * ab[1] - Q[:, 1] * ab[0]) / L if L > 1e-12 else np.linalg.norm(Q, axis=1)
            k = int(np.argmax(dist))
            if dist[k] > tol:
                j = int(idx[k])
                keep.add(j)
                stack.append((a, j))
                stack.append((j, b))
    a, b = sorted((i0, i1))
    run(a, b)
    run(b, a + n)
    return sorted(keep)


def _span(P, i, j):
    n = len(P)
    return P[(i + np.arange((j - i) % n + 1)) % n] if j != i else P


def fit_loop(P: np.ndarray, tol: float) -> list[dict]:
    """A closed outline (points in mm, counter-clockwise) as lines and arcs within tol: [{"k": "line", "a", "b"} |
    {"k": "arc", "c", "r", "a", "b", "ccw"} | {"k": "circle", "c", "r"}], end to start."""
    c, r, res = fit_circle(P)
    if res <= tol:
        return [{"k": "circle", "c": c.tolist(), "r": r, "residual": res}]
    idx = simplify(P, tol)
    m = len(idx)
    size = float(np.ptp(P, axis=0).max())
    prims, i, used = [], 0, 0
    while used < m:
        best = None
        for k in range(2, m - used + 1):
            Q = _span(P, idx[i % m], idx[(i + k) % m]) if k < m else P
            if len(Q) < 6:
                continue
            cc, rr, rs = fit_circle(Q)
            if rs > tol or rr > 20 * size:
                break
            _c0, _d0, line_res = fit_line(Q)
            a0 = math.atan2(Q[0][1] - cc[1], Q[0][0] - cc[0])
            sweep = float(np.abs(np.unwrap(np.arctan2(Q[:, 1] - cc[1], Q[:, 0] - cc[0]))[-1] - a0))
            if line_res > tol and sweep >= math.radians(20):
                best = (k, cc, rr, rs, sweep)
        if best:
            k, cc, rr, rs, sweep = best
            Q = _span(P, idx[i % m], idx[(i + k) % m])
            mid = Q[len(Q) // 2]
            cr = (Q[0][0] - cc[0]) * (mid[1] - cc[1]) - (Q[0][1] - cc[1]) * (mid[0] - cc[0])
            prims.append({"k": "arc", "c": cc, "r": rr, "ccw": bool(cr > 0), "residual": rs, "sweep": sweep,
                          "i": idx[i % m], "j": idx[(i + k) % m]})
            i += k
            used += k
        else:
            Q = _span(P, idx[i % m], idx[(i + 1) % m])
            c0, d0, rs = fit_line(Q)
            if d0 @ (Q[-1] - Q[0]) < 0:
                d0 = -d0
            prims.append({"k": "line", "p": c0, "d": d0, "residual": rs, "i": idx[i % m], "j": idx[(i + 1) % m]})
            i += 1
            used += 1
    # two lines in a row that are one line within the tolerance become one (a stub left where an arc ended, or
    # the vertex the simplification started from when that fell on a side)
    merged = True
    while merged and len(prims) > 2:
        merged = False
        for k in range(len(prims)):
            a, b = prims[k], prims[(k + 1) % len(prims)]
            if a["k"] != "line" or b["k"] != "line":
                continue
            Q = _span(P, a["i"], b["j"])
            c0, d0, rs = fit_line(Q)
            if rs <= tol:
                if d0 @ (Q[-1] - Q[0]) < 0:
                    d0 = -d0
                prims[k] = {"k": "line", "p": c0, "d": d0, "residual": rs, "i": a["i"], "j": b["j"]}
                del prims[(k + 1) % len(prims)]
                merged = True
                break
    # a line shorter than four tolerances between two lines that meet at an angle is the blur's rounding of their
    # corner, not a chamfer that can be told from the photo: it goes, and its neighbours meet at the corner
    k = 0
    while k < len(prims) and len(prims) > 3:
        q, a, b = prims[k], prims[k - 1], prims[(k + 1) % len(prims)]
        if (q["k"] == "line" and a["k"] == "line" and b["k"] == "line" and np.linalg.norm(P[q["j"]] - P[q["i"]]) < 4.0 * tol
                and abs(a["d"][0] * b["d"][1] - a["d"][1] * b["d"][0]) > math.sin(math.radians(20))):
            a["j"] = b["i"] = q["j"]
            del prims[k]
            continue
        k += 1
    # join neighbours: the corner between two primitives
    n = len(prims)
    corners, tangent = [], []
    for k in range(n):
        a, b = prims[k], prims[(k + 1) % n]
        v = P[a["j"]]
        tangent.append(False)
        ln, ar = (a, b) if a["k"] == "line" else (b, a)
        if ln["k"] == "line" and ar["k"] == "arc":
            foot = ln["p"] + ((ar["c"] - ln["p"]) @ ln["d"]) * ln["d"]
            if abs(np.linalg.norm(ar["c"] - foot) - ar["r"]) <= 2.0 * tol and np.linalg.norm(foot - v) < 0.6 * ar["r"] + 4 * tol:
                # the line touches the arc: they meet at the foot of the centre on the line (where a chord and its
                # arc part company cannot be read off the outline to better than sqrt(2 r tol))
                corners.append(foot)
                tangent[-1] = True
                continue
        if a["k"] == "line" and b["k"] == "line":
            den = a["d"][0] * b["d"][1] - a["d"][1] * b["d"][0]
            if abs(den) > math.sin(math.radians(3)):
                w = b["p"] - a["p"]
                t = (w[0] * b["d"][1] - w[1] * b["d"][0]) / den
                x = a["p"] + t * a["d"]
                if np.linalg.norm(x - v) < 8 * tol + 0.02 * size:
                    v = x
        else:
            for _ in range(3):                               # onto both: alternate projections
                for q in (a, b):
                    if q["k"] == "line":
                        v = q["p"] + ((v - q["p"]) @ q["d"]) * q["d"]
                    else:
                        w = v - q["c"]
                        v = q["c"] + w / max(np.linalg.norm(w), 1e-12) * q["r"]
        corners.append(v)
    out = []
    for k in range(n):
        a, b = corners[(k - 1) % n], corners[k]
        q = prims[k]
        if q["k"] == "line":
            out.append({"k": "line", "a": a.tolist(), "b": b.tolist(), "residual": q["residual"]})
        else:
            sweep = abs(math.atan2(*(b - q["c"])[::-1]) - math.atan2(*(a - q["c"])[::-1])) % (2 * math.pi)
            if abs(sweep - q["sweep"]) > math.pi / 2:
                sweep = 2 * math.pi - sweep
            out.append({"k": "arc", "c": q["c"].tolist(), "r": q["r"], "a": a.tolist(), "b": b.tolist(), "ccw": q["ccw"],
                        "residual": q["residual"], "sweep_deg": math.degrees(sweep), "seen_deg": math.degrees(q["sweep"])})
        out[-1]["tangent_end"] = bool(tangent[k])             # touches the next primitive
        out[-1]["tangent_start"] = bool(tangent[(k - 1) % n])
    return out


# ── the reference ────────────────────────────────────────────────────────────────────────────────────────────────

def _hull(P: np.ndarray) -> np.ndarray:
    pts = np.unique(np.round(P, 6), axis=0)
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h[:-1]
    return np.array(half(pts) + half(pts[::-1]))


def min_rect(P: np.ndarray):
    """The smallest rectangle round the points: (centre, long direction, long side, short side)."""
    Hh = _hull(P)
    best = None
    for k in range(len(Hh)):
        e = Hh[(k + 1) % len(Hh)] - Hh[k]
        L = np.linalg.norm(e)
        if L < 1e-9:
            continue
        u = e / L
        v = np.array([-u[1], u[0]])
        a, b = Hh @ u, Hh @ v
        w, h = a.max() - a.min(), b.max() - b.min()
        if best is None or w * h < best[0]:
            cen = u * (a.max() + a.min()) / 2 + v * (b.max() + b.min()) / 2
            best = (w * h, cen, u if w >= h else v, max(w, h), min(w, h))
    return best[1], best[2], best[3], best[4]


def card_corners(P: np.ndarray):
    """The four corners of a card's outline (pixels), where its fitted sides meet, in order round the card starting
    with a long side: (corners (4, 2), the largest distance of a side's points from its line)."""
    cen, u, L, S = min_rect(P)
    v = np.array([-u[1], u[0]])
    a, b = (P - cen) @ u, (P - cen) @ v
    sides, worst = [], 0.0
    for coord, other, half, span in ((b, a, -S / 2, L), (a, b, L / 2, S), (b, a, S / 2, L), (a, b, -L / 2, S)):
        sel = (np.abs(coord - half) < 0.04 * S + 1.5) & (np.abs(other) < 0.30 * span)
        if sel.sum() < 6:
            raise PhotoError("The reference does not look like a card: a side could not be found.",
                             "Lay the whole card flat in view, or give another reference.")
        c0, d0, res = fit_line(P[sel])
        worst = max(worst, res)
        sides.append((c0, d0))
    out = []
    for k in range(4):
        (p0, d0), (p1, d1) = sides[k], sides[(k + 1) % 4]
        den = d0[0] * d1[1] - d0[1] * d1[0]
        w = p1 - p0
        t = (w[0] * d1[1] - w[1] * d1[0]) / den
        out.append(p0 + t * d0)
    # corners between side k and k+1: (bottom, right), (right, top), (top, left), (left, bottom)
    return np.array([out[3], out[0], out[1], out[2]]), worst


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """The 3 x 3 projective map of four points onto four points (direct linear transform)."""
    A = []
    for (x, y), (X, Y) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y, -X])
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y, -Y])
    _u, _s, vt = np.linalg.svd(np.array(A, float))
    Hm = vt[-1].reshape(3, 3)
    return Hm / Hm[2, 2]


def apply_h(Hm: np.ndarray, P: np.ndarray) -> np.ndarray:
    q = np.column_stack([P, np.ones(len(P))]) @ Hm.T
    return q[:, :2] / q[:, 2:3]


def _shape_scores(P: np.ndarray) -> dict:
    A, per = abs(_area(P)), _perimeter(P)
    _cen, _u, L, S = min_rect(P)
    return {"area": A, "circularity": 4 * math.pi * A / (per * per), "rectangularity": A / (L * S), "aspect": L / S,
            "long": L, "short": S}


def _reference(loops: list, ref: dict, shrink: float):
    """(index of the reference's loop or None, a function pixel points -> mm, scale record)."""
    kind = str(ref.get("kind") or "card").lower()
    if kind in ("scale", "ruler", "px_per_mm"):
        if ref.get("px_per_mm"):
            s = float(ref["px_per_mm"]) * shrink
            L_px, L_mm, u_ref = None, None, float(ref.get("tolerance_mm", 0.0))
            rel = float(ref.get("relative_uncertainty", 0.0))
        else:
            try:
                (x0, y0), (x1, y1) = ref["points"]
                L_mm = float(ref["length_mm"])
            except (KeyError, TypeError, ValueError):
                raise PhotoError('A scale reference is {"kind": "scale", "points": [[x, y], [x, y]], "length_mm": L}: '
                                 'two points in the photo (pixels) a known distance apart.',
                                 "For a ruler, give the pixel positions of two of its marks and the millimetres between them.") from None
            L_px = math.hypot(x1 - x0, y1 - y0) * shrink
            if L_px < 10 or L_mm <= 0:
                raise PhotoError("The two scale points are too close together.", "Use marks at least 10 pixels apart.")
            s = L_px / L_mm
            u_ref = float(ref.get("tolerance_mm", 0.25))
            rel = math.hypot(u_ref / L_mm, math.sqrt(2) * float(ref.get("point_px", 1.0)) * shrink / L_px)
        rec = {"kind": "scale", "px_per_mm": s / shrink, "relative_uncertainty": rel,
               "reference_tolerance_mm": u_ref, "perspective_corrected": False,
               "note": "two points a known distance apart: scale only; the points are taken as read to 1 px and the "
                       "length to its tolerance (0.25 mm assumed for ruler marks unless given)"}
        return None, (lambda P: P / s), rec
    scored = [(_shape_scores(P), i) for i, P in enumerate(loops) if _area(P) > 0]
    at = ref.get("at")
    if at is not None:
        at = (float(at[0]) * shrink, float(at[1]) * shrink)
        scored = [(sc, i) for sc, i in scored if _inside(at, loops[i])]
        if not scored:
            raise PhotoError("No object lies under the reference's point.", "Give a pixel inside the reference object.")
    if kind == "card":
        want = CARD_MM[0] / CARD_MM[1]
        cands = [(abs(sc["aspect"] / want - 1), i, sc) for sc, i in scored if sc["rectangularity"] > 0.95]
        cands = [c for c in cands if c[0] < 0.08] if at is None else cands
        if not cands:
            raise PhotoError("No bank card was found in the photo (a rounded rectangle of 85.60 x 53.98 mm).",
                             "Lay the card flat beside the part, whole and unobscured, on a plain background; or give "
                             "reference={\"kind\": \"card\", \"at\": [x, y]} with a pixel on the card.")
        _d, i, sc = min(cands)
        corners, side_res = card_corners(loops[i])
        dst = np.array([[0, 0], [CARD_MM[0], 0], [CARD_MM[0], CARD_MM[1]], [0, CARD_MM[1]]], float)
        if (corners[1] - corners[0]) @ (corners[1] - corners[0]) < (corners[2] - corners[1]) @ (corners[2] - corners[1]):
            corners = np.roll(corners, -1, axis=0)
        Hm = homography(corners, dst)
        sides = [float(np.linalg.norm(corners[(k + 1) % 4] - corners[k])) for k in range(4)]
        s_long, s_short = (sides[0] + sides[2]) / 2 / CARD_MM[0], (sides[1] + sides[3]) / 2 / CARD_MM[1]
        s = math.sqrt(s_long * s_short)
        # the scale's relative uncertainty: the card's tolerance and the edge term, on its short side (the worse one)
        rel = max(math.hypot(CARD_TOL_MM[k] / CARD_MM[k], math.sqrt(2) * U_EDGE_PX / (CARD_MM[k] * s)) for k in (0, 1))
        rec = {"kind": "card", "px_per_mm": s / shrink, "relative_uncertainty": rel, "source": CARD_SOURCE,
               "reference_tolerance_mm": list(CARD_TOL_MM), "perspective_corrected": True,
               "anisotropy": s_long / s_short - 1.0, "opposite_sides_ratio": [sides[0] / sides[2], sides[1] / sides[3]],
               "side_fit_px": side_res, "aspect_found": sc["aspect"], "aspect_expected": want,
               "note": "the card's four corners give a homography: perspective in the card's plane is removed"}
        return i, (lambda P: apply_h(Hm, P)), rec
    if kind == "coin":
        coin = ref.get("coin")
        if ref.get("diameter_mm"):
            dia, src, tol = float(ref["diameter_mm"]), "given", float(ref.get("tolerance_mm", COIN_TOL_MM))
        elif coin in COINS:
            dia, src, tol = COINS[coin], COIN_SOURCE[coin.split("_")[0]], float(ref.get("tolerance_mm", COIN_TOL_MM))
        else:
            raise PhotoError("Which coin? Give coin= or diameter_mm=.", "Coins: " + ", ".join(sorted(COINS)) + ".")
        cands = [(-sc["circularity"], i, sc) for sc, i in scored if sc["circularity"] > 0.97 and sc["aspect"] < 1.15]
        if not cands:
            raise PhotoError("No coin was found in the photo (a round object).",
                             "Lay the coin flat beside the part on a plain background, or give reference.at = [x, y].")
        if at is None and len(cands) > 1:                      # several round things: the one nearest the coin's size is not knowable; take the roundest
            cands.sort()
        _c, i, sc = cands[0]
        _cen, _u, L, S = min_rect(loops[i])
        d_px = math.sqrt(4 * sc["area"] / math.pi)
        s = d_px / dia
        rel = math.hypot(tol / dia, math.sqrt(2) * U_EDGE_PX / d_px)
        rec = {"kind": "coin", "coin": coin, "diameter_mm": dia, "source": src, "px_per_mm": s / shrink,
               "relative_uncertainty": rel, "reference_tolerance_mm": tol, "tolerance_assumed": "tolerance_mm" not in ref,
               "perspective_corrected": False, "axis_ratio": L / S,
               "note": "scale only: a coin cannot correct a tilted camera"
                       + (f"; the coin reads as an ellipse ({L / S:.3f}:1), so the camera was tilted and lengths along "
                          f"the short axis read up to {(L / S - 1) * 100:.1f} % short" if L / S > 1.01 else "")}
        return i, (lambda P: P / s), rec
    raise PhotoError(f"Unknown reference “{kind}”.", "card, coin or scale.")


# ── the profile ──────────────────────────────────────────────────────────────────────────────────────────────────

def _to_sketch(loops_prims: list) -> dict:
    """Lines, arcs and circles of every loop as form/handsketch.py data, horizontal and vertical where they are."""
    pts, ents, cons = [], [], []

    def pid(p):
        pts.append([round(float(p[0]), 4), round(float(p[1]), 4)])
        return len(pts) - 1
    for prims in loops_prims:
        if prims[0]["k"] == "circle":
            ents.append({"k": "circle", "p": [pid(prims[0]["c"])], "r": round(prims[0]["r"], 4)})
            continue
        n = len(prims)
        corner = [pid(q["b"]) for q in prims]                 # corner k: end of primitive k, start of k + 1
        first = len(ents)
        for k, q in enumerate(prims):
            if q.get("tangent_end") and n > 1:
                cons.append({"k": "tangent", "e": [first + k, first + (k + 1) % n]})
            a, b = corner[(k - 1) % n], corner[k]
            if q["k"] == "line":
                ents.append({"k": "line", "p": [a, b]})
                ang = math.degrees(math.atan2(q["b"][1] - q["a"][1], q["b"][0] - q["a"][0])) % 180.0
                if min(ang, 180 - ang) <= HV_DEG:
                    cons.append({"k": "horizontal", "e": [len(ents) - 1]})
                elif abs(ang - 90) <= HV_DEG:
                    cons.append({"k": "vertical", "e": [len(ents) - 1]})
            else:
                c = pid(q["c"])
                ents.append({"k": "arc", "p": [c, a, b] if q["ccw"] else [c, b, a]})
    return {"plane": {"datum": "XY", "offset": 0}, "points": pts, "fixed": [0] if pts else [], "entities": ents,
            "constraints": cons}


def _dims(loops_prims: list, s_rel: float, px_mm: float) -> list:
    """Every length, radius and diameter with its expanded uncertainty (k = 2)."""
    u_edge = math.sqrt(2) * U_EDGE_PX * px_mm

    def U(d):
        return 2.0 * math.hypot(u_edge, d * s_rel)
    out, n = [], {"L": 0, "R": 0, "D": 0}
    for li, prims in enumerate(loops_prims):
        role = "outline" if li == 0 else f"hole {li}"
        for q in prims:
            if q["k"] == "line":
                n["L"] += 1
                d = math.dist(q["a"], q["b"])
                out.append({"id": f"L{n['L']}", "kind": "length", "of": role, "value_mm": round(d, 3)})
                k = prims.index(q)
                ends = [prims[(k - 1) % len(prims)]] * q.get("tangent_start", False) + [prims[(k + 1) % len(prims)]] * q.get("tangent_end", False)
                if ends:                                        # an end at a tangent arc is as good as that arc's centre
                    extra = [U_EDGE_PX * px_mm / max(1.0 - math.cos(math.radians(a["seen_deg"]) / 2.0), 1e-3) for a in ends]
                    out[-1]["uncertainty_mm"] = round(2.0 * math.sqrt(u_edge ** 2 + (d * s_rel) ** 2 + sum(x * x for x in extra)), 3)
                    out[-1]["note"] = "ends where it touches an arc: the end is placed by the arc's centre"
            elif q["k"] == "arc":
                n["R"] += 1
                d = q["r"]
                out.append({"id": f"R{n['R']}", "kind": "radius", "of": role, "value_mm": round(d, 3),
                            "sweep_deg": round(q["sweep_deg"], 1)})
                # a short arc fixes its radius poorly: the sagitta's edge error grows as 1 / (1 - cos(sweep / 2))
                amp = 1.0 / max(1.0 - math.cos(math.radians(q["seen_deg"]) / 2.0), 1e-3)
                out[-1]["uncertainty_mm"] = round(2.0 * math.hypot(U_EDGE_PX * px_mm * amp, d * s_rel), 3)
            else:
                n["D"] += 1
                d = 2 * q["r"]
                out.append({"id": f"D{n['D']}", "kind": "diameter", "of": role, "value_mm": round(d, 3)})
            out[-1].setdefault("uncertainty_mm", round(U(d), 3))
            out[-1].update(evidence=EVIDENCE, how_known="assumed", fit_residual_mm=round(float(q.get("residual", 0.0)), 3))
    return out


def _dimension(sketch: dict, loops_prims: list, dims: list) -> dict:
    """Add the dimensions that drive the sketch: each radius and diameter, each hole's position from the origin
    corner, and each line's length, in that order, keeping a dimension only when the sketch still solves and it
    takes a degree of freedom away (a length the others already fix is left out, not doubled)."""
    from . import handsketch
    base = handsketch.solve(sketch)
    if not base.get("ok"):
        return sketch
    dof = base["dof"]
    by_ent, e = [], 0
    ids = iter([d for d in dims if d["kind"] in ("length", "radius", "diameter")])
    for li, prims in enumerate(loops_prims):
        for q in prims:
            d = next(ids)
            by_ent.append((e, q, d, li))
            e += 1
    cand = []
    for e, q, d, li in by_ent:
        if q["k"] == "arc":
            cand.append({"k": "radius", "e": [e], "value": d["value_mm"], "name": d["id"], "label": f"Radius {d['id']}"})
    for e, q, d, li in by_ent:
        if q["k"] == "circle":
            c = sketch["entities"][e]["p"][0]
            cand.append({"k": "diameter", "e": [e], "value": d["value_mm"], "name": d["id"], "label": f"Diameter {d['id']}"})
            x, y = sketch["points"][c]
            x0, y0 = sketch["points"][0]
            if c != 0:
                cand.append({"k": "hdist", "p": [0, c], "value": round(x - x0, 3), "name": f"{d['id']}_x", "label": f"{d['id']} across"})
                cand.append({"k": "vdist", "p": [0, c], "value": round(y - y0, 3), "name": f"{d['id']}_y", "label": f"{d['id']} up"})
    for e, q, d, li in sorted(by_ent, key=lambda r: -r[2]["value_mm"]):
        if q["k"] == "line":
            cand.append({"k": "length", "e": [e], "value": d["value_mm"], "name": d["id"], "label": f"Length {d['id']}"})
    for c in cand:
        if dof <= 0:
            break
        trial = {**sketch, "constraints": sketch["constraints"] + [c]}
        r = handsketch.solve(trial)
        if r.get("ok") and r.get("closed") and r["dof"] < dof:
            sketch, dof = trial, r["dof"]
            for d in dims:
                if d["id"] == c["name"]:
                    d["drives_sketch"] = True
    return sketch


def trace(path, reference: dict | None = None, part_at=None, tolerance_mm: float | None = None,
          min_hole_mm: float = 1.0) -> dict:
    """The part in a photo as a dimensioned profile in millimetres. reference: {"kind": "card"} (default),
    {"kind": "coin", "coin": "eur_1" | "diameter_mm": d}, {"kind": "scale", "points": [[x, y], [x, y]], "length_mm": L};
    with "at": [x, y] (pixels) when the reference must be pointed at. part_at: a pixel on the part (default: the
    largest object that is not the reference). tolerance_mm: how closely lines and arcs follow the outline (default:
    1.5 pixels, at least 0.1 mm)."""
    img, shrink = load(path)
    d, t = foreground(img)
    loops = contours(d, t)
    if not loops:
        raise PhotoError("No object with a closed outline was found.", "Use a plain background that contrasts with the part.")
    big = max(loops, key=lambda P: abs(_area(P)))
    sign = 1.0 if _area(big) > 0 else -1.0                    # the largest loop is an object's outside
    outer = [P[::int(sign)] for P in loops if _area(P) * sign > 150]
    # each object again at half its own height above the background: one threshold for the whole photo sits at a
    # different fraction of a dark part's edge and a pale card's edge, which shifts each outline by a part of a pixel
    objects = [_retrace(d, P, t) for P in outer]
    outer = [o[0] for o in objects]
    ref = dict(reference or {"kind": "card"})
    ri, to_mm, scale = _reference(outer, ref, shrink)
    cands = [(abs(_area(P)), i) for i, P in enumerate(outer) if i != ri]
    if part_at is not None:
        pa = (float(part_at[0]) * shrink, float(part_at[1]) * shrink)
        cands = [(a, i) for a, i in cands if _inside(pa, outer[i])]
    if not cands:
        raise PhotoError("No part was found beside the reference.",
                         "The part must stand out from the background and not touch the reference; or give part_at=[x, y].")
    _a, pi_ = max(cands)
    part_px, holes = objects[pi_]
    px_mm = 1.0 / (scale["px_per_mm"] * shrink)
    tol = float(tolerance_mm) if tolerance_mm else max(1.5 * px_mm, 0.1)
    if tol < 0.75 * px_mm:
        raise PhotoError(f"A tolerance of {tol:g} mm is under one pixel ({px_mm:.3f} mm): the outline is not known that well.",
                         f"Use at least {px_mm:.2f} mm, or a closer or sharper photo.")

    c0 = part_px.mean(axis=0)
    tri = to_mm(np.array([c0, c0 + [1.0, 0.0], c0 + [0.0, -1.0]]))     # right and up on the screen
    e1, e2 = tri[1] - tri[0], tri[2] - tri[0]
    flip = (e1[0] * e2[1] - e1[1] * e2[0]) < 0                          # the map mirrors the picture: turn y over

    def mm(P):                                                # to millimetres, as seen (not mirrored)
        Q = to_mm(P)
        return Q * np.array([1.0, -1.0]) if flip else Q
    P = mm(part_px)
    if _area(P) < 0:
        P = P[::-1]
    inner = []
    for Hh in holes:
        if _inside(tuple(Hh.mean(axis=0)), part_px):
            Q = mm(Hh)
            if abs(_area(Q)) >= math.pi * (min_hole_mm / 2) ** 2:
                inner.append(Q if _area(Q) > 0 else Q[::-1])
    # the part's own axes: its longest straight side along x, the part's corner at the origin
    first = fit_loop(P, tol)
    lines = [q for q in first if q["k"] == "line"]
    rot = 0.0
    if lines:
        q = max(lines, key=lambda q: math.dist(q["a"], q["b"]))
        rot = -math.atan2(q["b"][1] - q["a"][1], q["b"][0] - q["a"][0])
        rot = (rot + math.pi / 2) % math.pi - math.pi / 2
    R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
    P = P @ R.T
    org = P.min(axis=0)
    P = P - org
    inner = [Q @ R.T - org for Q in inner]
    inner.sort(key=lambda Q: (-abs(_area(Q))))
    prims = [fit_loop(P, tol)] + [fit_loop(Q, tol) for Q in inner]
    size = np.ptp(P, axis=0)
    dims = _dims(prims, scale["relative_uncertainty"], px_mm)
    u_edge = math.sqrt(2) * U_EDGE_PX * px_mm
    for name, v in (("width", float(size[0])), ("height", float(size[1]))):
        dims.append({"id": name, "kind": "overall " + name, "of": "outline", "value_mm": round(v, 3),
                     "uncertainty_mm": round(2.0 * math.hypot(u_edge, v * scale["relative_uncertainty"]), 3),
                     "evidence": EVIDENCE, "how_known": "assumed"})
    sketch = _dimension(_to_sketch(prims), prims, dims)
    counts = {k: sum(1 for lp in prims for q in lp if q["k"] == k) for k in ("line", "arc", "circle")}
    worst = max((q.get("residual", 0.0) for lp in prims for q in lp), default=0.0)
    out = {
        "version": VERSION, "photo": Path(str(path)).name, "image_px": [int(img.shape[1] / shrink), int(img.shape[0] / shrink)],
        "evidence": EVIDENCE, "scale": scale, "mm_per_px": round(1.0 / scale["px_per_mm"], 5),
        "tolerance_mm": round(tol, 4), "rotation_deg": round(math.degrees(rot), 3),
        "size_mm": [round(float(size[0]), 3), round(float(size[1]), 3)],
        "profile": {"loops": len(prims), "holes": len(prims) - 1, **counts, "largest_fit_residual_mm": round(float(worst), 4)},
        "dimensions": dims, "sketch": sketch,
        "outline_mm": [[round(float(x), 3), round(float(y), 3)] for x, y in P[:: max(1, len(P) // 400)]],
        "uncertainty": {
            "coverage": "k = 2 (about 95 %)", "edge_px": U_EDGE_PX, "edge_mm": round(U_EDGE_PX * px_mm, 4),
            "edge_assumed": True, "scale_relative": round(scale["relative_uncertainty"], 6),
            "formula": "U(D) = 2 sqrt((sqrt(2) u_edge / s)² + (D u_s / s)²); a radius from a short arc is worse by "
                       "1 / (1 - cos(sweep / 2))",
            "not_included": ["parallax: a part thicker than the reference, or not lying in its plane, reads large",
                             "lens distortion"] + ([] if scale.get("perspective_corrected") else
                                                   ["camera tilt (only a card reference corrects it)"])},
        "caveats": ["Every dimension is estimated from the photo: use it as a start and measure what matters "
                    "(ask_measurement) before a fit depends on it."],
    }
    out["headline"] = (f"Profile {out['size_mm'][0]:.1f} x {out['size_mm'][1]:.1f} mm from the photo: {counts['line']} "
                       f"line(s), {counts['arc']} arc(s), {counts['circle']} circle(s), {len(prims) - 1} hole(s); "
                       f"{out['mm_per_px']:.3f} mm per pixel; overall size ±{dims[-2]['uncertainty_mm']:.2f} mm (k = 2), "
                       f"estimated from the photo.")
    return out


def solved(result: dict) -> dict:
    """The traced sketch through form.sketch2d's solver (form/handsketch.py): whether it solves and closes."""
    from . import handsketch
    return handsketch.solve(result["sketch"])


def create(st, result: dict, name: str = "", depth: float = 5.0, purpose: str | None = None) -> dict:
    """A new design: the traced profile extruded by `depth` (the depth is not in a photo: it is assumed)."""
    from . import modelling
    sol = solved(result)
    if not sol.get("ok") or not sol.get("closed"):
        raise PhotoError("The traced profile does not close into a sketch: " + str(sol.get("error") or sol.get("open") or ""),
                         "Try a larger tolerance_mm, or a sharper photo.")
    p = modelling.start_from_sketch(st, name or "Part from a photo", result["sketch"], "extrude", purpose or "model",
                                    depth=float(depth))
    return p


# ── MCP and the command line ─────────────────────────────────────────────────────────────────────────────────────

def call(st, photo: str, reference: dict | None = None, part_at=None, tolerance_mm: float | None = None,
         build: bool = False, name: str = "", depth: float = 5.0, purpose: str | None = None, full: bool = False) -> dict:
    """trace(), as the tool and the CLI return it: without the long outline unless full; build=True writes a design
    (the profile extruded) whose parameters are assumed, with the photo named as where they came from."""
    from .studio import StudioError
    try:
        r = trace(photo, reference, part_at, tolerance_mm)
        sol = solved(r)
        r["sketch_solves"] = {"ok": bool(sol.get("ok")), "closed": bool(sol.get("closed")), "loops": sol.get("loops"),
                              "degrees_of_freedom": sol.get("dof"), **({"error": sol["error"]} if sol.get("error") else {})}
        if build:
            p = create(st, r, name, depth, purpose)
            r["project"], r["head"] = p["id"], p["head"]
            r["depth_mm"] = {"value": float(depth), "how_known": "assumed", "note": "a photo from above does not show the thickness"}
            r["parameters"] = "every parameter of the design is assumed (estimated from the photo); measure what a fit depends on"
    except PhotoError as e:
        raise StudioError(str(e), e.hint, status=422) from None
    if not full:
        r.pop("outline_mm", None)
    return r


def register_tools(mcp, studio, run_async, RO, RW, origin) -> None:
    @mcp.tool(annotations=RW)
    async def photo_profile(photo: str, reference: dict | None = None, part_at: list[float] | None = None,
                            tolerance_mm: float | None = None, build: bool = False, name: str = "", depth: float = 5.0,
                            purpose: str = "", full: bool = False) -> dict:
        """A flat part's outline from a photo with a reference object, as a dimensioned sketch in millimetres. photo:
        the path of a picture the person gave (taken square on, the part beside the reference on a plain background).
        reference: {"kind": "card"} (default: a bank card, ISO/IEC 7810 ID-1, 85.60 x 53.98 mm; its four corners
        give a homography, so perspective in its plane is removed), {"kind": "coin", "coin": "eur_1"} (eur_0.01 to
        eur_2, usd_0.01 to usd_0.25) or {"kind": "coin", "diameter_mm": d}, or {"kind": "scale", "points": [[x, y],
        [x, y]], "length_mm": L} (two pixel points a known distance apart, such as two ruler marks); add "at": [x, y]
        (pixels) to point at the reference, and part_at=[x, y] to point at the part (default: the largest other
        object). The outline is found at sub-pixel positions (threshold between background and object, marching
        squares), simplified, and fitted with lines, arcs and circles within tolerance_mm (default 1.5 pixels).
        Returns scale (mm per pixel, its relative uncertainty and where the reference's size is from), dimensions
        (every length, radius, diameter and the overall size, each with ± uncertainty at k = 2 from the pixel size
        and the reference's accuracy, each marked "estimated from the photo"), sketch (form.sketch2d data: points,
        lines, arcs, circles, horizontal / vertical / tangent, the driving dimensions) and what the uncertainty
        leaves out (parallax, lens distortion, tilt without a card). build=True writes a design: the profile
        extruded by depth (assumed: a photo does not show it); its parameters are assumed, never measured."""
        st = studio()
        return await run_async(call, st, photo, reference, part_at, tolerance_mm, build, name, depth, purpose or None, full)


def main(argv: list) -> int:
    """`form photo-profile PHOTO [...]`: prints JSON. Exit 0 with a result, 2 on an error."""
    import json
    import sys
    doc = """form photo-profile PHOTO [--card | --coin eur_1 | --coin-d 23.25 | --scale X0,Y0:X1,Y1=MM] [--ref-at X,Y]
                        [--part-at X,Y] [--tol MM] [--build] [--name N] [--depth MM] [--full] [--svg FILE]      JSON
The part's outline as lines and arcs in mm, every dimension with its uncertainty, estimated from the photo."""
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(doc, file=sys.stderr)
        return 0 if argv else 2
    kw: dict = {"photo": argv[0]}
    ref: dict = {"kind": "card"}
    svg = None
    i = 1
    try:
        while i < len(argv):
            a = argv[i]
            if a in ("--build", "--full", "--card"):
                if a != "--card":
                    kw[a[2:]] = True
                i += 1
                continue
            if i + 1 >= len(argv):
                raise ValueError(f"{a} needs a value.")
            v = argv[i + 1]
            if a == "--coin":
                ref = {"kind": "coin", "coin": v}
            elif a == "--coin-d":
                ref = {"kind": "coin", "diameter_mm": float(v)}
            elif a == "--scale":
                pts, _, mm = v.partition("=")
                p0, _, p1 = pts.partition(":")
                ref = {"kind": "scale", "points": [[float(x) for x in p0.split(",")], [float(x) for x in p1.split(",")]],
                       "length_mm": float(mm)}
            elif a == "--ref-at":
                ref["at"] = [float(x) for x in v.split(",")]
            elif a == "--part-at":
                kw["part_at"] = [float(x) for x in v.split(",")]
            elif a == "--tol":
                kw["tolerance_mm"] = float(v)
            elif a == "--depth":
                kw["depth"] = float(v)
            elif a == "--name":
                kw["name"] = v
            elif a == "--svg":
                svg = v
            else:
                raise ValueError(f"Unknown option {a}.")
            i += 2
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    st = None
    try:
        if kw.get("build"):
            from . import config
            from .studio import Studio
            st = Studio(config.load())
        r = call(st, reference=ref, **kw)
        if svg:
            from . import handsketch
            sk, vals = handsketch.build(r["sketch"])
            Path(svg).write_text(sk.svg(vals), encoding="utf-8")
            r["svg"] = svg
        print(json.dumps(r, indent=1, ensure_ascii=False, default=float))
        return 0
    except Exception as e:                                    # noqa: BLE001 - StudioError: said as JSON
        if type(e).__name__ != "StudioError":
            raise
        print(json.dumps({"error": str(e), "hint": getattr(e, "hint", "")}, indent=1, ensure_ascii=False))
        return 2
    finally:
        if st is not None:
            try:
                st.kernel.stop()
            except Exception:                                 # noqa: BLE001
                pass


__all__ = ["PhotoError", "CARD_MM", "COINS", "EVIDENCE", "load", "foreground", "contours", "fit_line", "fit_circle",
           "simplify", "fit_loop", "min_rect", "card_corners", "homography", "apply_h", "trace", "solved", "create", "call", "register_tools", "main"]
