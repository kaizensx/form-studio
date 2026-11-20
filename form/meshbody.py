"""Sculpted meshes as what they are: a smooth NURBS solid with a cage you can edit, or a mesh body with exact cuts.

Two routes from a triangle mesh (a sculpt, a scan, a download) to something a design can use:

**Surface body** (``organic_solid``): the mesh becomes a closed OCCT solid whose skin is a few exact B-spline surfaces,
within a stated tolerance of the mesh, editable through its control cage.
  - A *shell* (a helmet, a mask, a cowl: a thick skin with an open rim) is split at its creases into skins and rim;
    the outside and the inside are each mapped onto a disk inside the cage's parameter square (a harmonic map with the
    rim on a circle; the inside's rim takes the outside's parameters point for point), fitted as a bicubic B-spline
    grid cage by least squares with parameter correction (form.craft.subd; the grid is the quad remesh, its points
    the cage) and trimmed by that circle; the rim becomes one ruled face straight across between the two borders.
    Three faces, C2 inside each skin, no corners.
  - A *closed* smooth body (a character prop, a bust, a grip) is fitted by a closed quad cage (a subdivided cube-
    sphere shrink-wrapped onto the mesh) whose Catmull-Clark limit is turned into bicubic patches (ACC) and sewn.
  Each result says how far it is from the mesh (both ways, measured), how many faces it has and how smooth it is.

**Mesh body** (``MeshBody``): fine sculpted detail that is not worth a surface (a texture, engraved lines) stays a
mesh, and exact CAD features (holes, magnet pockets, bosses) are cut and added with manifold3d's exact mesh booleans.
Its exports are meshes (STL, 3MF), labelled as such; it has no STEP.

Tiers are labelled in what is returned: "surface body (subdivision cage to NURBS)", "mesh body (sculpted; CAD features
exact)", "parametric (CAD)".

numpy and scipy everywhere; OCCT only to build the solid (kernel worker); manifold3d only for MeshBody (optional:
``pip install manifold3d``; wheels for macOS, Windows and Linux).
"""
from __future__ import annotations

import math
import time

import numpy as np

TIER_SURFACE = "surface body (subdivision cage to NURBS)"
TIER_MESH = "mesh body (sculpted; CAD features exact)"
TIER_CAD = "parametric (CAD)"


# ── mesh basics ───────────────────────────────────────────────────────────────────────────────────────────────────

def weld(T: np.ndarray, tol: float = 1e-6):
    from .recon.mesh import weld as _weld
    V, F, _ = _weld(np.asarray(T, dtype=np.float64), tol)
    return V, F


def tri_normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    a = np.linalg.norm(n, axis=1)
    return n / np.maximum(a, 1e-300)[:, None], a / 2


def _edge_table(F):
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    tri = np.tile(np.arange(len(F)), 3)
    key = np.sort(he, axis=1)
    E, inv = np.unique(key, axis=0, return_inverse=True)
    return E, inv.reshape(-1), tri, he


