"""From an optimised density field to something a person can edit: pockets with outlines, and the ribs between them
with their widths (runs in the FEA engine's Python: NumPy and SciPy).

    layout = pockets(image, inside, keep, grid, volfrac, ...)

The field of a 2.5D optimisation is a picture across the pull direction (form/topo/mesh3d.py Sampler). Its
reconstruction, step by step, each with what it decides:

1. **Threshold.** The level at which the solid area equals the volume fraction asked for (found by bisection), so
   the pockets remove what the optimisation removed, not more.
2. **Clean.** Void that touches a non-design region or the rim is given back; specks smaller than the smallest
   pocket are dropped; an island of material inside a pocket would fall out of a through cut, so it is removed
   with the pocket and counted.
3. **Outline.** The void is smoothed by one pixel and its boundary traced at sub-pixel positions (marching squares),
   then reduced to the fewest corners that stay within a stated distance of the traced line (Douglas-Peucker), and
   sides too short to carry a corner arc are merged: a pocket is a handful of straight sides.
4. **Ribs.** The material between the pockets is thinned to its centre lines (Zhang and Suen 1984); each stretch
   between two junctions is one rib, with its length and its width (twice the distance to the nearest edge).

Each pocket becomes one named feature of the design (form/topo/emit.py); what could not be written as a pocket is
said. `iso_mesh` is the other way out, for a free 3D layout: the smoothed surface of the dense region, as a mesh.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

POCKETS_MAX = 40
THRESHOLD_MAX = 0.9          # the level is never raised past this density to meet the volume
SIMPLIFY_PX = 0.45           # an outline's corners stay within this many pixels of the traced boundary


def threshold_for(image: np.ndarray, inside: np.ndarray, volfrac: float, weight: np.ndarray | None = None) -> float:
    """The density level above which the (thickness-weighted) area is volfrac of the inside."""
    w = (weight if weight is not None else np.ones_like(image))[inside]
    d = image[inside]
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if (w * (d > mid)).sum() > volfrac * w.sum():
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---- outlines --------------------------------------------------------------------------------------------------------

def contours(field: np.ndarray, level: float = 0.5) -> list:
    """Closed boundaries of {field > level} as (n, 2) arrays of (column, row) positions in pixel-centre units, the
    region on the left of the direction of travel (an outer boundary has positive area, a hole negative,
    with columns as x and rows as y). Marching squares with linear interpolation; saddles joined by the cell's mean."""
    g = np.pad(np.asarray(field, float), 1, constant_values=level - 1.0)
    b = g > level
    code = (b[:-1, :-1] * 1 + b[:-1, 1:] * 2 + b[1:, 1:] * 4 + b[1:, :-1] * 8).astype(int)
    segs = {}

    def cross(i, j, edge):
        """The point where the level crosses an edge of cell (i, j): 0 top, 1 right, 2 bottom, 3 left."""
        if edge == 0:
            a, c, p, q = g[i, j], g[i, j + 1], (j, i), (j + 1, i)
        elif edge == 1:
            a, c, p, q = g[i, j + 1], g[i + 1, j + 1], (j + 1, i), (j + 1, i + 1)
        elif edge == 2:
            a, c, p, q = g[i + 1, j], g[i + 1, j + 1], (j, i + 1), (j + 1, i + 1)
        else:
            a, c, p, q = g[i, j], g[i + 1, j], (j, i), (j, i + 1)
        t = (level - a) / (c - a) if c != a else 0.5
        t = min(1.0, max(0.0, t))
        return (p[0] + t * (q[0] - p[0]) - 1.0, p[1] + t * (q[1] - p[1]) - 1.0)

    def key(i, j, edge):
        return ("h", i, j) if edge == 0 else ("v", i, j + 1) if edge == 1 else ("h", i + 1, j) if edge == 2 else ("v", i, j)
    # per case: (from edge, to edge) with the inside on the left
    table = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)], 9: [(2, 0)],
             11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)]}
    pts = {}
    for i, j in zip(*np.where((code > 0) & (code < 15))):
        c = int(code[i, j])
        if c in (5, 10):
            mid = g[i:i + 2, j:j + 2].mean() > level
            pairs = ([(3, 0), (1, 2)] if not mid else [(3, 2), (1, 0)]) if c == 5 else \
                    ([(0, 1), (2, 3)] if not mid else [(0, 3), (2, 1)])
        else:
            pairs = table[c]
        for a, e in pairs:
            ka, ke = key(i, j, a), key(i, j, e)
            pts[ka], pts[ke] = cross(i, j, a), cross(i, j, e)
            segs[ka] = ke
    loops = []
    while segs:
        start, nxt = next(iter(segs.items()))
        loop = [start]
        del segs[start]
        while nxt != start and nxt in segs:
            loop.append(nxt)
            nxt = segs.pop(nxt)
        if nxt == start and len(loop) >= 3:
            loops.append(np.array([pts[k] for k in loop], float)[::-1])
    return loops


