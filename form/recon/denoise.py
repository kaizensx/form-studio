"""Scan noise: measure it, and give the program route a copy of the mesh with its vertices put back on their surfaces.

A CAD export puts every vertex exactly on its surface: the caps of a part share one height, a hole's top and bottom
rings lie on one cylinder. The program route (program.py) reads levels and walls from that exactness. A scan moves
every vertex a little (0.01 mm is a good scanner), so every vertex has its own height and no wall is straight.

This finds the surfaces anyway, with fits that use the tolerance and the measured noise instead of exact equality:

1. Pieces: triangles joined across edges that bend less than SMOOTH_DEG (a cap, a hole's wall, a chamfer).
2. Each piece is fitted with a plane, else a cylinder, cone, sphere or torus; a fit is kept when every vertex is within the
   tolerance and the residual is what noise gives (robust, from the median absolute deviation). A piece no single
   surface holds is split into planes grown from its largest facets (normals within GROW_DEG, vertices within a few
   noise widths), and what is left is fitted again.
3. Noise: 1.4826 x the median absolute distance of the vertices to their planes (to their cylinders and cones when the
   part has no planes). Below NOISE_MIN the mesh is exact and nothing is changed.
4. Design intent: a normal or axis within SNAP_DEG of a world axis is made that axis (and the fit redone about it);
   planes with one normal whose offsets agree within the noise become one plane.
5. Snap: each vertex moves to the nearest point on all the surfaces of its triangles (Gauss-Newton on the sum of the
   squared distances: a corner goes to where its planes meet), never farther than the tolerance and a few noise
   widths. A vertex no surface holds is left where it is.

The result is a working copy for reading the design: every candidate built from it is verified against the mesh as
given (pipeline.py). numpy and scipy only.
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import fit as fitmod
from .mesh import tri_normals

SMOOTH_DEG = 40.0
GROW_DEG = 8.0
SNAP_DEG = 0.5
NOISE_MIN = 2e-4          # mm: below this the mesh is exact (a CAD export written as float32 has about 1e-6)
MAX_MOVE_SIGMA = 6.0      # a vertex moves at most this many noise widths (and never past the tolerance)


def _adjacency(F):
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    tri = np.tile(np.arange(len(F)), 3)
    key = np.sort(he, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    o = np.argsort(inv, kind="stable")
    s = inv[o]
    nb = np.flatnonzero((s[1:] == s[:-1]) & (cnt[s[1:]] == 2))
    return tri[o][nb], tri[o][nb + 1]


def _components(n, a, b):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n))
    return connected_components(g, directed=False)[1]


def _mad(d):
    return 1.4826 * float(np.median(np.abs(d))) if len(d) else 0.0


def _pts(V, F, N, A, ts):
    """The vertices of the triangles ts and their normals (area-weighted over those triangles)."""
    vs, inv = np.unique(F[ts], return_inverse=True)
    acc = np.zeros((len(vs), 3))
    np.add.at(acc, inv.reshape(-1), np.repeat(N[ts] * A[ts, None], 3, axis=0))
    return V[vs], acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-300)[:, None]


def _fit(P, N, kinds=("plane", "cylinder", "cone", "sphere", "torus")):
    """Fits of each kind to the points P (normals N, one per point), simplest first: [(kind, prim)]."""
    out = []
    for k in kinds:
        try:
            pr = fitmod.fit_plane(P, N) if k == "plane" else fitmod._sane(fitmod.FITTERS[k](P, N))
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            pr = None
        if pr is not None and np.isfinite(pr.max):
            out.append((k, pr))
    return out


def _grow_planes(V, F, N, A, ts, nbrs, tol, sigma):
    """Split the triangles `ts` into planes grown from the largest facet left: a neighbour joins when its normal is
    within GROW_DEG of the plane's and its vertices within the allowance of it. Returns [(tris, prim)] and the rest."""
    left = set(ts.tolist())
    planes = []
    allow = min(tol, max(4 * sigma, 1e-4))
    cg = math.cos(math.radians(GROW_DEG))
    while left:
        seed = max(left, key=lambda t: A[t])
        n0, o0 = N[seed], V[F[seed]].mean(axis=0)
        mem, front = [seed], [seed]
        left.discard(seed)
        while front:
            t = front.pop()
            for u in nbrs[t]:
                if u in left and float(N[u] @ n0) > cg and float(np.abs((V[F[u]] - o0) @ n0).max()) <= allow:
                    left.discard(u)
                    mem.append(u)
                    front.append(u)
            if len(mem) in (4, 16, 64, 256, 1024):        # refit as it grows
                P = V[np.unique(F[mem])]
                pr = fitmod.fit_plane(P)
                n0 = pr.p["a"] if float(pr.p["a"] @ n0) >= 0 else -pr.p["a"]
                o0 = pr.p["o"]
        if len(mem) < 3:                                  # two facets of a curve are not a face
            continue
        mem = np.array(mem)
        P = V[np.unique(F[mem])]
        pr = fitmod.fit_plane(P)
        if float(pr.p["a"] @ n0) < 0:
            pr.p["a"] = -pr.p["a"]
        if pr.max <= allow:
            planes.append((mem, pr))
        else:
            left.update(mem.tolist()[1:])                 # give them back (the seed stays out: no endless loop)
    used = set(np.concatenate([m for m, _ in planes]).tolist()) if planes else set()
    rest = np.array([t for t in ts.tolist() if t not in used], dtype=np.int64)
    return planes, rest


