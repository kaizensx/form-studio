"""Geometry of a print orientation, on the tessellation (pure numpy; no kernel, no slicer).

    m = Mesh(P, T)                              # triangles of a closed surface, outward normals, millimetres
    r = evaluate(m, down, critical_deg=45)      # one orientation: `down` is the design direction that faces the plate
    r["support_mm3"], r["support_contact_mm2"], r["contact_mm2"], r["tip_over_deg"], ...

**Supports.** A facet needs support when it faces down more steeply than the critical angle (measured from vertical:
0 is a wall, 90 a ceiling) and does not lie on the plate. The support under it is the column from the facet straight
down to the first surface of the part below it, or to the plate. Its volume is the integral over the facet's shadow
of that column's height. The facet's own height is linear, so the integral is exact wherever the whole shadow of a
piece lands on one plane (the plate, or one flat face). A facet is cut into pieces no longer than `res`; where a
piece's shadow straddles an edge of what is below, the centroid rule is off by at most that piece's area times the
step, and `support_mm3_spread` is the difference between two quadrature rules (one point and three points per piece),
a measure of exactly that. The floor is found by casting a ray down from each quadrature point.

**Plate contact and tip-over.** Contact is the flat area lying on the plate. The part tips when its centre of mass
(of the solid, uniform density) leaves the convex hull of that contact: `tip_over_deg` is the tilt at which it does,
atan(distance from the centre's foot to the hull's edge / the centre's height). Zero when the foot is outside, or
when nothing flat is on the plate (the part then stands on its supports).

**Cusp height** (Dolenc and Makela 1994, "Slicing procedures for layered manufacturing techniques", Computer-Aided
Design 26(2)): a layer of thickness t leaves a stair of height t |cos a| on a face whose normal makes the angle a with
the build direction. Flat faces that face straight up or lie on the plate have no stairs.

**Stress across the layers.** With a strength study's stress field (the tensor at the surface nodes), the stress
normal to the layers is b.s.b for the build direction b. Its largest tensile value over the nodes, over the Z
strength, is how much of the weak direction the load uses in that orientation. The field is the isotropic study's, so
this is first order: how anisotropy moves the stress itself is not in it (the layer-aware study is).
"""
from __future__ import annotations

import math

import numpy as np

CONTACT_EPS = 0.05          # mm above the lowest point that still counts as lying on the plate
FLAT = 0.999                # cos of 2.6 deg: a facet this close to horizontal is flat
PAIR_CHUNK = 1_500_000


# ---- directions --------------------------------------------------------------------------------------------------

def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if not n > 1e-12:
        raise ValueError("a direction of zero length")
    return v / n


def rotation(down) -> np.ndarray:
    """R with R @ down = (0, 0, -1): the single rotation about the axis down x (-z), as form.analysis applies for a
    "down:x,y,z" orientation, so what is computed here is what is exported and sliced."""
    d = unit(down)
    z = np.array([0.0, 0.0, -1.0])
    c = float(np.clip(d @ z, -1.0, 1.0))
    axis = np.cross(d, z)
    s = np.linalg.norm(axis)
    if s < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    k = axis / s
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * K + (1 - c) * (K @ K)


def icosphere(level: int = 2) -> np.ndarray:
    """Unit vectors of a geodesic grid: an icosahedron with every triangle split in four `level` times
    (10 * 4**level + 2 directions: 42, 162, 642). The spacing between neighbours is about 63.4 / 2**level degrees."""
    t = (1 + math.sqrt(5)) / 2
    V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7),
         (9, 8, 1)]
    V = [unit(v) for v in V]
    for _ in range(max(0, int(level))):
        cache, nf = {}, []

        def mid(a, b):
            k = (min(a, b), max(a, b))
            if k not in cache:
                V.append(unit(V[a] + V[b]))
                cache[k] = len(V) - 1
            return cache[k]
        for a, b, c in F:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        F = nf
    return np.array(V)


def spacing_deg(level: int) -> float:
    return 63.435 / 2 ** max(0, int(level))


def ring(d, step_deg: float, n: int = 6) -> np.ndarray:
    """n directions at step_deg around d."""
    d = unit(d)
    a = np.eye(3)[int(np.argmin(np.abs(d)))]
    u = unit(a - (a @ d) * d)
    v = np.cross(d, u)
    s, c = math.sin(math.radians(step_deg)), math.cos(math.radians(step_deg))
    ang = np.arange(n) * 2 * math.pi / n
    return c * d[None, :] + s * (np.cos(ang)[:, None] * u[None, :] + np.sin(ang)[:, None] * v[None, :])


# ---- the Pareto front --------------------------------------------------------------------------------------------