def area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def simplify(poly: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker on a closed polygon: split at its two farthest-apart corners, simplify each half."""
    n = len(poly)
    if n <= 4:
        return poly
    i0 = int(np.argmax(np.linalg.norm(poly - poly[0], axis=1)))

    def dp(P):
        if len(P) <= 2:
            return P
        a, b = P[0], P[-1]
        ab = b - a
        L = np.linalg.norm(ab)
        d = np.abs(ab[0] * (P[1:-1, 1] - a[1]) - ab[1] * (P[1:-1, 0] - a[0])) / L if L > 1e-12 else np.linalg.norm(P[1:-1] - a, axis=1)
        k = int(np.argmax(d))
        if d[k] <= tol:
            return np.array([a, b])
        left, right = dp(P[: k + 2]), dp(P[k + 1:])
        return np.concatenate([left[:-1], right])
    h1 = dp(poly[: i0 + 1])
    h2 = dp(np.concatenate([poly[i0:], poly[:1]]))
    return np.concatenate([h1[:-1], h2[:-1]])


def merge_short(poly: np.ndarray, min_len: float) -> np.ndarray:
    """The polygon without sides shorter than min_len: the two ends of the shortest such side become their middle,
    until none is left. A very short side leaves no room for a corner arc and a sliver for a mesher."""
    P = np.asarray(poly, float)
    while len(P) > 3:
        d = np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1)
        k = int(np.argmin(d))
        if d[k] >= min_len:
            break
        mid = (P[k] + P[(k + 1) % len(P)]) / 2
        P[k] = mid
        P = np.delete(P, (k + 1) % len(P), axis=0)
    return P


def inside_polygon(pt, poly: np.ndarray) -> bool:
    x, y = pt
    x0, y0 = poly[:, 0], poly[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    hit = ((y0 > y) != (y1 > y)) & (x < (x1 - x0) * (y - y0) / np.where(y1 != y0, y1 - y0, 1e-300) + x0)
    return bool(hit.sum() % 2)


# ---- ribs --------------------------------------------------------------------------------------------------------------

def thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning: the one-pixel centre lines of a region."""
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p2, p3, p4 = img[:-2, 1:-1], img[:-2, 2:], img[1:-1, 2:]
            p5, p6, p7 = img[2:, 2:], img[2:, 1:-1], img[2:, :-2]
            p8, p9 = img[1:-1, :-2], img[:-2, :-2]
            nb = [p2, p3, p4, p5, p6, p7, p8, p9]
            B = sum(nb)
            A = sum(((nb[k] == 0) & (nb[(k + 1) % 8] == 1)).astype(np.uint8) for k in range(8))
            if step == 0:
                cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            kill = (img[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & cond
            if kill.any():
                img[1:-1, 1:-1][kill] = 0
                changed = True
        if not changed:
            break
    return img[1:-1, 1:-1].astype(bool)


def ribs(solid: np.ndarray, px: float, to_xy) -> dict:
    """The members of the material: centre lines between junctions, each with its length and width."""
    if not solid.any():
        return {"members": [], "width_min_mm": None, "width_median_mm": None}
    dist = ndi.distance_transform_edt(np.pad(solid, 1))[1:-1, 1:-1] * px
    sk = thin(solid)
    nbr = ndi.convolve(sk.astype(int), np.ones((3, 3), int), mode="constant") - sk
    junction = sk & (nbr >= 3)
    lab, n = ndi.label(sk & ~ndi.binary_dilation(junction, np.ones((3, 3), bool)), np.ones((3, 3), int))
    members = []
    for k in range(1, n + 1):
        ys, xs = np.where(lab == k)
        if len(ys) < 3:
            continue
        w = 2 * dist[ys, xs]
        # the two ends: the pixels farthest apart along the stretch
        pts = np.column_stack([xs, ys]).astype(float)
        a = pts[int(np.argmax(np.linalg.norm(pts - pts[0], axis=1)))]
        b = pts[int(np.argmax(np.linalg.norm(pts - a, axis=1)))]
        members.append({"from": [round(float(v), 2) for v in to_xy(a)], "to": [round(float(v), 2) for v in to_xy(b)],
                        "length_mm": round(float(len(ys) * px), 2), "width_mm": round(float(np.median(w)), 2),
                        "width_min_mm": round(float(w.min()), 2)})
    members.sort(key=lambda m_: -m_["length_mm"])
    wall = 2 * dist[sk]
    return {"members": members[:60], "count": len(members),
            "width_min_mm": round(float(wall.min()), 2) if len(wall) else None,
            "width_median_mm": round(float(np.median(wall)), 2) if len(wall) else None,
            "junctions": int(ndi.label(junction, np.ones((3, 3), int))[1])}


# ---- the layout ------------------------------------------------------------------------------------------------------

def pockets(image: np.ndarray, inside: np.ndarray, keep: np.ndarray, grid: dict, volfrac: float,
            min_pocket_mm: float, thickness: np.ndarray | None = None, rim_px: int = 0,
            tol_mm: float = 0.0) -> dict:
    """The layout of a 2.5D density picture: {"threshold", "pockets": [{"outline": [[u, v], ...] mm in the grid's
    frame, "area_mm2", "centre"}], "ribs", "dropped", "solid_fraction_predicted", ...}.

    Cleaning gives material back (the rim, the non-design regions, specks), so the pockets of the thresholded
    picture leave more than was asked for. They are then grown evenly, every rib thinned by the same amount from
    both sides, until the material left is the fraction asked for, and never so far that two pockets join or a rib
    falls below `min_pocket_mm` / 2: the layout keeps the members the optimisation found. "grown_mm" is by how
    much; when the limit stopped it, the fraction left is above the one asked for and both are stated."""
    args = (image, inside, keep, grid, min_pocket_mm, thickness, rim_px, max(float(tol_mm) / float(grid["px"]), SIMPLIFY_PX))
    t0 = threshold_for(image, inside, volfrac, thickness)
    px = float(grid["px"])
    best = _pockets_at(0.0, t0, *args)
    n0 = best["_components"]
    if best["solid_fraction_predicted"] > volfrac + 0.005 and n0:
        g = 0.0
        while g < 12.0:
            g += 0.5
            cand = _pockets_at(g, t0, *args)
            w = cand["ribs"]["width_min_mm"]
            if cand["_components"] < n0 or cand["dropped"]["islands"] > best["dropped"]["islands"] or \
                    (w is not None and w < max(min_pocket_mm / 2, 2 * px)):
                break
            if abs(cand["solid_fraction_predicted"] - volfrac) <= abs(best["solid_fraction_predicted"] - volfrac):
                best = cand
            if cand["solid_fraction_predicted"] <= volfrac:
                break
    best.pop("_components", None)
    best["threshold"] = round(float(t0), 4)
    best["volume_fraction_asked"] = round(float(volfrac), 4)
    return best


def _pockets_at(grow: float, t: float, image, inside, keep, grid, min_pocket_mm, thickness, rim_px, tol_px) -> dict:
    px = float(grid["px"])
    allowed = inside & ~keep
    if rim_px > 0:
        allowed &= ndi.binary_erosion(inside, iterations=int(rim_px), border_value=0)
    void = allowed & (image <= t)
    void = ndi.binary_opening(void, np.ones((3, 3), bool))
    if grow > 0 and void.any():
        void = allowed & (ndi.distance_transform_edt(~void) <= grow)
    lab, n = ndi.label(void)
    min_area_px = max(6.0, (min_pocket_mm / px) ** 2)
    dropped = {"small": 0, "islands": 0, "over_limit": 0}
    sizes = ndi.sum(void, lab, index=np.arange(1, n + 1)) if n else np.array([])
    for k, s in enumerate(sizes, 1):
        if s < min_area_px:
            void[lab == k] = False
            dropped["small"] += 1
    smooth = ndi.gaussian_filter(void.astype(float), 1.0)
    smooth[~inside] = np.minimum(smooth[~inside], 0.0)
    smooth[keep] = np.minimum(smooth[keep], 0.25)
    loops = [(lp, area(lp)) for lp in contours(smooth, 0.5)]
    outer = sorted(((lp, a) for lp, a in loops if a > 0), key=lambda x: -x[1])
    dropped["islands"] = sum(1 for _, a in loops if a < 0)

    def to_uv(P):
        P = np.atleast_2d(P)
        return np.column_stack([grid["u0"] + (P[:, 0] + 0.5) * px, grid["v0"] + (P[:, 1] + 0.5) * px])
    out, kept = [], []
    for lp, a in outer:
        if a * px * px < min_pocket_mm ** 2 * 0.6:
            dropped["small"] += 1
            continue
        if len(out) >= POCKETS_MAX:
            dropped["over_limit"] += 1
            continue
        sp = merge_short(simplify(lp, tol_px), 1.5 * tol_px)
        if len(sp) < 3 or area(sp) <= 0:
            continue
        uv = to_uv(sp)
        kept.append(sp)
        out.append({"outline": [[round(float(x), 3), round(float(y), 3)] for x, y in uv],
                    "area_mm2": round(float(area(uv)), 2), "corners": len(uv),
                    "centre": [round(float(v), 2) for v in uv.mean(axis=0)]})
    # what the outlines leave, on the pixel grid (for the ribs and the fraction that stays)
    cut = np.zeros_like(void)
    for lp in kept:
        x0, x1 = int(max(0, np.floor(lp[:, 0].min()))), int(min(image.shape[1] - 1, np.ceil(lp[:, 0].max())))
        y0, y1 = int(max(0, np.floor(lp[:, 1].min()))), int(min(image.shape[0] - 1, np.ceil(lp[:, 1].max())))
        xs = np.arange(x0, x1 + 1)
        xa, ya = lp[:, 0], lp[:, 1]
        xb, yb = np.roll(xa, -1), np.roll(ya, -1)
        for y in range(y0, y1 + 1):
            cr = ((ya[None, :] > y) != (yb[None, :] > y)) & \
                 (xs[:, None] < (xb - xa)[None, :] * (y - ya)[None, :] / np.where(yb != ya, yb - ya, 1e-300)[None, :] + xa[None, :])
            cut[y, x0:x1 + 1] |= (cr.sum(axis=1) % 2).astype(bool)
    solid = inside & ~cut
    w = thickness if thickness is not None else np.ones_like(image)
    frac = float((w * solid).sum() / max((w * inside).sum(), 1e-300))

    def to_xy(pt):
        return to_uv(np.asarray(pt, float))[0]
    return {"threshold": round(float(t), 4), "pockets": out, "dropped": dropped,
            "solid_fraction_predicted": round(frac, 4), "ribs": ribs(solid, px, to_xy),
            "tolerance_mm": round(tol_px * px, 3), "pixel_mm": round(px, 4),
            "grown_mm": round(grow * px, 3), "_components": len(out)}


# ---- the mesh-body way out --------------------------------------------------------------------------------------------

def iso_mesh(P: np.ndarray, T: np.ndarray, S: np.ndarray, nodal: np.ndarray, level: float, smooth: int = 10) -> tuple:
    """The surface of {density > level} on a tetrahedral mesh with densities at its vertices: the level surface
    inside the tetrahedra (marching tetrahedra) and the part of the boundary triangles S above the level, as
    (vertices, triangles). Then Taubin smoothing of the level surface's own vertices (boundary vertices stay on the
    part's surface), which removes the facets of the mesh without shrinking the body."""
    verts, index, tris = [], {}, []
    on_iso = []

    def edge_point(a, b):
        k = (a, b) if a < b else (b, a)
        i = index.get(k)
        if i is None:
            da, db = nodal[a] - level, nodal[b] - level
            t = da / (da - db) if da != db else 0.5
            i = index[k] = len(verts)
            verts.append(P[a] + t * (P[b] - P[a]))
            on_iso.append(True)
        return i

    def vert(a):
        k = (a, a)
        i = index.get(k)
        if i is None:
            i = index[k] = len(verts)
            verts.append(P[a])
            on_iso.append(False)
        return i
    above = nodal > level
    cnt = above[T].sum(axis=1)
    for tet in T[(cnt > 0) & (cnt < 4)]:
        ins = [int(v) for v in tet if above[v]]
        out = [int(v) for v in tet if not above[v]]
        if len(ins) == 1:
            tri = [edge_point(ins[0], o) for o in out]
            tris.append((tri, P[ins[0]]))
        elif len(ins) == 3:
            tri = [edge_point(i, out[0]) for i in ins]
            tris.append((tri, 2 * np.mean([verts[k] for k in tri], axis=0) - P[out[0]]))
        else:
            q = [edge_point(ins[0], out[0]), edge_point(ins[0], out[1]), edge_point(ins[1], out[1]), edge_point(ins[1], out[0])]
            inner = (P[ins[0]] + P[ins[1]]) / 2
            tris.append(([q[0], q[1], q[2]], inner))
            tris.append(([q[0], q[2], q[3]], inner))
    faces = []
    for tri, inner in tris:                              # outward: away from the dense side
        a, b, c = (np.asarray(verts[k]) for k in tri)
        n = np.cross(b - a, c - a)
        faces.append(tri if np.dot(n, (a + b + c) / 3 - inner) > 0 else [tri[0], tri[2], tri[1]])
    for tri in S:                                        # boundary triangles (already outward), clipped at the level
        ins = [int(v) for v in tri if above[v]]
        if len(ins) == 3:
            faces.append([vert(int(v)) for v in tri])
        elif len(ins) in (1, 2):
            poly = []
            for k in range(3):
                a, b = int(tri[k]), int(tri[(k + 1) % 3])
                if above[a]:
                    poly.append(vert(a))
                if above[a] != above[b]:
                    poly.append(edge_point(a, b))
            for k in range(1, len(poly) - 1):
                faces.append([poly[0], poly[k], poly[k + 1]])
    V = np.array(verts, float).reshape(-1, 3)
    F = np.array(faces, dtype=np.int64).reshape(-1, 3)
    if len(F) and smooth:
        free = np.array(on_iso, bool)
        # iso vertices that also lie on the boundary (cut boundary edges) move only along it: keep them still
        bnd = np.zeros(len(V), bool)
        edge_on_boundary = set()
        for tri in S:
            for k in range(3):
                a, b = int(tri[k]), int(tri[(k + 1) % 3])
                edge_on_boundary.add((a, b) if a < b else (b, a))
        for kk, i in index.items():
            if kk[0] != kk[1] and kk in edge_on_boundary:
                bnd[i] = True
        free &= ~bnd
        import scipy.sparse as sp_
        e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        A = sp_.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(V), len(V))).tocsr()
        A = ((A + A.T) > 0).astype(float)
        deg = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1.0)
        for _ in range(int(smooth)):
            for lam in (0.5, -0.53):
                L = (A @ V) / deg[:, None] - V
                V[free] += lam * L[free]
    return V, F