def segment(V, F, crease_deg: float = 50.0, min_share: float = 1e-3) -> np.ndarray:
    """Label every triangle with its smooth region: regions meet at creases sharper than crease_deg."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    N, _ = tri_normals(V, F)
    E, eo, tri, _ = _edge_table(F)
    order = np.argsort(eo, kind="stable")
    eo_s, tri_s = eo[order], tri[order]
    pair = eo_s[1:] == eo_s[:-1]
    a, b = tri_s[:-1][pair], tri_s[1:][pair]
    smooth = np.einsum("ij,ij->i", N[a], N[b]) > math.cos(math.radians(crease_deg))
    g = coo_matrix((np.ones(int(smooth.sum())), (a[smooth], b[smooth])), shape=(len(F), len(F)))
    _, lab = connected_components(g, directed=False)
    # tiny regions (a sliver triangle whose normal is noise, a speck between creases) join the neighbour they share
    # most edges with, so a skin's border stays one loop
    _, area = tri_normals(V, F)
    for _ in range(6):
        tot = np.bincount(lab, weights=area)
        small = tot < min_share * tot.sum()
        bad = small[lab[a]] != small[lab[b]]
        if not small.any() or not bad.any():
            break
        x, y = np.where(small[lab[a]], a, b), np.where(small[lab[a]], b, a)
        m = bad
        new = lab.copy()
        new[x[m]] = lab[y[m]]
        if np.array_equal(new, lab):
            break
        lab = new
    _, lab = np.unique(lab, return_inverse=True)
    return lab


def boundary_loop(F) -> list[int]:
    """The single boundary loop of a disk-like triangle set, in the triangles' direction. Raises if not one loop."""
    E, eo, tri, he = _edge_table(F)
    cnt = np.bincount(eo, minlength=len(E))
    nxt = {}
    for k in np.flatnonzero(cnt[eo] == 1):
        a, b = he[k]
        nxt[int(a)] = int(b)
    if not nxt:
        raise ValueError("The region has no open border (it is closed): use the closed route.")
    start = next(iter(nxt))
    loop, cur = [start], nxt[start]
    while cur != start:
        loop.append(cur)
        cur = nxt.get(cur)
        if cur is None or len(loop) > len(nxt):
            raise ValueError("The region's border is not one simple loop.")
    if len(loop) != len(nxt):
        raise ValueError("The region has more than one border loop; a skin needs exactly one.")
    return loop


def _cotan_laplacian(V, F):
    import scipy.sparse as sp
    n = len(V)
    I, J, W = [], [], []
    for k in range(3):
        i, j, o = F[:, k], F[:, (k + 1) % 3], F[:, (k + 2) % 3]
        u, v = V[i] - V[o], V[j] - V[o]
        cot = np.einsum("ij,ij->i", u, v) / np.maximum(np.linalg.norm(np.cross(u, v), axis=1), 1e-12)
        w = np.clip(cot, 1e-3, 1e3) / 2
        I += [i, j]
        J += [j, i]
        W += [w, w]
    A = sp.csr_matrix((np.concatenate(W), (np.concatenate(I), np.concatenate(J))), shape=(n, n))
    return sp.diags(np.asarray(A.sum(1)).ravel()) - A


def _frame(P, toward):
    o = P.mean(0)
    _, _, vt = np.linalg.svd(P - o)
    n = vt[2]
    if np.dot(toward - o, n) < 0:
        n = -n
    e1 = vt[0]
    if abs(e1[0]) > 0.5 and e1[0] < 0:          # keep e1 pointing to +x where the rim is long in x (a helmet: front)
        e1 = -e1
    e2 = np.cross(n, e1)
    return o, e1, e2, n


# ── point to mesh distance ────────────────────────────────────────────────────────────────────────────────────────

class Nearest:
    """Closest points on a triangle mesh for many query points (candidates from a k-d tree of the triangles)."""

    def __init__(self, V, F, k: int = 12):
        from scipy.spatial import cKDTree
        self.A, self.B, self.C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        self.tree = cKDTree((self.A + self.B + self.C) / 3)
        self.k = min(k, len(F))

    def __call__(self, Q):
        from .analysis import closest_on_triangles
        Q = np.asarray(Q, dtype=np.float64)
        _, cand = self.tree.query(Q, k=self.k)
        cand = cand.reshape(len(Q), -1)
        best = np.full(len(Q), np.inf)
        out = np.zeros_like(Q)
        for j in range(cand.shape[1]):
            t = cand[:, j]
            p, d = closest_on_triangles(Q, self.A[t], self.B[t], self.C[t])
            m = d < best
            best[m], out[m] = d[m], p[m]
        return out, best


# ── shell route ───────────────────────────────────────────────────────────────────────────────────────────────────