def pareto(F) -> np.ndarray:
    """Mask of the rows of F (n, m; every column is to be minimised) that no other row dominates. A row dominates
    another when it is no worse in every column and better in at least one. Equal rows do not dominate each other."""
    F = np.asarray(F, dtype=np.float64)
    if F.ndim != 2:
        raise ValueError("objectives are a table: one row per candidate, one column per objective")
    n = len(F)
    keep = np.ones(n, dtype=bool)
    for i in range(n):
        le = np.all(F <= F[i], axis=1)
        lt = np.any(F < F[i], axis=1)
        if np.any(le & lt):
            keep[i] = False
    return keep


# ---- the mesh ----------------------------------------------------------------------------------------------------

class Mesh:
    """Triangles with what does not depend on the orientation: normals, areas, the volume and the centre of mass."""

    def __init__(self, P, T):
        self.P = np.asarray(P, dtype=np.float64)
        self.T = np.asarray(T, dtype=np.int64)
        a, b, c = self.P[self.T[:, 0]], self.P[self.T[:, 1]], self.P[self.T[:, 2]]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n, axis=1)
        self.area = ln / 2
        self.n = n / np.maximum(ln, 1e-300)[:, None]
        self.a, self.b, self.c = a, b, c
        v6 = np.einsum("ij,ij->i", a, np.cross(b, c))
        self.volume = float(v6.sum() / 6.0)
        if abs(self.volume) > 1e-12:
            self.com = ((a + b + c) * v6[:, None]).sum(axis=0) / (24.0 * self.volume)
        else:
            self.com = self.P.mean(axis=0)
        self.diag = float(np.linalg.norm(np.ptp(self.P, axis=0))) if len(self.P) else 0.0
        self.surface = float(self.area.sum())


def _lattice(n: int):
    """Centroids (n*n, 2) and three-point rule points (n*n, 3, 2) of a triangle cut into n*n equal ones, as
    barycentric (u, v): point = a + u (b - a) + v (c - a)."""
    cen, tri = [], []
    for i in range(n):
        for j in range(n - i):
            cen.append((i + 1 / 3, j + 1 / 3))
            tri.append(((i + 1 / 6, j + 1 / 6), (i + 2 / 3, j + 1 / 6), (i + 1 / 6, j + 2 / 3)))
            if i + j < n - 1:
                cen.append((i + 2 / 3, j + 2 / 3))
                tri.append(((i + 5 / 6, j + 5 / 6), (i + 1 / 3, j + 5 / 6), (i + 5 / 6, j + 1 / 3)))
    return np.array(cen) / n, np.array(tri) / n


_LAT: dict = {}


def lattice(n: int):
    if n not in _LAT:
        _LAT[n] = _lattice(n)
    return _LAT[n]


