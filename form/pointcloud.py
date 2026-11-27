"""A surface from a scanner's points, so a point cloud (XYZ, PTS, LAS, E57, a PLY of vertices) can be triaged and
reconstructed like a mesh. numpy and scipy only; bounded in points and grid cells, so it takes seconds, not minutes.

    surface(P, N=None) -> (V, F, report)

The method is Hoppe et al., "Surface reconstruction from unorganized points" (SIGGRAPH 1992):

  1. normals: the direction in which each point's k nearest neighbours spread least (principal components), unless
     the file gives normals;
  2. one consistent side: the normals are made to agree along a minimum spanning tree of the neighbour graph whose
     edges cost 1 - |n_i . n_j| (neighbours with parallel normals first), starting from the point farthest from the
     centre with its normal pointing away from it;
  3. a signed distance on a grid around the points: for each grid point, the distance to the tangent planes of its
     nearest points (weighted by how near they are). Grid points farther than a few cells from any point have no
     value, so the surface stops where the scan stops: an open scan gives an open surface, never a guessed one;
  4. the zero level of that distance as triangles: marching tetrahedra (six per cube, so neighbouring cubes agree and
     the result has no cracks), vertices shared between neighbouring tetrahedra.

The report says how many points were used, the grid spacing (the finest detail the surface keeps), and the seconds.
The surface is an estimate from the points: triage measures it like any mesh, and its numbers are the surface's.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np

VERSION = 1
MAX_POINTS = 200_000          # more points are thinned out evenly (every point stays in the report)
MAX_CELLS = 160               # grid cells along the largest side at most
K_NORMAL = 12
K_SDF = 8
BAND = 2                      # cells around each point where the distance is computed
_CUBE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]])
_TETS = np.array([[0, 1, 3, 7], [0, 1, 5, 7], [0, 2, 3, 7], [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 6, 7]])


def _normals(P: np.ndarray, nb: np.ndarray) -> np.ndarray:
    Q = P[nb] - P[nb].mean(axis=1, keepdims=True)
    C = np.einsum("nki,nkj->nij", Q, Q)
    _w, v = np.linalg.eigh(C)
    return v[:, :, 0]


def _orient(P: np.ndarray, N: np.ndarray, nb: np.ndarray) -> np.ndarray:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import breadth_first_order, connected_components, minimum_spanning_tree
    n, k = nb.shape
    r = np.repeat(np.arange(n), k - 1)
    c = nb[:, 1:].reshape(-1)
    w = 1.0 - np.abs(np.einsum("ij,ij->i", N[r], N[c])) + 1e-6
    G = coo_matrix((w, (r, c)), shape=(n, n)).tocsr()
    G = G.maximum(G.T)
    T = minimum_spanning_tree(G)
    T = T.maximum(T.T)
    ncomp, lab = connected_components(T, directed=False)
    N = N.copy()
    centre = P.mean(axis=0)
    for comp in range(ncomp):
        idx = np.flatnonzero(lab == comp)
        seed = idx[np.argmax(np.linalg.norm(P[idx] - centre, axis=1))]
        if np.dot(N[seed], P[seed] - centre) < 0:
            N[seed] = -N[seed]
        order, pred = breadth_first_order(T, seed, directed=False, return_predecessors=True)
        for i in order[1:]:
            if np.dot(N[i], N[pred[i]]) < 0:
                N[i] = -N[i]
    return N


def surface(P: np.ndarray, N: np.ndarray | None = None, max_points: int = MAX_POINTS,
            max_cells: int = MAX_CELLS) -> tuple[np.ndarray, np.ndarray, dict]:
    """Triangles (V (n, 3), F (m, 3)) of the surface through the points P (mm), with a report."""
    from scipy.spatial import cKDTree
    t0 = time.perf_counter()
    P = np.asarray(P, dtype=np.float64)
    n_in = len(P)
    if n_in < 20:
        raise ValueError(f"{n_in} points are too few to make a surface from.")
    rng = np.random.default_rng(0)
    if n_in > max_points:
        keep = np.sort(rng.choice(n_in, size=max_points, replace=False))
        P = P[keep]
        N = None if N is None else np.asarray(N, dtype=np.float64)[keep]
    P, first = np.unique(P, axis=0, return_index=True)
    if N is not None:
        N = np.asarray(N, dtype=np.float64)[first]
    tree = cKDTree(P)
    d, nb = tree.query(P, k=min(K_NORMAL, len(P)))
    spacing = float(np.median(d[:, 1]))
    given = N is not None and len(N) == len(P) and np.all(np.isfinite(N))
    if given:
        L = np.linalg.norm(N, axis=1)
        given = bool(np.all(L > 1e-9))
    if given:
        N = N / np.linalg.norm(N, axis=1)[:, None]
    else:
        N = _orient(P, _normals(P, nb), nb)
    lo, hi = P.min(axis=0), P.max(axis=0)
    size = float((hi - lo).max())
    h = max(2.0 * spacing, size / max_cells, 1e-9)
    lo = lo - 3 * h
    # the cells near the points, and their corners
    cell = np.floor((P - lo) / h).astype(np.int64)
    off = np.stack(np.meshgrid(*[np.arange(-BAND, BAND + 1)] * 3, indexing="ij"), axis=-1).reshape(-1, 3)
    dims = np.floor((hi + 3 * h - lo) / h).astype(np.int64) + 2 * BAND + 2
    lin = lambda ijk: (ijk[..., 0] * dims[1] + ijk[..., 1]) * dims[2] + ijk[..., 2]   # noqa: E731
    base = np.unique(lin(cell))
    cells = np.unique((base[:, None] + lin(off)[None, :]).reshape(-1))
    ijk = np.stack([cells // (dims[1] * dims[2]), (cells // dims[2]) % dims[1], cells % dims[2]], axis=1)
    corners = ijk[:, None, :] + _CUBE[None, :, :]                       # (c, 8, 3)
    gid, vloc = np.unique(lin(corners).reshape(-1), return_inverse=True)
    vloc = vloc.reshape(-1, 8)
    G = np.stack([gid // (dims[1] * dims[2]), (gid // dims[2]) % dims[1], gid % dims[2]], axis=1) * h + lo
    dd, nn = tree.query(G, k=min(K_SDF, len(P)))
    sig = 1.5 * h
    wgt = np.exp(-(dd / sig) ** 2)
    dist = np.einsum("gki,gki->gk", G[:, None, :] - P[nn], N[nn])
    f = (wgt * dist).sum(axis=1) / np.maximum(wgt.sum(axis=1), 1e-300)
    valid = dd[:, 0] < 3.0 * h                  # beyond this the scan has no points: no surface
    # marching tetrahedra
    tv = vloc[:, _TETS].reshape(-1, 4)                                    # (t, 4) local vertex ids
    tv = tv[valid[tv].all(axis=1)]
    inside = f[tv] < 0
    code = inside @ np.array([1, 2, 4, 8])
    tv, inside, code = tv[(code > 0) & (code < 15)], inside[(code > 0) & (code < 15)], code[(code > 0) & (code < 15)]
    nv = len(G)
    tris, outward = [], []
    for c in range(1, 15):
        sel = code == c
        if not sel.any():
            continue
        t = tv[sel]
        ins = [i for i in range(4) if c >> i & 1]
        out = [i for i in range(4) if not c >> i & 1]
        go = G[t[:, out]].mean(axis=1) - G[t[:, ins]].mean(axis=1)       # from inside to outside
        if len(ins) in (1, 3):
            lone, rest = (ins[0], out) if len(ins) == 1 else (out[0], ins)
            e = [(t[:, lone], t[:, r]) for r in rest]
            tris.append(np.stack([_ek(a, b, nv) for a, b in e], axis=1))
            outward.append(go)
        else:
            a, b = ins
            c1, d1 = out
            e = [_ek(t[:, a], t[:, c1], nv), _ek(t[:, a], t[:, d1], nv), _ek(t[:, b], t[:, d1], nv),
                 _ek(t[:, b], t[:, c1], nv)]
            tris.append(np.stack([e[0], e[1], e[2]], axis=1))
            tris.append(np.stack([e[0], e[2], e[3]], axis=1))
            outward += [go, go]
    if not tris:
        raise ValueError("No surface could be made from the points.")
    K = np.concatenate(tris)
    uk, Fl = np.unique(K.reshape(-1), return_inverse=True)
    F = Fl.reshape(-1, 3).astype(np.int64)
    ea, eb = uk // nv, uk % nv
    fa, fb = f[ea], f[eb]
    s = fa / (fa - fb)
    V = G[ea] + s[:, None] * (G[eb] - G[ea])
    # each triangle faces where the distance grows (out of the body)
    a, b, c3 = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    nrm = np.cross(b - a, c3 - a)
    flip = np.einsum("ij,ij->i", nrm, np.concatenate(outward)) < 0
    F[flip] = F[flip][:, ::-1]
    # vertices that met on a grid point (its distance was zero) are one vertex; the triangles between them go
    from .recon.mesh import weld
    V, F, _w = weld(V[F], 1e-6 * h)
    rep = {"points_in_file": int(n_in), "points_used": int(len(P)), "normals": "from the file" if given else
           "estimated (principal components, made consistent along a spanning tree)",
           "point_spacing_mm": round(spacing, 4), "grid_mm": round(h, 4), "triangles": int(len(F)),
           "method": "signed distance to the points' tangent planes, marching tetrahedra (Hoppe et al. 1992)",
           "seconds": round(time.perf_counter() - t0, 2),
           "note": f"The surface is an estimate from the points, with detail down to about {h:.3g} mm; where the "
                   "scan has no points the surface stays open."}
    return V, F, rep


def _ek(a: np.ndarray, b: np.ndarray, nv: int) -> np.ndarray:
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    return lo * nv + hi


def _cache_root() -> Path:
    import os
    try:
        from . import config
        data = Path(config.load()["data"]["dir"])
    except Exception:                                  # noqa: BLE001 - outside a configured Form Studio: the default folder
        data = Path(os.environ.get("FORM_DATA") or Path.home() / "FORM").expanduser()
    return data / ".cache" / "pointcloud"


def surface_cached(P: np.ndarray, N, sha256: str) -> tuple[np.ndarray, np.ndarray, dict]:
    """surface(), kept by the file's checksum so a second look at the same scan is instant."""
    import json
    key = hashlib.sha256(f"{VERSION}|{MAX_POINTS}|{MAX_CELLS}|{sha256}".encode()).hexdigest()[:24]
    root = _cache_root()
    f = root / f"{key}.npz"
    try:
        z = np.load(f, allow_pickle=False)
        return z["V"], z["F"], json.loads(str(z["rep"]))
    except (OSError, ValueError, KeyError):
        pass
    V, F, rep = surface(P, N)
    try:
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / f"{key}.tmp.npz"
        np.savez(tmp, V=V, F=F, rep=np.array(json.dumps(rep)))
        tmp.replace(f)
    except OSError:
        pass
    return V, F, rep
