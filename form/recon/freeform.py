"""Layer 1, freeform surfaces: B-spline patches where no plane, cylinder, cone, sphere or torus fits. numpy and scipy
for the fit; the OCCT surface is made only when the face is built (brep.py, kernel worker).

Where it applies: a smooth part of the mesh (triangles joined across edges that bend less than SMOOTH_DEG) in which
the analytic fit left frozen facets, or which it could only cover with many small pieces of different surfaces (an
organic shape, a scan, a sculpted handle). Such a part is replaced by a few B-spline patches:

1. it is cut into height fields: each triangle goes to the one of six directions (the part's principal axes, both
   ways) its normal is closest to, and connected pieces of one direction are patches (small ones join a neighbour);
2. each patch is a bicubic B-spline height above the plane across its direction, fitted by least squares to the
   patch's vertices and the middles of its facets and their edges (a flat facet is farthest from the surface there,
   so the fit lies between the two and halves the mesh's own chord error) with a small bending penalty, and to the
   vertices just outside the patch; the knots are refined until every one of the patch's points is within FIT_SHARE
   of the tolerance, or the patch is left as it was;
3. the surface is exact as a B-spline (the plane coordinates are linear in the parameters, so the poles sit on the
   Greville points), and its normals follow the mesh's.

A patch is reported as "freeform (B-spline fitted)": smooth CAD within the tolerance, but not a dimension you can
change. Its boundary follows the mesh's edges between patches, so the faces meet exactly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .mesh import edges, tri_normals

SMOOTH_DEG = 30.0
FIT_SHARE = 0.6            # every vertex and facet middle of a patch within this share of the tolerance
SAG_WEIGHT = 1.0           # facet middles weigh as much as vertices: the surface lies between them
MIN_TRIS = 24
DEGREE = 3
LAST: list = []            # what the last fits came to (for the report)
MAX_POLES = 4000           # poles per patch: a bigger patch that needs more is split or left as it was
LAMBDA = float(__import__("os").environ.get("FF_LAMBDA", "1e-3"))


@dataclass
class Spline:
    """A fitted height field z = f(x, y) in the frame (o, e1, e2, n), with the interface of fit.Prim."""
    kind: str
    p: dict = field(default_factory=dict)
    rms: float = 0.0
    max: float = 0.0

    def _local(self, P):
        P = np.atleast_2d(P) - self.p["o"]
        return P @ self.p["e1"], P @ self.p["e2"], P @ self.p["n"]

    def _f(self, x, y, dx=0, dy=0):
        from scipy.interpolate import BSpline
        tx, ty, C = self.p["tx"], self.p["ty"], self.p["C"]
        x = np.clip(x, tx[DEGREE], tx[-DEGREE - 1])
        y = np.clip(y, ty[DEGREE], ty[-DEGREE - 1])
        Bx = BSpline.design_matrix(x, tx, DEGREE).toarray() if not dx else _deriv_matrix(x, tx)
        By = BSpline.design_matrix(y, ty, DEGREE).toarray() if not dy else _deriv_matrix(y, ty)
        return np.einsum("pi,ij,pj->p", Bx, C, By)

    def dist(self, P):
        x, y, z = self._local(P)
        f = self._f(x, y)
        fx, fy = self._f(x, y, dx=1), self._f(x, y, dy=1)
        return self.p["sign"] * (z - f) / np.sqrt(1 + fx * fx + fy * fy)

    def normal(self, P):
        x, y, _ = self._local(P)
        fx, fy = self._f(x, y, dx=1), self._f(x, y, dy=1)
        n = (-fx[:, None] * self.p["e1"] - fy[:, None] * self.p["e2"] + self.p["n"]) * self.p["sign"]
        return n / np.linalg.norm(n, axis=1)[:, None]

    def public(self):
        return {"kind": "bspline", "degree": DEGREE, "poles": [int(self.p["C"].shape[0]), int(self.p["C"].shape[1])],
                "rms_mm": round(self.rms, 6), "max_mm": round(self.max, 6), "evidence": "freeform (B-spline fitted)"}

    def surface(self):
        """The OCCT B-spline surface (kernel worker only)."""
        from OCP.Geom import Geom_BSplineSurface
        from OCP.collections import Array1_double as TColStd_Array1OfReal, Array1_int as TColStd_Array1OfInteger
        from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
        from OCP.gp import gp_Pnt
        tx, ty, C = self.p["tx"], self.p["ty"], self.p["C"]
        gx = np.array([tx[i + 1:i + DEGREE + 1].mean() for i in range(C.shape[0])])
        gy = np.array([ty[j + 1:j + DEGREE + 1].mean() for j in range(C.shape[1])])
        o, e1, e2, n = self.p["o"], self.p["e1"], self.p["e2"], self.p["n"]
        poles = TColgp_Array2OfPnt(1, C.shape[0], 1, C.shape[1])
        for i in range(C.shape[0]):
            for j in range(C.shape[1]):
                q = o + gx[i] * e1 + gy[j] * e2 + C[i, j] * n
                poles.SetValue(i + 1, j + 1, gp_Pnt(*map(float, q)))

        def knots(t):
            u, m = np.unique(np.round(t, 12), return_counts=True)
            K, M = TColStd_Array1OfReal(1, len(u)), TColStd_Array1OfInteger(1, len(u))
            for k, (a, b) in enumerate(zip(u, m), 1):
                K.SetValue(k, float(a))
                M.SetValue(k, int(b))
            return K, M
        ku, mu = knots(tx)
        kv, mv = knots(ty)
        return Geom_BSplineSurface(poles, ku, kv, mu, mv, DEGREE, DEGREE)


def _deriv_matrix(x, t):
    """First derivatives of the degree-3 basis at x: k (N[i,k-1] / (t[i+k] - t[i]) - N[i+1,k-1] / (t[i+k+1] - t[i+1]))."""
    from scipy.interpolate import BSpline
    k = DEGREE
    n = len(t) - k - 1
    B = BSpline.design_matrix(np.clip(x, t[k], t[-k - 1]), t[1:-1], k - 1).toarray()     # n - 1 basis of degree k-1
    B = np.c_[np.zeros(len(x)), B, np.zeros(len(x))]                                       # pad: N[0,k-1], N[n,k-1] = 0
    d0 = t[k:k + n] - t[0:n]
    d1 = t[k + 1:k + 1 + n] - t[1:1 + n]
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.where(d0 > 0, k / d0, 0.0)
        b = np.where(d1 > 0, k / d1, 0.0)
    return B[:, :n] * a - B[:, 1:n + 1] * b


def _tensor(Bx, By, ny):
    """Rows of the tensor-product basis: row k is the outer product of row k of Bx and of By."""
    from scipy.sparse import csr_matrix
    n = Bx.shape[0]
    bx, by = Bx.toarray(), By.toarray()
    k = DEGREE + 1
    ix = np.argsort(bx == 0, axis=1, kind="stable")[:, :k]
    iy = np.argsort(by == 0, axis=1, kind="stable")[:, :k]
    vx = np.take_along_axis(bx, ix, 1)
    vy = np.take_along_axis(by, iy, 1)
    rows = np.repeat(np.arange(n), k * k)
    cols = (ix[:, :, None] * ny + iy[:, None, :]).reshape(-1)
    vals = (vx[:, :, None] * vy[:, None, :]).reshape(-1)
    return csr_matrix((vals, (rows, cols)), shape=(n, Bx.shape[1] * ny))


def _dmat(x, t):
    """Sparse matrix of the first derivatives of the B-spline basis at x."""
    from scipy.sparse import csr_matrix
    return csr_matrix(_deriv_matrix(np.clip(x, t[DEGREE], t[-DEGREE - 1]), t))


def _knots(lo, hi, h):
    n = max(1, int(math.ceil((hi - lo) / h)))
    inner = np.linspace(lo, hi, n + 1)
    return np.r_[[lo] * DEGREE, inner, [hi] * DEGREE]


def fit_patch(V, F, tris, axis, tol, N=None, ring=None):
    """A B-spline height field over the plane across `axis` through the patch's vertices, or None."""
    from scipy.interpolate import BSpline
    from scipy.sparse import csr_matrix
    vid = np.unique(F[tris])
    a, b, c = V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]]
    # the vertices are on the surface; the triangles' middles and edge middles are where a flat facet is farthest
    # from it (the mesh's chord error), and they keep the surface from bulging between vertices
    # and the vertices just outside (on the same smooth surface) keep it from bending away at its edges
    extra = np.setdiff1d(np.unique(F[ring]), vid) if ring is not None and len(ring) else np.zeros(0, dtype=np.int64)
    P = np.r_[V[vid], (a + b + c) / 3, (a + b) / 2, (b + c) / 2, (c + a) / 2, V[extra]]
    wts = np.r_[np.ones(len(vid)), np.full(4 * len(tris), SAG_WEIGHT), np.full(len(extra), 0.5)]
    n = axis / np.linalg.norm(axis)
    t = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(n, t)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    o = P.mean(axis=0)
    x, y, z = (P - o) @ e1, (P - o) @ e2, (P - o) @ n
    span = max(np.ptp(x), np.ptp(y), 1e-9)
    m = 0.02 * span
    lo_x, hi_x, lo_y, hi_y = x.min() - m, x.max() + m, y.min() - m, y.max() + m
    # mean edge length: the knots need not be closer than the points
    el = float(np.mean(np.linalg.norm(a - b, axis=1)))
    nv = len(vid)
    best = None
    h = span / 6
    for _ in range(6):
        tx, ty = _knots(lo_x, hi_x, h), _knots(lo_y, hi_y, h)
        nx, ny = len(tx) - DEGREE - 1, len(ty) - DEGREE - 1
        if nx * ny > min(6 * nv + 64, MAX_POLES):
            break
        A = _tensor(BSpline.design_matrix(x, tx, DEGREE).tocsr(), BSpline.design_matrix(y, ty, DEGREE).tocsr(), ny)
        # bending penalty: second differences of the coefficients in both directions
        R = []
        lam = LAMBDA
        for i in range(nx):
            for j in range(ny):
                if 0 < i < nx - 1:
                    R.append({(i - 1) * ny + j: 1.0, i * ny + j: -2.0, (i + 1) * ny + j: 1.0})
                if 0 < j < ny - 1:
                    R.append({i * ny + j - 1: 1.0, i * ny + j: -2.0, i * ny + j + 1: 1.0})
        rr, cc, vv = [], [], []
        for r, d in enumerate(R):
            for col, val in d.items():
                rr.append(r)
                cc.append(col)
                vv.append(val * lam)
        Rm = csr_matrix((vv, (rr, cc)), shape=(len(R), nx * ny))
        from scipy.sparse import diags
        from scipy.sparse.linalg import spsolve
        Aw = diags(wts) @ A
        N_ = (Aw.T @ Aw + Rm.T @ Rm).tocsc()           # normal equations: banded, solved directly
        sol = spsolve(N_, Aw.T @ (wts * z))
        C = sol.reshape(nx, ny)
        # distance along the surface normal, not along the axis (a steep patch would look worse than it is)
        from scipy.interpolate import BSpline as _B
        fx = _tensor(_dmat(x, tx), _B.design_matrix(y, ty, DEGREE).tocsr(), ny) @ sol
        fy = _tensor(_B.design_matrix(x, tx, DEGREE).tocsr(), _dmat(y, ty), ny) @ sol
        res = np.abs(A @ sol - z) / np.sqrt(1 + fx * fx + fy * fy)
        ns = nv + 4 * len(tris)                        # the patch's own samples (not the ring round it)
        best = (C, tx, ty, float(res[:ns].max()), float(np.sqrt(np.mean(res[:ns] ** 2))), float(res[:nv].max()))
        if best[3] <= 0.5 * FIT_SHARE * tol:
            break
        if h < 0.75 * el:
            break
        h /= 2
    LAST.append({"tris": int(len(tris)), "h": round(h, 4), "max": best and round(best[3], 5),
                 "vertex_max": best and round(best[5], 5), "poles": best and list(best[0].shape)})
    if best is None or best[3] > FIT_SHARE * tol:
        LAST[-1]["why"] = "not within the tolerance"
        return None
    C, tx, ty, mx, rms, _ = best
    sp = Spline("bspline", {"o": o, "e1": e1, "e2": e2, "n": n, "tx": tx, "ty": ty, "C": C, "sign": 1.0}, rms, mx)
    if N is not None:
        cen = (a + b + c) / 3
        s = float(np.sign(np.einsum("ij,ij->i", sp.normal(cen), N[tris]).sum()) or 1.0)
        sp.p["sign"] = s
    # the surface must face the way the triangles do everywhere (a height field cannot fold)
    if N is not None and np.any(np.einsum("ij,ij->i", sp.normal((a + b + c) / 3), N[tris]) < 0.2):
        LAST[-1]["why"] = "the fitted surface folds against the facets"
        return None
    return sp