def split_shell(V, F, crease_deg: float = 50.0) -> dict:
    """A thick shell's outer skin, inner skin and rim (triangle index sets), by creases and area."""
    lab = segment(V, F, crease_deg)
    _, area = tri_normals(V, F)
    tot = np.bincount(lab, weights=area)
    order = np.argsort(-tot)
    if len(order) < 2:
        raise ValueError("No creases split this mesh into skins: it is one smooth surface (use the closed route).")
    a, b = order[0], order[1]
    # the outer skin is the one further from the middle
    c = V[np.unique(F)].mean(0)
    da = np.mean(np.linalg.norm(V[F[lab == a]].reshape(-1, 3) - c, axis=1))
    db = np.mean(np.linalg.norm(V[F[lab == b]].reshape(-1, 3) - c, axis=1))
    outer, inner = (a, b) if da >= db else (b, a)
    return {"outer": np.flatnonzero(lab == outer), "inner": np.flatnonzero(lab == inner),
            "rim": np.flatnonzero((lab != outer) & (lab != inner)), "regions": int(len(tot)),
            "share": float((tot[outer] + tot[inner]) / tot.sum())}


from .craft.subd import DISK_R  # noqa: E402  (a skin's border: a circle of its cage's parameter square)


def circle_map(V, F, frame, border_from=None):
    """Harmonic map of a disk-like triangle set into the cage's parameter square: its border goes round the circle
    of radius DISK_R about (0.5, 0.5) (by arc length, starting where the frame's e1 points), the inside follows by a
    cotangent-weighted harmonic map (no fold for a disk). With border_from=(points, uv) of another skin's border, each
    border vertex takes the parameter of the nearest point there instead, so the two borders correspond point for
    point (the rim between them is then straight across). No corners: a disk on a disk."""
    import scipy.sparse.linalg as spl
    o, e1, e2, n = frame
    loop = boundary_loop(F)
    P = V[loop]
    q = P - o
    ang = np.arctan2(q @ e2, q @ e1)
    if np.sum(np.diff(np.unwrap(np.r_[ang, ang[0]]))) < 0:
        loop = loop[::-1]
        ang = ang[::-1]
    if border_from is None:
        k0 = int(np.argmin(np.abs(np.angle(np.exp(1j * ang)))))     # the border point straight ahead (+e1)
        loop = loop[k0:] + loop[:k0]
        P = V[loop]
        L = np.cumsum(np.r_[0, np.linalg.norm(np.diff(np.r_[P, P[:1]], axis=0), axis=1)])
        t = 2 * math.pi * L[:-1] / L[-1]
    else:
        P = V[loop]
        Q, quv = border_from
        tq = np.unwrap(np.arctan2(quv[:, 1] - 0.5, quv[:, 0] - 0.5))
        segA, segB = Q, np.roll(Q, -1, axis=0)
        tA, tB = tq, np.r_[tq[1:], tq[0] + 2 * math.pi]
        ab = segB - segA
        abab = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
        t = np.empty(len(P))
        for k, x in enumerate(P):                # nearest point on the other border (a polyline), its angle
            w = np.clip(np.einsum("ij,ij->i", x - segA, ab) / abab, 0, 1)
            d = np.linalg.norm(segA + w[:, None] * ab - x, axis=1)
            m = int(np.argmin(d))
            t[k] = tA[m] + w[m] * (tB[m] - tA[m])
    uv_b = np.c_[0.5 + DISK_R * np.cos(t), 0.5 + DISK_R * np.sin(t)]
    used = np.unique(F)
    Lp = _cotan_laplacian(V, F).tocsr()
    bset = np.array(loop)
    inner = np.setdiff1d(used, bset)
    UV = np.full((len(V), 2), np.nan)
    UV[bset] = uv_b
    lu = spl.splu(Lp[inner][:, inner].tocsc())
    Lib = Lp[inner][:, bset]
    for d in range(2):
        UV[inner, d] = lu.solve(-(Lib @ uv_b[:, d]))
    return _even_radius(UV, V, F, used), loop