def _snap_dir(a):
    """The world axis within SNAP_DEG of a (sign kept), or None."""
    k = int(np.argmax(np.abs(a)))
    if abs(a[k]) >= math.cos(math.radians(SNAP_DEG)):
        e = np.zeros(3)
        e[k] = math.copysign(1.0, a[k])
        return e
    return None


def _refit_on_axis(kind, P, pr, a):
    """The cylinder or cone `pr` refitted with its axis direction fixed to `a`: centre across the axis, radius (and
    half-angle) by least squares."""
    from scipy.optimize import least_squares
    u, w = fitmod._perp(a)
    o = pr.p["o"]
    if kind == "cylinder":
        def mk(x):
            return fitmod.Prim("cylinder", {"o": o + x[0] * u + x[1] * w, "a": a, "r": abs(x[2])})
        x0 = np.r_[0.0, 0.0, pr.p["r"]]
    else:
        def mk(x):
            return fitmod.Prim("cone", {"o": o + x[0] * u + x[1] * w, "a": a, "r": x[2], "half_angle": x[3]})
        sgn = 1.0 if float(pr.p["a"] @ a) >= 0 else -1.0
        x0 = np.r_[0.0, 0.0, pr.p["r"], sgn * pr.p["half_angle"]]
    try:
        sol = least_squares(lambda x: mk(x).dist(P), x0, method="lm", xtol=1e-12, ftol=1e-12, max_nfev=200)
        return fitmod._finish(mk(sol.x), P)
    except Exception:                                    # noqa: BLE001
        return None


def _coaxial(V, F, regions, tol):
    """Cylinders and cones whose axes are parallel and within the tolerance of each other share one axis line (a turned
    part has one axis): each is refitted about it, and keeps the shared axis only when it still holds its vertices."""
    rev = [i for i, (_, k, _) in enumerate(regions) if k in ("cylinder", "cone")]
    groups = []
    for i in rev:
        pr = regions[i][2]
        for g in groups:
            q = regions[g[0]][2]
            a = q.p["a"]
            if abs(float(pr.p["a"] @ a)) > 1 - 1e-9:
                d = pr.p["o"] - q.p["o"]
                if float(np.linalg.norm(d - (d @ a) * a)) <= tol:
                    g.append(i)
                    break
        else:
            groups.append([i])
    out = list(regions)
    for g in groups:
        if len(g) < 2:
            continue
        a = regions[g[0]][2].p["a"]
        w = np.array([len(regions[i][0]) for i in g], dtype=np.float64)
        o0 = regions[g[0]][2].p["o"]
        offs = np.array([(regions[i][2].p["o"] - o0) - ((regions[i][2].p["o"] - o0) @ a) * a for i in g])
        o = o0 + (offs * w[:, None]).sum(axis=0) / w.sum()
        for i in g:
            ts, k, pr = regions[i]
            P = V[np.unique(F[ts])]
            d = P - o
            s = d @ a
            rho = np.linalg.norm(d - s[:, None] * a, axis=1)
            if k == "cylinder":
                q = fitmod.Prim("cylinder", {"o": o.copy(), "a": a.copy(), "r": float(rho.mean())})
            else:
                if np.ptp(s) < 1e-9:
                    continue
                t, r0 = np.polyfit(s, rho, 1)
                q = fitmod.Prim("cone", {"o": o.copy(), "a": a.copy(), "r": float(r0), "half_angle": math.atan(t)})
            q = fitmod._finish(q, P)
            if q.max <= tol:
                out[i] = (ts, k, q)
    return out


