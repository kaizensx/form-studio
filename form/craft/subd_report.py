"""How close a subdivision cage's CAD is to its true limit surface: measured, never assumed.

    from form.craft import subd, subd_report
    cage = subd.Cage(V, F, levels=1, creases={(3, 7): float("inf")})
    rep = subd_report.report(cage)          # deviation, seams, BRepCheck, faces, STEP round trip

deviation(cage) subdivides the cage `level` more times (Catmull-Clark with the same crease and boundary rules, 6 by
default), pushes every vertex to its exact limit position and measures each one's distance to the patch it lies in
(closest point within that patch, from its subdivision parameters): max and RMS in mm. Where every patch is regular the
CAD is the limit surface itself and the numbers are rounding; at extraordinary vertices, darts and irregular crease
sectors the patches are Loop and Schaefer's approximation (ACC) and the numbers are the measured error. A result is
called exact only when every patch is regular.

fixtures() returns the reference cages the tests and the bench use (a regular torus, a cube-sphere, a genus-2 slab, a
lens with a sharp equator, the same with a semi-sharp one, a cube-sphere with a sharp rim and an open tube).
"""
from __future__ import annotations

import math
import os
import tempfile

import numpy as np

from . import subd

LEVEL = 6
CHUNK = 200_000
MAX_QUADS = 1_600_000          # the reference mesh's size cap: a finer cage is measured at fewer extra levels


# ── the reference: the cage subdivided `level` times, at its limit, with every vertex's patch parameters ─────────

def limit_mesh(cage, level: int = LEVEL) -> dict:
    """The limit surface sampled by `level` Catmull-Clark steps of the cage's quads: points P (n, 3), the patch
    (cage face) each lies in and its (u, v) in that patch (u from corner a to b, v from a to d)."""
    V, F = cage.V, np.asarray(cage.F)
    sh = subd._sharp_arrays(cage.creases)
    m = len(F)
    base = np.arange(m)
    corners = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    UV = np.repeat(corners[None], m, axis=0)                     # (m, 4, 2) parameters of each quad's corners
    for _ in range(int(level)):
        V, Fn, sh, parent = subd._cc_step(V, F, sh)
        # child k of quad q: [corner k, edge (k, k+1), centre, edge (k-1, k)]
        c = UV.mean(1)
        nxt, prv = np.roll(UV, -1, axis=1), np.roll(UV, 1, axis=1)
        child = np.stack([UV, (UV + nxt) / 2, np.repeat(c[:, None], 4, 1), (UV + prv) / 2], axis=2)   # (q, k, 4, 2)
        UV = child.reshape(-1, 4, 2)
        base = np.repeat(base, 4)
        F = Fn
    P = subd.limit_points(V, F, sh)
    first = np.unique(F.ravel(), return_index=True)
    vid, pos = first
    q, k = pos // 4, pos % 4
    return {"P": P[vid], "base": base[q], "uv": UV[q, k], "quads": len(F)}


def _project(B: np.ndarray, base: np.ndarray, uv: np.ndarray, P: np.ndarray, iters: int = 6) -> np.ndarray:
    """Distance from each P to its patch: Gauss-Newton from (u, v), held inside the patch (an upper bound where the
    closest point is on the neighbour)."""
    u, v = uv[:, 0].copy(), uv[:, 1].copy()
    Pb = B[base]
    for _ in range(iters + 1):
        bu, bv = subd.bernstein(u), subd.bernstein(v)
        du, dv = _dbern_vec(u), _dbern_vec(v)
        S = np.einsum("nr,nc,nrck->nk", bv, bu, Pb)
        Su = np.einsum("nr,nc,nrck->nk", bv, du, Pb)
        Sv = np.einsum("nr,nc,nrck->nk", dv, bu, Pb)
        r = P - S
        a, b, c = (Su * Su).sum(1), (Su * Sv).sum(1), (Sv * Sv).sum(1)
        e, f = (Su * r).sum(1), (Sv * r).sum(1)
        det = a * c - b * b
        ok = np.abs(det) > 1e-24
        dU = np.where(ok, (c * e - b * f) / np.where(ok, det, 1), 0)
        dV = np.where(ok, (a * f - b * e) / np.where(ok, det, 1), 0)
        u = np.clip(u + np.clip(dU, -0.1, 0.1), 0, 1)
        v = np.clip(v + np.clip(dV, -0.1, 0.1), 0, 1)
    bu, bv = subd.bernstein(u), subd.bernstein(v)
    return np.linalg.norm(P - np.einsum("nr,nc,nrck->nk", bv, bu, Pb), axis=1)