def _even_radius(UV, V, F, used):
    """Re-space the map along its radius so equal rings of the disk hold equal surface area. A harmonic map of a
    dome squeezes its crown into the middle of the disk (a hemisphere's crown gets a quarter of the rim's share), and
    a uniform cage then has too few points where the crest and brow are. Angles and the border stay as they were."""
    c = np.array([0.5, 0.5])
    R = np.linalg.norm(UV[used] - c, axis=1)
    _, area = tri_normals(V, F)
    rc = np.linalg.norm(UV[F].mean(1) - c, axis=1)
    order = np.argsort(rc)
    cum = np.cumsum(area[order])
    cum /= cum[-1]
    target = DISK_R * np.sqrt(np.interp(R, rc[order], cum, left=0.0, right=1.0))
    target[R >= DISK_R * (1 - 1e-9)] = DISK_R
    k = np.where(R > 1e-12, target / np.maximum(R, 1e-12), 1.0)
    out = UV.copy()
    out[used] = c + (UV[used] - c) * k[:, None]
    return out


def fit_skin(V, F, frame, n: int, border_from=None, smooth: float = 1e-4, rounds: int = 3):
    """One skin as a grid cage: (C, distances of its vertices, (border points, their uv))."""
    from .craft import subd
    UV, loop = circle_map(V, F, frame, border_from)
    used = np.unique(F)
    P = V[used]
    u, v = UV[used, 0], UV[used, 1]
    C, u, v, d = subd.fit_grid_refined(P, u, v, n, n, rounds=rounds, smooth=smooth)
    return C, d, (V[loop], UV[loop]), used


def shell_cages(V, F, tol: float = 0.3, n0: int = 40, n_max: int = 128, crease_deg: float = 50.0) -> dict:
    """Fit the outer and inner skins of a thick shell mesh with grid cages (each skin a disk trimmed out of one
    B-spline surface), refining the cage until every skin vertex is within 0.7 x tol of its surface (99.5 % within 0.5 x).
    Returns {outer, inner, n, radius, skin distances, timings}."""
    t0 = time.perf_counter()
    parts = split_shell(V, F, crease_deg)
    Fo, Fi = F[parts["outer"]], F[parts["inner"]]
    Po = V[np.unique(Fo)]
    frame = _frame(V[boundary_loop(Fo)], Po.mean(0))
    n, best, tried = n0, None, []
    while True:
        Co, do, border, uo = fit_skin(V, Fo, frame, n)
        # the inside: its border takes the outer border's parameters point for point, so the rim runs straight across
        Ci, di, _, ui = fit_skin(V, Fi, frame, n, border_from=border)
        p995 = max(float(np.percentile(do, 99.5)), float(np.percentile(di, 99.5)))
        top = float(max(do.max(), di.max()))
        tried.append({"cage": n, "max_mm": round(top, 4), "p995_mm": round(p995, 4)})
        if best is None or top < best["top"]:
            best = {"top": top, "p995": p995, "n": n, "Co": Co, "Ci": Ci, "do": do, "di": di, "uo": uo, "ui": ui}
        # finer is not always closer: past a point a cage starts to ripple between the mesh's points
        if (p995 <= 0.5 * tol and top <= 0.7 * tol) or n >= n_max or (len(tried) > 2 and top > 1.2 * best["top"]):
            break
        n = min(n_max, int(n * 1.3) + 1)
    b = best
    do, di = b["do"], b["di"]
    return {"outer": b["Co"], "inner": b["Ci"], "n": b["n"], "radius": DISK_R, "skin_max_mm": b["top"],
            "skin_p995_mm": b["p995"], "skin_rms_mm": float(np.sqrt(np.mean(np.r_[do, di] ** 2))), "tried": tried,
            "split": {k: int(parts[k].size) for k in ("outer", "inner", "rim")}, "fit_s": time.perf_counter() - t0,
            "_skin": (np.r_[b["uo"], b["ui"]], np.r_[do, di]), "_rim": np.unique(F[parts["rim"]])}


