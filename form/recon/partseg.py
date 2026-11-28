"""Split one mesh into parts at its concave creases, and close each part. numpy and scipy only.

A generated object (a lamp, a toy, a bracket from a picture) arrives as one welded surface; its parts meet in
concave creases (the neck under a lamp shade, the joint of a handle). This splits it there:

1. Separate bodies are separate parts.
2. Inside a body, an edge is a cut when the surface folds inward across it (the far vertex of one triangle lies on
   the outside of the other's plane) by more than CONCAVE_DEG. The triangles joined across every other edge are one
   region (connected components).
3. Regions under MIN_SHARE of the area are merged into the neighbour they share the longest border with, until at
   most MAX_PARTS are left.
4. Each part's open borders are closed by a fan of triangles to the border's centroid, so every part is a closed
   mesh the reconstruction routes take.

The cut is a heuristic (a convexity criterion, as in approximate convex decomposition); the result lists every
part's share of the area and the length of its crease, so a reader sees what it was split on.
"""
from __future__ import annotations

import numpy as np

CONCAVE_DEG = 28.0
MIN_SHARE = 0.04
MAX_PARTS = 8


def _adjacency(F: np.ndarray):
    """(edge vertex pairs (k, 2), the two triangles of each interior edge (k, 2); -1 where an edge has one)."""
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    t = np.tile(np.arange(len(F)), 3)
    key = np.sort(e, axis=1)
    uniq, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    order = np.argsort(inv, kind="stable")
    tris = np.full((len(uniq), 2), -1, dtype=np.int64)
    first = np.searchsorted(inv[order], np.arange(len(uniq)))
    tris[:, 0] = t[order[first]]
    two = cnt >= 2
    tris[two, 1] = t[order[first[two] + 1]]
    return uniq, tris


def _concave(V, F, edges, tris, N):
    """Fold angle in degrees across each interior edge, positive where the surface folds inward (concave)."""
    a, b = tris[:, 0], tris[:, 1]
    ok = b >= 0
    ang = np.zeros(len(edges))
    n1, n2 = N[a[ok]], N[b[ok]]
    ang_ok = np.degrees(np.arccos(np.clip((n1 * n2).sum(1), -1, 1)))
    Fb = F[b[ok]]
    e = edges[ok]
    # the vertex of triangle b that is not on the edge
    far = np.where((Fb[:, 0] != e[:, 0]) & (Fb[:, 0] != e[:, 1]), Fb[:, 0],
                   np.where((Fb[:, 1] != e[:, 0]) & (Fb[:, 1] != e[:, 1]), Fb[:, 1], Fb[:, 2]))
    side = ((V[far] - V[e[:, 0]]) * n1).sum(1)
    ang[ok] = np.where(side > 1e-9, ang_ok, -ang_ok)
    return ang, ok


def split(V: np.ndarray, F: np.ndarray, concave_deg: float = CONCAVE_DEG, min_share: float = MIN_SHARE,
          max_parts: int = MAX_PARTS) -> list[dict]:
    """[{"V", "F", "area_share", "crease_mm", "tris"}] for a welded mesh; one entry when nothing splits it."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    cr = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    area = np.linalg.norm(cr, axis=1) / 2
    N = cr / np.maximum(2 * area, 1e-300)[:, None]
    edges, tris = _adjacency(F)
    ang, inner = _concave(V, F, edges, tris, N)
    keep = inner & (ang < concave_deg)
    a, b = tris[keep, 0], tris[keep, 1]
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(F), len(F)))
    n, label = connected_components(g, directed=False)
    elen = np.linalg.norm(V[edges[:, 0]] - V[edges[:, 1]], axis=1)
    total = area.sum()

    def borders(label):
        """{(region i, region j): shared border length} over interior edges."""
        out = {}
        la, lb = label[tris[inner, 0]], label[tris[inner, 1]]
        for i, j, L in zip(la, lb, elen[inner]):
            if i != j:
                k = (min(i, j), max(i, j))
                out[k] = out.get(k, 0.0) + L
        return out

    while True:
        ids, label = np.unique(label, return_inverse=True)
        share = np.bincount(label, weights=area) / total
        if len(share) <= 1:
            break
        small = int(np.argmin(share))
        if share[small] >= min_share and len(share) <= max_parts:
            break
        nb = {k: L for k, L in borders(label).items() if small in k}
        if not nb:                                    # a separate small body: keep it as its own part
            if len(share) <= max_parts:
                break
            nb = {(small, int(np.argsort(share)[1])): 0.0}
        other = max(nb, key=nb.get)
        tgt = other[0] if other[1] == small else other[1]
        label = np.where(label == small, tgt, label)
    ids, label = np.unique(label, return_inverse=True)
    crease = borders(label)
    parts = []
    for r in range(len(ids)):
        sel = np.where(label == r)[0]
        sub = F[sel]
        used, local = np.unique(sub, return_inverse=True)
        Vp, Fp = V[used], local.reshape(-1, 3)
        Vp, Fp = close_holes(Vp, Fp)
        parts.append({"V": Vp, "F": Fp, "tris": sel, "area_share": round(float(area[sel].sum() / total), 4),
                      "crease_mm": round(float(sum(L for k, L in crease.items() if r in k)), 2)})
    parts.sort(key=lambda p: -p["area_share"])
    return parts


def close_holes(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Close every open border loop with a fan to its centroid, oriented like the surface around it."""
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = np.sort(e, axis=1)
    uniq, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    open_e = e[cnt[inv.ravel()] == 1]                  # directed as in their triangle
    if not len(open_e):
        return V, F
    nxt = {int(a): int(b) for a, b in open_e}
    seen, newV, newF = set(), [V], [F]
    count = len(V)
    for start in list(nxt):
        if start in seen:
            continue
        loop, v = [], start
        while v not in seen and v in nxt:
            seen.add(v)
            loop.append(v)
            v = nxt[v]
        if len(loop) < 3:
            continue
        c = V[loop].mean(axis=0)
        newV.append(c[None])
        ci = count
        count += 1
        # the border runs one way in its triangles; the cap runs the other way so its edges pair with them
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            newF.append(np.array([[b, a, ci]]))
    return np.vstack(newV), np.vstack(newF)