def _dbern_vec(t: np.ndarray) -> np.ndarray:
    s = 1 - t
    return np.stack([-3 * s * s, 3 * s * s - 6 * s * t, 6 * s * t - 3 * t * t, 3 * t * t], axis=1)


def deviation(cage, level: int = LEVEL, B: np.ndarray | None = None) -> dict:
    """Measured distance between the CAD patches and the true Catmull-Clark limit surface (level-`level` limit
    points; a cage with more than MAX_QUADS / 4**level quads is measured at fewer levels, and the result says which):
    max and RMS mm, the cage size (largest bounding-box side, mm) and max per 100 mm of it, and the claim
    that may be made: "exact" only when every patch is a regular B-spline patch."""
    B = cage.patches() if B is None else B
    asked = int(level)
    level = max(2, min(asked, int(math.log(MAX_QUADS / max(len(cage.F), 1), 4))))
    L = limit_mesh(cage, level)
    P, base, uv = L["P"], L["base"], L["uv"]
    d = np.concatenate([_project(B, base[i:i + CHUNK], uv[i:i + CHUNK], P[i:i + CHUNK])
                        for i in range(0, len(P), CHUNK)])
    size = float(np.ptp(P, axis=0).max())
    mx, rms = float(d.max()), float(math.sqrt(float(np.mean(d * d))))
    exact = cage.exact
    claim = ("exact: every patch is a regular bicubic B-spline patch of the limit surface" if exact else
             f"approximate at {cage.irregular()} irregular point(s) (Loop-Schaefer ACC): measured max "
             f"{mx:.3g} mm, RMS {rms:.3g} mm against the level-{level} limit")
    return {"max_mm": mx, "rms_mm": rms, "p99_mm": float(np.percentile(d, 99)), "size_mm": size,
            "max_per_100mm": mx * 100.0 / max(size, 1e-9), "points": int(len(P)), "level": int(level),
            "level_asked": asked, "levels_from_input": int(level + cage.levels),
            "exact": bool(exact), "irregular_points": cage.irregular(), "extraordinary": cage.extraordinary(),
            "claim": claim}


def step_roundtrip(solid) -> dict:
    """Write the solid to STEP, read it back: valid, volumes and their relative difference."""
    from build123d import export_step, import_step
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        export_step(solid, path)
        back = import_step(path)
        sols = back.solids()
        v0 = float(solid.volume)
        v1 = float(sum(s.volume for s in sols))
        return {"valid": bool(back.is_valid) and len(sols) == 1, "solids": len(sols), "volume_mm3": v0,
                "reimport_volume_mm3": v1, "rel_diff": abs(v1 - v0) / max(abs(v0), 1e-12),
                "bytes": os.path.getsize(path)}
    finally:
        os.unlink(path)


def report(cage, solid=None, level: int = LEVEL, step: bool = True, merge: bool = True, close: str = "cap",
           thickness: float | None = None) -> dict:
    """Everything measured about a cage's CAD: deviation from the limit surface, seam angles over smooth borders,
    BRepCheck validity, face counts (merged and one per patch, as before), and the STEP round trip."""
    B = cage.patches()
    out = {"cage": {"points": int(len(cage.V)), "quads": int(len(cage.F)), "levels": cage.levels,
                    "creases": len(cage.creases), "open": cage.is_open(), "regions": list(cage.region_names)}}
    out["deviation"] = deviation(cage, level, B)
    out["seams"] = cage.seams(B)
    if solid is None:
        solid = cage.solid(merge=merge, close=close, thickness=thickness)
    meta = cage.face_meta()
    out["brep"] = {"valid": bool(solid.is_valid), "solids": len(solid.solids()), "faces": len(solid.faces()),
                   "faces_one_per_patch": int(len(cage.F)), "bspline_faces": sum(m["kind"] == "bspline" for m in meta),
                   "bezier_faces": sum(m["kind"] == "bezier" for m in meta), "volume_mm3": float(solid.volume)}
    if step:
        out["step"] = step_roundtrip(solid)
    return out