def organic_solid(T_or_VF, tol: float = 0.3, kind: str = "auto", verify: int = 20000, cage: int | None = None):
    """A sculpted mesh as a closed NURBS solid within tol (mm). T_or_VF: triangles (m, 3, 3) or (V, F).
    kind: "shell" (a thick skin with a rim), "closed" (one smooth closed body) or "auto".
    Returns (solid, report): report has faces, valid, closed, the measured deviation both ways, timings and the tier."""
    t0 = time.perf_counter()
    V, F = (T_or_VF if isinstance(T_or_VF, tuple) else weld(T_or_VF))
    if kind == "auto":
        kind = "shell" if segment(V, F).max() > 0 else "closed"
    from .craft import subd
    rep = {"tier": TIER_SURFACE, "kind": kind, "triangles": int(len(F)), "tolerance_mm": tol}
    if kind == "shell":
        cg = shell_cages(V, F, tol)
        t1 = time.perf_counter()
        solid = subd.trimmed_shell_solid(cg["outer"], cg["inner"], radius=cg["radius"])
        samples = shell_samples(cg)
        normals = None
        rep.update({"cage": [cg["n"], cg["n"]], "cages_tried": cg["tried"], "skin_max_mm": cg["skin_max_mm"], "skin_p995_mm": cg["skin_p995_mm"],
                    "skin_rms_mm": cg["skin_rms_mm"],
                    "fit_s": round(cg["fit_s"], 2), "solid_s": round(time.perf_counter() - t1, 2),
                    "smoothness": "C2 inside each skin (exact B-splines); the rim edges are creases, as in the mesh",
                    "cages": cg})
        known = cg["_skin"]
        rim = cg["_rim"]
    else:
        n = cage or 5
        Vq, Fq = subd.quad_sphere(n, 1.0)
        c = V.mean(0)
        ext = (V.max(0) - V.min(0)) / 2
        near = Nearest(V, F)
        # start on the mesh: each cage point pushed along its direction to the mesh's surface
        Vq = c + Vq * ext
        Vq, _ = near(Vq)
        cg = subd.Cage(Vq, Fq, levels=1)
        subd.fit_cage(cg, lambda S: near(S)[0], rounds=24, smooth=0.002)
        t1 = time.perf_counter()
        B = cg.patches()
        solid = subd.patches_solid(B)
        G = subd.patch_eval(B, 10)
        N = np.cross(np.gradient(G, axis=2), np.gradient(G, axis=1))
        samples = G.reshape(-1, 3)
        normals = (N / np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-12)).reshape(-1, 3)
        known, rim = None, None
        rep.update({"cage": [int(len(cg.V)), int(len(cg.F))], "extraordinary": cg.extraordinary(),
                    "solid_s": round(time.perf_counter() - t1, 2), "smoothness": subd.seam_angles(B, cg.F),
                    "cage_obj": cg})
    rep.update(verify_solid(solid, V, F, samples=samples, normals=normals, n=verify, known=known, extra=rim))
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    rep["within_tolerance"] = bool(rep["max_mm"] <= tol)
    return solid, rep


def _exact(solid, P) -> np.ndarray:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    out = []
    for p in P:
        ex = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex(), solid.wrapped)
        out.append(ex.Value() if ex.IsDone() else np.inf)
    return np.array(out)