def measure_and_snap(V, F, tol, deadline=None) -> tuple[np.ndarray, dict]:
    """(V', report). V' is V when the mesh has no measurable noise (report["noisy"] False) or nothing could be fitted.
    report["noise_mm"] is the measured noise (one standard deviation, across the surface)."""
    t0 = time.perf_counter()
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    N, A = tri_normals(V, F)
    t1, t2 = _adjacency(F)
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", N[t1], N[t2]), -1, 1)))
    sm = ang < SMOOTH_DEG
    lab = _components(len(F), t1[sm], t2[sm])
    pieces = {}
    for t, l in enumerate(lab.tolist()):
        pieces.setdefault(l, []).append(t)
    regions = []                                        # (tris, kind, prim)
    hard = []                                           # pieces no single surface held
    for ts in pieces.values():
        ts = np.array(ts)
        if len(ts) < 2:
            continue
        P, NP = _pts(V, F, N, A, ts)
        got = None
        for k, pr in _fit(P, NP):
            if pr.max <= tol:
                got = (k, pr)
                break
        if got is None:
            hard.append(ts)
        else:
            regions.append((ts, *got))
        if deadline is not None and time.perf_counter() > deadline:
            break
    # the noise, from the planes (unbiased); from the other surfaces when there are none
    def residuals(kinds):
        return np.concatenate([pr.dist(V[np.unique(F[ts])]) for ts, k, pr in regions if k in kinds] or [np.zeros(0)])
    d = residuals(("plane",))
    on = "planes"
    if len(d) < 12:
        d, on = residuals(("plane", "cylinder", "cone")), "planes, cylinders and cones"
    sigma = _mad(d)
    rep = {"noise_mm": round(sigma, 6), "measured_on": f"{len(d)} vertices on {on}", "noisy": bool(sigma > NOISE_MIN),
           "threshold_mm": NOISE_MIN}
    if not rep["noisy"] or not regions:
        rep["seconds"] = round(time.perf_counter() - t0, 3)
        return V, rep
    # the pieces no single surface held: planes grown inside them, then the rest fitted again
    if hard:
        nbrs = [[] for _ in range(len(F))]
        for a, b in zip(t1[sm].tolist(), t2[sm].tolist()):
            nbrs[a].append(b)
            nbrs[b].append(a)
        for ts in hard:
            if deadline is not None and time.perf_counter() > deadline:
                break
            planes, rest = _grow_planes(V, F, N, A, ts, nbrs, tol, sigma)
            regions += [(m, "plane", pr) for m, pr in planes]
            if len(rest) >= 2:
                sub = _components(len(F), *[x[np.isin(x, rest) & np.isin(y, rest)] for x, y in ((t1[sm], t2[sm]),
                                                                                                   (t2[sm], t1[sm]))])
                groups = {}
                for t in rest.tolist():
                    groups.setdefault(sub[t], []).append(t)
                for g in groups.values():
                    g = np.array(g)
                    if len(g) < 4:
                        continue
                    P, NP = _pts(V, F, N, A, g)
                    for k, pr in _fit(P, NP, ("cylinder", "cone", "sphere", "torus")):
                        if pr.max <= tol and pr.rms <= 2.5 * sigma:
                            regions.append((g, k, pr))
                            break
    # design intent: axes, and one plane per (normal, offset)
    snapped_dirs = 0
    out = []
    for ts, k, pr in regions:
        P = V[np.unique(F[ts])]
        e = _snap_dir(pr.p["a"]) if k in ("plane", "cylinder", "cone") else None
        if e is not None and not np.allclose(e, pr.p["a"], atol=0.0, rtol=0.0):
            if k == "plane":
                pr = fitmod._finish(fitmod.Prim("plane", {"o": P.mean(axis=0), "a": e}), P)
            else:
                pr2 = _refit_on_axis(k, P, pr, e)
                pr = pr2 if pr2 is not None and pr2.max <= tol else pr
            snapped_dirs += 1
        if pr.max <= tol:
            out.append((ts, k, pr))
    regions = _coaxial(V, F, out, tol)
    planes = [i for i, (_, k, _) in enumerate(regions) if k == "plane"]
    merged = 0
    for i in planes:
        for j in planes:
            if j <= i:
                continue
            ai, aj = regions[i][2].p["a"], regions[j][2].p["a"]
            if abs(float(ai @ aj)) < 1 - 1e-12:
                continue
            hi, hj = float(regions[i][2].p["o"] @ ai), float(regions[j][2].p["o"] @ ai)
            if abs(hi - hj) <= 3 * sigma:
                ni, nj = len(regions[i][0]), len(regions[j][0])
                h = (hi * ni + hj * nj) / (ni + nj)
                for q in (i, j):
                    pr = regions[q][2]
                    a = pr.p["a"]
                    pr.p["o"] = pr.p["o"] + (h * float(a @ ai) - float(pr.p["o"] @ a)) * a
                merged += 1
    # snap every vertex onto the surfaces of its triangles
    prims = [pr for _, _, pr in regions]
    reg_of = -np.ones(len(F), dtype=np.int64)
    for i, (ts, _, _) in enumerate(regions):
        reg_of[ts] = i
    vt = {}
    for t, (a, b, c) in enumerate(F.tolist()):
        r = int(reg_of[t])
        if r >= 0:
            for v in (a, b, c):
                vt.setdefault(v, set()).add(r)
    limit = min(float(tol), MAX_MOVE_SIGMA * sigma)
    V2 = V.copy()
    moved, refused, moves = 0, 0, []
    for v, rs in vt.items():
        rs = sorted(rs)
        x = V[v].copy()
        for _ in range(8):
            d = np.array([float(prims[r].dist(x[None])[0]) for r in rs])
            J = np.vstack([prims[r].normal(x[None])[0] for r in rs])
            step, *_ = np.linalg.lstsq(J, d, rcond=1e-6)
            x = x - step
            if float(np.abs(step).max()) < 1e-12:
                break
        mv = float(np.linalg.norm(x - V[v]))
        res = max(abs(float(prims[r].dist(x[None])[0])) for r in rs)
        if mv <= limit and res <= 1e-6:
            V2[v] = x
            moved += 1
            moves.append(mv)
        else:
            refused += 1
    kinds = {}
    for _, k, _ in regions:
        kinds[k] = kinds.get(k, 0) + 1
    covered = float(A[reg_of >= 0].sum() / max(A.sum(), 1e-300))
    rep.update({"surfaces": kinds, "surface_share_pct": round(100 * covered, 2), "axes_snapped": snapped_dirs,
                "planes_merged": merged, "vertices_moved": moved, "vertices_left": int(len(V) - moved),
                "vertices_refused": refused, "max_move_mm": round(max(moves), 6) if moves else 0.0,
                "rms_move_mm": round(float(np.sqrt(np.mean(np.square(moves)))), 6) if moves else 0.0,
                "move_limit_mm": round(limit, 6), "seconds": round(time.perf_counter() - t0, 3)})
    return V2, rep