def _smooth_components(V, F, N):
    E, tri, eo, _ = edges(F)
    order = np.argsort(eo, kind="stable")
    eo_s, tri_s = eo[order], tri[order]
    nb = np.flatnonzero(eo_s[1:] == eo_s[:-1])
    t1, t2 = tri_s[nb], tri_s[nb + 1]
    c = np.clip(np.einsum("ij,ij->i", N[t1], N[t2]), -1, 1)
    sm = np.degrees(np.arccos(c)) < SMOOTH_DEG
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    g = coo_matrix((np.ones(int(sm.sum())), (t1[sm], t2[sm])), shape=(len(F), len(F)))
    return connected_components(g, directed=False)[1], (t1, t2)


def candidates(V, F, regions, tol) -> list[np.ndarray]:
    """Smooth parts of the mesh that the analytic fit did not explain well: triangle index arrays."""
    N, A = tri_normals(V, F)
    lab, _ = _smooth_components(V, F, N)
    reg_of = np.empty(len(F), dtype=np.int64)
    for r in regions:
        reg_of[r.tris] = r.id
    out = []
    for L in np.unique(lab):
        ts = np.flatnonzero(lab == L)
        if len(ts) < MIN_TRIS:
            continue
        regs = {int(i) for i in np.unique(reg_of[ts])}
        area = float(A[ts].sum())
        facet = sum(float(A[r.tris].sum()) for r in regions if r.id in regs and r.kind == "facet")
        analytic = [r for r in regions if r.id in regs and r.kind != "facet"]
        big = max((r.area for r in analytic), default=0.0)
        # many small pieces of different surfaces, or frozen facets: freeform. One surface that covers most of it,
        # or a few that make a mechanical part (planes and rounds meeting tangentially), are left alone.
        if facet >= 0.05 * area or (len(analytic) >= 12 and big < 0.35 * area):
            out.append(ts)
    return out