def verify_solid(solid, V, F, samples=None, normals=None, n: int = 20000, exact: int = 300, known=None, extra=None,
                 seed: int = 0) -> dict:
    """Measured distance between a solid and a mesh, both ways (evidence: computed).
    Mesh to solid: where the fit already measured them (`known`: (vertex ids, distances to the fitted surfaces,
    each vertex's closest point found by Gauss-Newton), those distances for every vertex; the `exact` largest of them
    measured again by OCCT's exact point-to-solid distance, and the `extra` vertices (the rim) by OCCT too. Without
    `known`: n sampled vertices against the nearest of the solid's sample points (its tangent plane there, with
    `normals`), the largest `exact` of them by OCCT. Solid to mesh: the solid's sample points against the mesh's triangles (exact
    point-to-triangle distance)."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    if samples is None:
        vs, _ = solid.tessellate(0.02, 0.1)
        samples = np.array([(q.X, q.Y, q.Z) for q in vs])
    if known is not None:
        ids, d1 = known
        d1 = np.asarray(d1, float).copy()
        worst = np.argsort(-d1)[:exact]
        d1[worst] = np.maximum(d1[worst], _exact(solid, V[ids[worst]]))
        n_exact = len(worst)
    else:
        used = np.unique(F)
        pick = V[rng.choice(used, size=min(n, len(used)), replace=False)]
        d1, nb = cKDTree(samples).query(pick)
        if normals is not None:            # the nearest sample's tangent plane: close to the true distance
            d1 = np.minimum(d1, np.abs(np.einsum("ij,ij->i", pick - samples[nb], normals[nb])))
        worst = np.argsort(-d1)[:exact]
        d1[worst] = _exact(solid, pick[worst])
        n_exact = len(worst)
    if extra is not None and len(extra):
        ex = extra if len(extra) <= 600 else rng.choice(extra, size=600, replace=False)
        d1 = np.r_[d1, _exact(solid, V[ex])]
        n_exact += len(ex)
    S = samples if len(samples) <= 2 * n else samples[rng.choice(len(samples), size=2 * n, replace=False)]
    _, d2 = Nearest(V, F, k=8)(S)
    return {"faces": len(solid.faces()), "valid": bool(solid.is_valid), "closed": _closed(solid),
            "volume_mm3": round(float(solid.volume), 1), "mesh_to_solid_max_mm": round(float(d1.max()), 4),
            "mesh_to_solid_rms_mm": round(float(np.sqrt(np.mean(d1 ** 2))), 4),
            "solid_to_mesh_max_mm": round(float(d2.max()), 4), "max_mm": round(float(max(d1.max(), d2.max())), 4),
            "verified_points": {"mesh_vertices": int(len(d1)), "exact_occt": int(n_exact), "solid_points": int(len(S))},
            "evidence": "computed"}


def shell_samples(cg: dict, k: int = 400) -> np.ndarray:
    """Points on a fitted shell's three faces: both skins inside their trim circle, and across the rim."""
    from .craft import subd
    t = np.linspace(0, 2 * np.pi, 4 * k, endpoint=False)
    rr = np.linspace(0, 1, k // 2)[:, None] * cg["radius"]
    U = (0.5 + rr * np.cos(t)[None, :]).ravel()
    W = (0.5 + rr * np.sin(t)[None, :]).ravel()
    out = [subd.grid_eval(cg["outer"], U, W), subd.grid_eval(cg["inner"], U, W)]
    bu, bv = 0.5 + cg["radius"] * np.cos(t), 0.5 + cg["radius"] * np.sin(t)
    a, b = subd.grid_eval(cg["outer"], bu, bv), subd.grid_eval(cg["inner"], bu, bv)
    for f in np.linspace(0, 1, 7):
        out.append(a + f * (b - a))
    return np.vstack(out)


def _closed(solid) -> bool:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    try:
        fb = ShapeAnalysis_FreeBounds(solid.wrapped)
        ex = TopExp_Explorer(fb.GetClosedWires(), TopAbs_EDGE)
        return not ex.More() and BRepCheck_Analyzer(solid.wrapped).IsValid()
    except Exception:
        return bool(solid.is_valid)


# ── an in-house fixture: a helmet-like sculpted shell, as a mesh ──────────────────────────────────────────────────

def fixture_helmet(n: int = 225, wall: float = 3.0, seed: int = 7) -> np.ndarray:
    """A helmet-like thick shell as a triangle soup (m, 3, 3), about 4 n^2 triangles (n = 225: 200k): a sculpted
    dome (a sagittal crest, a brow ridge, cheek hollows, a lower edge that dips at the back), its inside offset by the
    wall along the surface normal, a flat rim between them. Rings round a crown point, triangulated irregularly and
    shuffled, so nothing of the grid it came from survives in the file. Made here, for tests and benchmarks."""
    rng = np.random.default_rng(seed)
    nr, nt = n // 2, 2 * n
    a, b, h = 130.0, 104.0, 150.0
    pmax = math.pi / 2 * 1.08

    def surf(ph, th):
        z0 = 18 * (1 - np.cos(th)) / 2 - 8 * np.cos(2 * th)          # lower at the back, a dip at the sides
        Z = z0 + (h - z0) * np.cos(np.minimum(ph, math.pi / 2)) - 22 * np.maximum(ph - math.pi / 2, 0)
        rad = np.sin(np.minimum(ph, math.pi / 2))
        cs, sn = np.cos(th), np.sin(th)
        P = np.stack([a * rad * np.sign(cs) * np.abs(cs) ** 0.9, b * rad * np.sign(sn) * np.abs(sn) ** 0.9, Z], axis=-1)
        crest = 6.0 * np.exp(-(P[..., 1] / 9.0) ** 2) * np.clip((P[..., 2] - 40) / 80, 0, 1)
        brow = 5.0 * np.exp(-((P[..., 2] - 85) / 10) ** 2) * np.clip(P[..., 0] / a, 0, 1) ** 2
        cheek = -4.0 * np.exp(-(((np.abs(P[..., 1]) - 70) / 18) ** 2 + ((P[..., 2] - 40) / 20) ** 2)) * \
            np.clip(P[..., 0] / a + 0.3, 0, 1)
        radial = P - np.array([0, 0, 40.0])
        radial /= np.linalg.norm(radial, axis=-1, keepdims=True)
        return P + (crest + brow + cheek)[..., None] * radial
    ph = pmax * (np.arange(1, nr + 1) / nr)
    th = np.linspace(-math.pi, math.pi, nt, endpoint=False)
    PH, TH = np.meshgrid(ph, th, indexing="ij")
    P = np.vstack([surf(np.array([0.0]), np.array([0.0])).reshape(1, 3), surf(PH, TH).reshape(-1, 3)])
    idx = 1 + np.arange(nr * nt).reshape(nr, nt)
    tri = [np.stack([np.zeros(nt, int), idx[0], np.roll(idx[0], -1)], 1)]
    a00, a01 = idx[:-1], np.roll(idx[:-1], -1, axis=1)
    a10, a11 = idx[1:], np.roll(idx[1:], -1, axis=1)
    flip = (rng.random(a00.shape) < 0.5)[..., None]
    t1 = np.where(flip, np.stack([a00, a10, a11], -1), np.stack([a00, a10, a01], -1))
    t2 = np.where(flip, np.stack([a00, a11, a01], -1), np.stack([a10, a11, a01], -1))
    tri += [t1.reshape(-1, 3), t2.reshape(-1, 3)]
    Fo = np.concatenate(tri)
    # outward orientation, then vertex normals from the triangles
    c = P.mean(0)
    fn, _ = tri_normals(P, Fo)
    if np.mean(np.einsum("ij,ij->i", fn, P[Fo].mean(1) - c)) < 0:
        Fo = Fo[:, ::-1]
    nrm = np.zeros_like(P)
    raw = np.cross(P[Fo[:, 1]] - P[Fo[:, 0]], P[Fo[:, 2]] - P[Fo[:, 0]])
    for k in range(3):
        np.add.at(nrm, Fo[:, k], raw)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    Q = P - wall * nrm
    m = len(P)
    ring_o = idx[-1]
    ring_i = ring_o + m
    rim = []
    for k in range(nt):
        a0, a1 = ring_o[k], ring_o[(k + 1) % nt]
        b0, b1 = ring_i[k], ring_i[(k + 1) % nt]
        rim += [[a0, b0, a1], [a1, b0, b1]]
    F = np.concatenate([Fo, Fo[:, ::-1] + m, np.array(rim)])
    Vall = np.vstack([P, Q])
    A, B, C = Vall[F[:, 0]], Vall[F[:, 1]], Vall[F[:, 2]]
    vol = np.einsum("ij,ij->i", A, np.cross(B, C)).sum()
    if vol < 0:
        F = F[:, ::-1]
    F = F[rng.permutation(len(F))]
    return Vall[F]


def fixture_bust(n: int = 80, seed: int = 3) -> np.ndarray:
    """A closed, smooth character-prop blob (a stylised head: nose, brow, cheek hollows, chin; the narrowest feature
    about 25 mm across) as a triangle soup (12 n^2 triangles)."""
    from .craft import subd
    Vq, Fq = subd.quad_sphere(n, 1.0)
    d = Vq
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    g = lambda c, w: np.exp(-np.sum(((d - np.asarray(c)) / np.asarray(w)) ** 2, axis=1))   # a bump on the sphere
    r = 60 + 7 * g((0.95, 0, 0.0), (0.3, 0.22, 0.3)) \
        + 4 * g((0.8, 0, 0.4), (0.3, 0.6, 0.18)) \
        - 3 * g((0.6, 0.65, -0.05), (0.3, 0.25, 0.3)) - 3 * g((0.6, -0.65, -0.05), (0.3, 0.25, 0.3)) \
        + 5 * g((0.55, 0, -0.75), (0.35, 0.4, 0.3))                  # nose, brow, cheek hollows, chin
    P = d * r[:, None] * np.array([1.0, 0.82, 1.18])
    T = []
    for f in Fq:
        T.append([f[0], f[1], f[2]])
        T.append([f[0], f[2], f[3]])
    T = np.array(T)
    return P[T]


# ── mesh bodies: sculpted detail kept as a mesh, CAD features cut exactly (manifold3d) ────────────────────────────

def has_manifold() -> bool:
    import importlib.util
    return importlib.util.find_spec("manifold3d") is not None


class MeshBody:
    """A closed triangle mesh with exact boolean features. Every operation is a manifold3d boolean, so the result
    stays closed (watertight) and the cut faces are exact (a cylinder cut is a cylinder's tessellation)."""

    def __init__(self, V, F):
        import manifold3d as m3
        self.m3 = m3
        mesh = m3.Mesh(vert_properties=np.asarray(V, np.float32), tri_verts=np.asarray(F, np.uint32))
        self.man = m3.Manifold(mesh)
        if self.man.status() != m3.Error.NoError:
            raise ValueError(f"The mesh is not a closed manifold body ({self.man.status()}); repair it first.")
        self.features: list[str] = []

    @classmethod
    def from_shape(cls, shape, tol: float = 0.02):
        """A build123d shape's tessellation as a mesh body (to combine CAD with a sculpt)."""
        vs, ts = shape.tessellate(tol, 0.1)
        V = np.array([(q.X, q.Y, q.Z) for q in vs])
        F = np.array(ts, dtype=np.int64)
        V, F = weld(V[F], 1e-6)
        return cls(V, F)

    def _tool(self, shape):
        return shape if isinstance(shape, MeshBody) else MeshBody.from_shape(shape)

    def cut(self, shape, name: str = "cut") -> "MeshBody":
        self.man = self.man - self._tool(shape).man
        self.features.append(name)
        return self

    def add(self, shape, name: str = "boss") -> "MeshBody":
        self.man = self.man + self._tool(shape).man
        self.features.append(name)
        return self

    def split(self, origin, normal) -> tuple["MeshBody", "MeshBody"]:
        n = np.asarray(normal, float)
        n = n / np.linalg.norm(n)
        off = float(np.dot(n, origin))
        a, b = self.man.split_by_plane(tuple(n), off)
        out = []
        for m in (b, a):
            mb = MeshBody.__new__(MeshBody)
            mb.m3, mb.man, mb.features = self.m3, m, list(self.features)
            out.append(mb)
        return out[0], out[1]

    def arrays(self):
        mesh = self.man.to_mesh()
        return np.asarray(mesh.vert_properties)[:, :3].astype(np.float64), np.asarray(mesh.tri_verts).astype(np.int64)

    def volume(self) -> float:
        return float(self.man.volume())

    def write_stl(self, path) -> None:
        from .recon.mesh import write_stl
        V, F = self.arrays()
        write_stl(path, V, F, "Form Studio mesh body")

    def report(self) -> dict:
        V, F = self.arrays()
        return {"tier": TIER_MESH, "triangles": int(len(F)), "volume_mm3": round(self.volume(), 1),
                "closed": self.man.status() == self.m3.Error.NoError and self.man.genus() >= 0,
                "genus": int(self.man.genus()), "features": self.features}