# ── reference cages ───────────────────────────────────────────────────────────────────────────────────────────────

def torus_cage(n: int = 12, m: int = 8, R: float = 40.0, r: float = 12.0):
    """A closed quad cage in which every vertex has four quads round it (no extraordinary vertex)."""
    V = []
    for i in range(n):
        for j in range(m):
            a, b = 2 * math.pi * i / n, 2 * math.pi * j / m
            V.append(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
    F = [[i * m + j, ((i + 1) % n) * m + j, ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m]
         for i in range(n) for j in range(m)]
    return np.array(V), F


def tube_cage(n: int = 12, rings: int = 5, r: float = 30.0, h: float = 80.0):
    """An open tube (no caps): every border vertex has two quads, so the whole skin is regular."""
    V = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), h * k / (rings - 1))
         for k in range(rings) for i in range(n)]
    F = [[k * n + i, k * n + (i + 1) % n, (k + 1) * n + (i + 1) % n, (k + 1) * n + i]
         for k in range(rings - 1) for i in range(n)]
    return np.array(V), F


def equator_edges(V: np.ndarray, F, tol: float = 1e-6) -> list:
    """Cage edges whose two ends are both on z = 0."""
    out = set()
    for f in F:
        for i in range(len(f)):
            a, b = int(f[i]), int(f[(i + 1) % len(f)])
            if abs(V[a][2]) < tol and abs(V[b][2]) < tol:
                out.add(subd._ekey(a, b))
    return sorted(out)


def region_border(F, faces) -> list:
    """Edges of the given faces that only one of them has (the region's outline: a crease or a split line)."""
    count: dict = {}
    for i in faces:
        f = F[i]
        for k in range(len(f)):
            e = subd._ekey(f[k], f[(k + 1) % len(f)])
            count[e] = count.get(e, 0) + 1
    return sorted(e for e, c in count.items() if c == 1)


def fixtures() -> dict:
    """{name: (cage, hole)}: reference cages (about 100 mm) and a hole (centre, axis, diameter) through each."""
    out = {}
    V, F = torus_cage(12, 8, 40, 12)
    out["torus_regular"] = (subd.Cage(V, F), ((40.0, 0.0, 0.0), (0, 0, 1), 8.0))
    V, F = subd.quad_sphere(3, 50)
    out["cube_sphere"] = (subd.Cage(V, F, levels=1), ((0.0, 0.0, 0.0), (0, 0, 1), 12.0))
    V, F = subd.voxel_cage({(i, j, 0) for i in range(5) for j in range(3)} - {(1, 1, 0), (3, 1, 0)}, 22)
    out["genus2"] = (subd.Cage(V, F, levels=3), ((55.0, 33.0, 11.0), (0, 0, 1), 6.0))
    V, F = subd.quad_sphere(2, 50)
    eq = equator_edges(V, F)
    top = [i for i, f in enumerate(F) if all(V[x][2] > 1e-6 for x in f)]
    out["lens_sharp"] = (subd.Cage(V, F, levels=2, creases=eq, regions={"top": top}),
                         ((0.0, 0.0, 0.0), (1, 0, 0), 12.0))
    out["lens_semisharp"] = (subd.Cage(V, F, creases={e: 2.0 for e in eq}), ((0.0, 0.0, 0.0), (1, 0, 0), 12.0))
    lid = [i for i, f in enumerate(F) if all(V[x][2] > 0.5 * 50 for x in f)]
    out["rim_sharp"] = (subd.Cage(V, F, levels=2, creases=region_border(F, lid), regions={"lid": lid}),
                        ((0.0, 0.0, 0.0), (0, 0, 1), 12.0))
    V, F = tube_cage(12, 5, 30, 90)
    out["tube_open"] = (subd.Cage(V, F), ((0.0, 0.0, 45.0), (1, 0, 0), 10.0))
    return out