class Floor:
    """What is straight below a point: the upward-facing triangles of the part, binned on a grid in the plate's
    plane. below(pts) gives, for each point, the highest surface under it (and whether there is one)."""

    def __init__(self, A, B, C, cells_max: int = 3_000_000):
        self.A, self.B, self.C = A, B, C
        self.n = len(A)
        if self.n == 0:
            return
        lo = np.minimum(np.minimum(A[:, :2], B[:, :2]), C[:, :2])
        hi = np.maximum(np.maximum(A[:, :2], B[:, :2]), C[:, :2])
        self.o = lo.min(axis=0)
        ext = np.maximum(hi.max(axis=0) - self.o, 1e-9)
        G = int(np.clip(round(math.sqrt(self.n)), 4, 160))
        while True:
            self.G = G
            self.h = ext / G
            i0 = np.clip(np.floor((lo - self.o) / self.h).astype(np.int64), 0, G - 1)
            i1 = np.clip(np.floor((hi - self.o) / self.h).astype(np.int64), 0, G - 1)
            dx, dy = i1[:, 0] - i0[:, 0] + 1, i1[:, 1] - i0[:, 1] + 1
            k = dx * dy
            if k.sum() <= cells_max or G <= 4:
                break
            G = max(4, G // 2)
        rep = np.repeat(np.arange(self.n), k)
        off = np.arange(len(rep)) - np.repeat(np.cumsum(k) - k, k)
        cell = (i0[rep, 1] + off // dx[rep]) * G + (i0[rep, 0] + off % dx[rep])
        order = np.argsort(cell, kind="stable")
        self.tri = rep[order]
        self.start = np.searchsorted(cell[order], np.arange(G * G + 1))

    def below(self, pts: np.ndarray, eps: float = 1e-6):
        """(z of the highest surface strictly below each point, or -inf; hit mask)."""
        m = len(pts)
        z = np.full(m, -np.inf)
        if self.n == 0 or m == 0:
            return z, np.zeros(m, dtype=bool)
        ij = np.floor((pts[:, :2] - self.o) / self.h).astype(np.int64)
        inside = np.all((ij >= 0) & (ij < self.G), axis=1)
        idx = np.where(inside)[0]
        cell = ij[idx, 1] * self.G + ij[idx, 0]
        cnt = self.start[cell + 1] - self.start[cell]
        cum = np.cumsum(cnt)
        s = 0
        while s < len(idx):
            base = cum[s - 1] if s else 0
            e = int(np.searchsorted(cum, base + PAIR_CHUNK, side="right"))
            e = max(e, s + 1)
            c = cnt[s:e]
            pi = np.repeat(idx[s:e], c)
            off = np.arange(len(pi)) - np.repeat(np.cumsum(c) - c, c)
            ti = self.tri[np.repeat(self.start[cell[s:e]], c) + off]
            A, B, C, p = self.A[ti], self.B[ti], self.C[ti], pts[pi]
            v0, v1, v2 = B[:, :2] - A[:, :2], C[:, :2] - A[:, :2], p[:, :2] - A[:, :2]
            den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
            ok = np.abs(den) > 1e-14
            den = np.where(ok, den, 1.0)
            u = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
            v = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
            zz = A[:, 2] + u * (B[:, 2] - A[:, 2]) + v * (C[:, 2] - A[:, 2])
            ok &= (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (zz < p[:, 2] - eps)
            np.maximum.at(z, pi[ok], zz[ok])
            s = e
        return z, np.isfinite(z)


def hull2d(pts: np.ndarray) -> np.ndarray:
    """Convex hull of points in the plane, counter-clockwise (Andrew's monotone chain)."""
    pts = np.unique(np.round(np.asarray(pts, dtype=np.float64), 6), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 1e-12:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(pts), half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def inside_margin(hull: np.ndarray, p) -> float:
    """Distance from p to the boundary of a convex polygon (counter-clockwise): positive inside, negative outside,
    0 for fewer than three corners."""
    if len(hull) < 3:
        return 0.0
    a, b = hull, np.roll(hull, -1, axis=0)
    e = b - a
    ln = np.maximum(np.linalg.norm(e, axis=1), 1e-300)
    d = (e[:, 0] * (p[1] - a[:, 1]) - e[:, 1] * (p[0] - a[:, 0])) / ln      # signed distance to each edge's line
    if np.all(d >= 0):
        return float(d.min())
    t = np.clip(np.einsum("ij,ij->i", np.asarray(p)[None, :] - a, e) / ln ** 2, 0, 1)
    return -float(np.linalg.norm(a + t[:, None] * e - np.asarray(p)[None, :], axis=1).min())


# ---- one orientation ---------------------------------------------------------------------------------------------

def evaluate(m: Mesh, down, critical_deg: float = 45.0, res: float | None = None, samples_max: int = 40000,
             layer: float = 0.2, cosmetic: np.ndarray | None = None, three_point: bool = False) -> dict:
    """Everything the orientation `down` decides, from the geometry alone.

    res: the longest piece an overhang facet is cut into before its column is measured (mm; default: a fortieth of
    the part's diagonal). three_point: also integrate with three points per piece and give the spread.
    cosmetic: mask of the triangles on the faces a person marked as the ones that show."""
    d = unit(down)
    R = rotation(d)
    zax = R[2]
    nz = m.n @ zax
    dn = -nz
    za, zb, zc = m.a @ zax, m.b @ zax, m.c @ zax
    zmin = float(min(za.min(), zb.min(), zc.min()))
    ztop = np.maximum(np.maximum(za, zb), zc)
    Q = m.P @ R.T
    size = Q.max(axis=0) - Q.min(axis=0)
    contact = (dn > FLAT) & (ztop - zmin < CONTACT_EPS)
    over = (dn > math.sin(math.radians(critical_deg)) + 1e-6) & ~contact
    ceiling = (dn > FLAT) & ~contact
    out = {"down": [float(x) for x in d], "height_mm": float(size[2]), "footprint_mm": [float(size[0]), float(size[1])],
           "contact_mm2": float(m.area[contact].sum()), "overhang_mm2": float(m.area[over].sum()),
           "ceiling_mm2": float(m.area[ceiling].sum()),
           "lateral_mm2": float((m.area * np.sqrt(np.maximum(1 - nz * nz, 0))).sum()),
           "top_mm2": float((m.area * np.maximum(nz, 0)).sum()), "bottom_mm2": float((m.area * np.maximum(dn, 0)).sum())}

    # supports: columns from the overhang facets down to the part or the plate
    vol = vol3 = on_part = shadow = 0.0
    n_samples = 0
    idx = np.where(over)[0]
    if len(idx):
        A, B, C = m.a[idx] @ R.T, m.b[idx] @ R.T, m.c[idx] @ R.T
        proj = m.area[idx] * dn[idx]                                   # the facet's shadow on the plate
        shadow = float(proj.sum())
        res = float(res) if res else max(m.diag / 40.0, 0.2)
        edge = np.sqrt(np.maximum(np.maximum(((B - A)[:, :2] ** 2).sum(1), ((C - B)[:, :2] ** 2).sum(1)),
                                  ((A - C)[:, :2] ** 2).sum(1)))
        nsub = np.clip(np.ceil(edge / res).astype(int), 1, 24)
        while (nsub.astype(np.int64) ** 2).sum() > samples_max and nsub.max() > 1:
            nsub = np.maximum(1, (nsub * 0.8).astype(int))
        up = nz > 1e-6
        floor = Floor(m.a[up] @ R.T, m.b[up] @ R.T, m.c[up] @ R.T)
        for k in np.unique(nsub):
            sel = nsub == k
            cen, tri = lattice(int(k))
            a_, ab, ac = A[sel], (B - A)[sel], (C - A)[sel]
            w = np.repeat(proj[sel] / (k * k), len(cen))
            pts = (a_[:, None, :] + cen[None, :, 0, None] * ab[:, None, :] + cen[None, :, 1, None] * ac[:, None, :]).reshape(-1, 3)
            zf, hit = floor.below(pts)
            h = pts[:, 2] - np.where(hit, zf, zmin)
            vol += float((w * h).sum())
            on_part += float(w[hit].sum())
            n_samples += len(pts)
            if three_point:
                p3 = (a_[:, None, None, :] + tri[None, :, :, 0, None] * ab[:, None, None, :]
                      + tri[None, :, :, 1, None] * ac[:, None, None, :]).reshape(-1, 3)
                zf3, hit3 = floor.below(p3)
                vol3 += float((np.repeat(w / 3.0, 3) * (p3[:, 2] - np.where(hit3, zf3, zmin))).sum())
    out.update({"support_mm3": vol, "support_shadow_mm2": shadow, "support_on_part_mm2": on_part,
                # where support touches the part: the facets it holds up, and where it stands on the part
                "support_contact_mm2": float(m.area[over].sum()) + on_part, "support_samples": n_samples})
    if three_point:
        out["support_mm3_three_point"] = vol3
        out["support_mm3_spread"] = abs(vol3 - vol)

    # the plate: contact, and the tilt at which the part tips
    com = R @ m.com
    com_h = float(com[2] - zmin)
    tip, margin = 0.0, 0.0
    if contact.any():
        pts = np.concatenate([m.a[contact], m.b[contact], m.c[contact]]) @ R.T
        hull = hull2d(pts[:, :2])
        margin = inside_margin(hull, com[:2])
        if margin > 0 and com_h > 1e-9:
            tip = math.degrees(math.atan2(margin, com_h))
    out.update({"com_height_mm": com_h, "com_margin_mm": float(margin), "tip_over_deg": float(tip),
                "rests_on_supports": bool(out["contact_mm2"] < 1.0)})

    # stairs on the faces that show
    if cosmetic is not None and np.any(cosmetic):
        c = np.asarray(cosmetic, dtype=bool)
        a_c = m.area[c]
        stairs = np.where(np.abs(nz[c]) < FLAT, layer * np.abs(nz[c]), 0.0)
        out.update({"cosmetic_mm2": float(a_c.sum()),
                    "cosmetic_cusp_um": float(1000.0 * (stairs * a_c).sum() / max(a_c.sum(), 1e-300)),
                    "cosmetic_cusp_max_um": float(1000.0 * stairs.max()) if len(stairs) else 0.0,
                    "cosmetic_supported_mm2": float(m.area[c & over].sum()),
                    "cosmetic_on_plate_mm2": float(m.area[c & contact].sum())})
    return out


def across_layers(stress: np.ndarray, down, ok: np.ndarray | None = None) -> dict:
    """Stress normal to the layers at each node, for the build direction opposite `down`.
    stress: (n, 6) xx, yy, zz, xy, yz, zx in the design frame (MPa). ok: nodes that count (outside singular zones).
    Returns the largest tension across the layers and the largest shear in the layer plane."""
    b = -unit(down)
    s = np.asarray(stress, dtype=np.float64)
    if ok is not None:
        s = s[np.asarray(ok, dtype=bool)]
    if len(s) == 0:
        return {"tension_MPa": 0.0, "shear_MPa": 0.0}
    t = np.stack([s[:, 0] * b[0] + s[:, 3] * b[1] + s[:, 5] * b[2],
                  s[:, 3] * b[0] + s[:, 1] * b[1] + s[:, 4] * b[2],
                  s[:, 5] * b[0] + s[:, 4] * b[1] + s[:, 2] * b[2]], axis=1)       # traction on the layer plane
    sn = t @ b
    tau = np.sqrt(np.maximum((t * t).sum(axis=1) - sn * sn, 0.0))
    return {"tension_MPa": float(max(sn.max(), 0.0)), "shear_MPa": float(tau.max())}