def patches(V, F, tris, N):
    """Height-field patches of a smooth part: lists of triangles, each with its direction."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    P = V[np.unique(F[tris])]
    _, _, vt = np.linalg.svd(P - P.mean(axis=0), full_matrices=False)
    dirs = np.r_[vt, -vt]
    lab = np.argmax(N[tris] @ dirs.T, axis=1)
    # adjacency within the part
    E, tri, eo, _ = edges(F[tris])
    order = np.argsort(eo, kind="stable")
    eo_s, tri_s = eo[order], tri[order]
    nb = np.flatnonzero(eo_s[1:] == eo_s[:-1])
    t1, t2 = tri_s[nb], tri_s[nb + 1]
    for _ in range(8):                                  # smooth the labels: a triangle follows most of its neighbours
        cnt = np.zeros((len(tris), 6))
        np.add.at(cnt, (t1, lab[t2]), 1)
        np.add.at(cnt, (t2, lab[t1]), 1)
        cnt[np.arange(len(tris)), lab] += 0.5
        new = np.argmax(cnt, axis=1)
        ok = (N[tris] * dirs[new]).sum(1) > 0.5         # still a height field over that direction, not steep
        lab = np.where(ok, new, lab)
    for _ in range(6):                                  # small islands join the neighbour they share most edges with
        same = lab[t1] == lab[t2]
        g = coo_matrix((np.ones(int(same.sum())), (t1[same], t2[same])), shape=(len(tris), len(tris)))
        comp = connected_components(g, directed=False)[1]
        size = np.bincount(comp)
        small = size[comp] < max(MIN_TRIS, len(tris) // 200)
        if not small.any():
            break
        cnt = np.zeros((len(tris), 6))
        m1, m2 = small[t1] & ~small[t2], small[t2] & ~small[t1]
        np.add.at(cnt, (t1[m1], lab[t2[m1]]), 1)
        np.add.at(cnt, (t2[m2], lab[t1[m2]]), 1)
        has = cnt.sum(1) > 0
        new = np.argmax(cnt, axis=1)
        ok = small & has & ((N[tris] * dirs[new]).sum(1) > 0.2)
        if not ok.any():
            break
        lab = np.where(ok, new, lab)
    same = lab[t1] == lab[t2]
    g = coo_matrix((np.ones(int(same.sum())), (t1[same], t2[same])), shape=(len(tris), len(tris)))
    comp = connected_components(g, directed=False)[1]
    groups = {}
    for i, c in enumerate(comp.tolist()):
        groups.setdefault(c, []).append(i)
    out = []
    for c, idx in groups.items():
        idx = np.array(idx)
        out.append((tris[idx], dirs[lab[idx[0]]]))
    return out


def apply(V, F, regions, tol, progress=None) -> tuple[list, dict]:
    """Replace the freeform parts of `regions` by B-spline regions where they fit. Returns (regions, report)."""
    from .segment import Region
    N, A = tri_normals(V, F)
    parts = candidates(V, F, regions, tol)
    rep = {"parts": len(parts), "patches": 0, "fitted": 0, "left_as_was": 0}
    if not parts:
        return regions, rep
    taken = np.zeros(len(F), dtype=bool)
    new = []
    for k, ts in enumerate(parts):
        if progress:
            progress({"stage": "layer1", "text": f"Fitting B-spline surfaces: part {k + 1} of {len(parts)}",
                      "fraction": 0.5 * k / len(parts)})
        inpart = np.zeros(len(F), dtype=bool)
        inpart[ts] = True
        for ptris, d in patches(V, F, ts, N):
            rep["patches"] += 1
            if len(ptris) < 4:
                continue
            near = np.zeros(len(V), dtype=bool)
            near[F[ptris]] = True
            for _ in range(2):                          # two rings of triangles round the patch, in the same part
                tr = np.flatnonzero(inpart & near[F].any(axis=1))
                near[F[tr]] = True
            sp = fit_patch(V, F, ptris, d, tol, N, ring=np.setdiff1d(tr, ptris))
            if sp is None:
                rep["left_as_was"] += 1
                continue
            rep["fitted"] += 1
            taken[ptris] = True
            new.append(Region(0, "bspline", ptris, sp, float(A[ptris].sum())))
    if not new:
        return regions, rep
    out = []
    for r in regions:                                   # what is left of each region keeps its kind (facets per triangle)
        keep = r.tris[~taken[r.tris]]
        if len(keep) == len(r.tris):
            out.append(r)
        elif len(keep):
            if r.kind == "facet" or len(keep) < 8:
                out += [Region(0, "facet", np.array([t]), None, float(A[t])) for t in keep.tolist()]
            else:
                out.append(Region(0, r.kind, keep, r.prim, float(A[keep].sum())))
    out += new
    for i, r in enumerate(out):
        r.id = i
    rep["area_mm2"] = round(float(sum(r.area for r in new)), 3)
    return out, rep
