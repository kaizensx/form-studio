"""The export ladder: an STL of a valid CAD solid comes out closed, or says exactly why it is not.

OCCT's mesher can leave a valid solid with an open STL: a small or sliver face that gets no triangles, faces whose
edge polygons do not meet (cracks, T-junctions), triangles flipped against their neighbours. write_stl (form/kernel.py)
meshes each solid of the shape on its own and climbs these rungs, per solid, until the solid's mesh is closed:

    mesh      the asked-for settings
    finer     finer settings for the whole solid, then for the faces that got no triangles
    sewn      the solid's faces sewn (BRepBuilderAPI_Sewing) and meshed again
    welded    vertices closer than a small distance merged (closes cracks between faces)
    repaired  last resort: duplicate faces dropped, orientation made consistent, holes filled from their own edges

Each rung states the most the mesh can be from the CAD surface (`deviation_mm`): the mesher's chord deflection, plus
the sewing or welding distance, plus, for a filled hole, how far the hole's edge is from a plane (the fill is flat).
The climb has a time budget; a solid still open when it runs out, or after the last rung, is written as it is with
the cause named. "Closed" is the same screen as form/mesh_audit.py: no open, non-manifold, flipped or duplicate edges
once vertices are welded at 1e-6 mm.

A shape of several solids (an assembly in its assembled pose) is closed when each solid is: solids that touch share
faces and edges, which is not a defect. The STL then gets a sidecar, `<name>.stl.parts.json`, with each solid's
triangle count, and form/mesh_audit.py audits each solid's triangles as its own mesh.

numpy only at import; OCCT is imported inside the functions that need it (they run in the kernel worker).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

WELD = 1e-6                     # mm: the audit's weld grid
TRACE = bool(__import__("os").environ.get("FORM_MESHCLOSE_TRACE"))   # each rung's result on stderr
PARTS_SUFFIX = ".parts.json"


# ---- mesh topology (numpy) -------------------------------------------------------------------------------------
def weld(V: np.ndarray, grid: float = WELD) -> tuple[np.ndarray, np.ndarray]:
    """Triangles (n, 3, 3) -> (points (m, 3), faces (n, 3)) with vertices welded on a grid."""
    if not len(V):
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    k = np.round(V.reshape(-1, 3) / grid).astype(np.int64)
    _, first, inv = np.unique(k, axis=0, return_index=True, return_inverse=True)
    return V.reshape(-1, 3)[first], inv.reshape(-1, 3)


def _labels(n: int, pairs: np.ndarray) -> np.ndarray:
    """Connected-component labels of n items joined by pairs (min-label propagation, numpy only)."""
    lab = np.arange(n)
    if not len(pairs):
        return lab
    a, b = pairs[:, 0], pairs[:, 1]
    while True:
        m = np.minimum(lab[a], lab[b])
        new = lab.copy()
        np.minimum.at(new, a, m)
        np.minimum.at(new, b, m)
        new = new[new]                         # pointer jumping
        if np.array_equal(new, lab):
            return lab
        lab = new


def cluster(V: np.ndarray, eps: float) -> tuple[np.ndarray, np.ndarray]:
    """Like weld, but vertices closer than about eps merge even across grid cells (two offset grids). Merged
    vertices move to their cluster's mean: at most eps * sqrt(3) * 2 for a chain, stated by the caller."""
    P, F = weld(V)
    n = len(P)
    pairs = []
    for off in (0.0, 0.5):
        k = np.floor(P / eps + off).astype(np.int64)
        _, inv = np.unique(k, axis=0, return_inverse=True)
        order = np.argsort(inv, kind="stable")
        g = inv[order]
        same = np.nonzero(g[1:] == g[:-1])[0]
        pairs.append(np.stack([order[same], order[same + 1]], axis=1))
    lab = _labels(n, np.concatenate(pairs))
    u, inv = np.unique(lab, return_inverse=True)
    Q = np.zeros((len(u), 3))
    np.add.at(Q, inv, P)
    Q /= np.bincount(inv)[:, None]
    return Q, inv[F]


def stitch(P: np.ndarray, F: np.ndarray, eps: float, passes: int = 3) -> tuple[np.ndarray, int]:
    """Close cracks where two faces' edge polygons do not match (T-junctions): a vertex of one side that lies on an
    open edge of the other side, within eps, splits that edge's triangle, so both sides share vertices. No vertex
    moves; the split points are on the triangle's edge to within eps (the deviation). Returns (faces, splits)."""
    total = 0
    for _ in range(passes):
        E, inv, c = _edges(F)
        open_e = np.nonzero(c[inv] == 1)[0]
        if not len(open_e):
            break
        n = len(F)
        tri = np.tile(np.arange(n), 3)[open_e]
        A, B = E[open_e, 0], E[open_e, 1]
        verts = np.unique(np.concatenate([A, B]))
        Q = P[verts]
        splits: dict = {}
        for s0 in range(0, len(open_e), 512):
            a, b = P[A[s0:s0 + 512]], P[B[s0:s0 + 512]]
            d = b - a
            L2 = np.einsum("ij,ij->i", d, d)
            t = np.einsum("kij,ij->ki", Q[:, None, :] - a[None], d) / np.where(L2 > 0, L2, 1)[None]
            foot = a[None] + t[..., None] * d[None]
            dist = np.linalg.norm(Q[:, None, :] - foot, axis=2)
            ok = (dist <= eps) & (t > 1e-9) & (t < 1 - 1e-9)
            ok &= (verts[:, None] != A[s0:s0 + 512][None]) & (verts[:, None] != B[s0:s0 + 512][None])
            for qi, ei in zip(*np.nonzero(ok)):
                e = s0 + int(ei)
                splits.setdefault(e, []).append((float(t[qi, ei]), int(verts[qi])))
        if not splits:
            break
        by_tri: dict = {}
        for e, pts in splits.items():
            by_tri.setdefault(int(tri[e]), []).append((int(A[e]), int(B[e]), sorted(pts)))
        keep = np.ones(n, bool)
        new = []
        for t_i, cuts in by_tri.items():
            keep[t_i] = False
            polys = [list(F[t_i])]
            for a, b, pts in cuts:              # split every triangle of the fan that still has edge a-b
                nxt = []
                for tr in polys:
                    k = next((j for j in range(3) if tr[j] == a and tr[(j + 1) % 3] == b), None)
                    if k is None:
                        nxt.append(tr)
                        continue
                    o = tr[(k + 2) % 3]
                    chain = [a] + [v for _, v in pts] + [b]
                    nxt += [[chain[j], chain[j + 1], o] for j in range(len(chain) - 1)]
                polys = nxt
            new += polys
            total += sum(len(p) for _, _, p in cuts)
        F = np.concatenate([F[keep], np.array(new, dtype=F.dtype)])
    return F, total


def _drop_degenerate(F: np.ndarray) -> np.ndarray:
    return F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 2] != F[:, 0])]


def _flat(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Triangles with three distinct corners and no area (collinear), by the audit's own test on float32 corners."""
    if not len(F):
        return np.zeros(0, bool)
    Q = P.astype(np.float32).astype(np.float64)
    c = np.cross(Q[F[:, 1]] - Q[F[:, 0]], Q[F[:, 2]] - Q[F[:, 0]])
    return np.einsum("ij,ij->i", c, c) <= WELD ** 4


def _drop_flat(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    return F[~_flat(P, F)]


def _drop_duplicates(F: np.ndarray) -> np.ndarray:
    _, keep = np.unique(np.sort(F, axis=1), axis=0, return_index=True)
    return F[np.sort(keep)]


def _edges(F: np.ndarray):
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = np.sort(E, axis=1)
    _, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return E, inv, counts


def topology(P: np.ndarray, F: np.ndarray) -> dict:
    """Edge counts of a welded mesh, degenerate triangles left out (they have no area): what the audit reads."""
    deg = len(F) - len(_drop_degenerate(F))
    F = _drop_degenerate(F)
    if not len(F):
        return {"boundary": 0, "nonmanifold": 0, "winding": 0, "duplicate": 0, "flat": 0, "degenerate": deg,
                "triangles": 0}
    E, inv, c = _edges(F)
    fwd = (E[:, 0] < E[:, 1]).astype(np.int64)
    s = np.bincount(inv, weights=fwd, minlength=len(c))
    return {"boundary": int((c == 1).sum()), "nonmanifold": int((c > 2).sum()),
            "winding": int(((c == 2) & (s != 1)).sum()), "duplicate": int(len(F) - len(_drop_duplicates(F))),
            "flat": int(_flat(P, F).sum()), "degenerate": int(deg), "triangles": int(len(F))}


def closed(t: dict) -> bool:
    return not (t["boundary"] or t["nonmanifold"] or t["winding"] or t["duplicate"] or t.get("flat"))


def open_edges(t: dict) -> int:
    return t["boundary"] + t["nonmanifold"] + t["winding"] + t["duplicate"] + t.get("flat", 0)


# ---- repair (the last rung) ------------------------------------------------------------------------------------
def _orient(F: np.ndarray) -> np.ndarray:
    """Flip triangles so that every manifold edge is used once in each direction (breadth first from the first
    triangle of each connected piece); a piece with negative volume is turned inside out afterwards by the caller."""
    F = F.copy()
    E, inv, c = _edges(F)
    n = len(F)
    tri_of = np.tile(np.arange(n), 3)
    by_edge: dict = {}
    for e_i, (k, t) in enumerate(zip(inv.tolist(), tri_of.tolist())):
        if c[k] == 2:
            by_edge.setdefault(k, []).append(e_i)
    nbr: list = [[] for _ in range(n)]
    for k, (a, b) in by_edge.items():
        ta, tb = tri_of[a], tri_of[b]
        same = bool(E[a][0] == E[b][0])        # both triangles use the edge in the same direction: one must flip
        nbr[ta].append((tb, same))
        nbr[tb].append((ta, same))
    flip = np.zeros(n, bool)
    seen = np.zeros(n, bool)
    for s in range(n):
        if seen[s]:
            continue
        seen[s] = True
        stack = [s]
        while stack:
            t = stack.pop()
            for u, same in nbr[t]:
                if not seen[u]:
                    seen[u] = True
                    flip[u] = flip[t] ^ same
                    stack.append(u)
    F[flip] = F[flip][:, [0, 2, 1]]
    return F


def _loops(F: np.ndarray) -> list[list[int]]:
    """Boundary loops, each in the direction that fills the hole consistently with its neighbours. A vertex where
    two loops touch is split so each loop is simple."""
    E, inv, c = _edges(F)
    b = E[c[inv] == 1]
    nxt: dict = {}
    for a, z in b.tolist():
        nxt.setdefault(z, []).append(a)        # the fill runs against the boundary edge's direction
    out = []
    for s in list(nxt):
        while nxt.get(s):
            path, pos = [s], {s: 0}
            v = nxt[s].pop()
            while True:
                if v in pos:                   # closed a cycle: cut it out, keep walking from v
                    i = pos[v]
                    cyc = path[i:]
                    if len(cyc) >= 3:
                        out.append(cyc)
                    for x in cyc[1:]:
                        pos.pop(x, None)
                    path = path[:i + 1]
                    if v == s and len(path) == 1:
                        break
                else:
                    pos[v] = len(path)
                    path.append(v)
                if not nxt.get(v):
                    break
                v = nxt[v].pop()
    return out


def _earclip(Q: np.ndarray, taken=None) -> list[tuple[int, int, int]]:
    """Triangles of a simple polygon given in 2D (ear clipping, vectorised point tests). taken(i, j): the diagonal
    i-j is already an edge of the mesh (an ear that would add it a third triangle is skipped while another ear
    exists). Falls back to a fan from the first vertex if no ear is found (a self-overlapping hole)."""
    n = len(Q)
    idx = list(range(n))
    x, y = Q[:, 0], Q[:, 1]
    area = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    sgn = 1.0 if area >= 0 else -1.0
    tris = []
    stall = 0
    i = 0
    while len(idx) > 3:
        m = len(idx)
        i %= m
        a, b, c = idx[i - 1], idx[i], idx[(i + 1) % m]
        pa, pb, pc = Q[a], Q[b], Q[c]
        cr = sgn * ((pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]))
        ear = cr > 0 and not (taken is not None and m > 3 and stall <= m and taken(a, c))
        if ear and m > 3:
            rest = np.array([j for j in idx if j not in (a, b, c)])
            R = Q[rest]
            d1 = sgn * ((pb[0] - pa[0]) * (R[:, 1] - pa[1]) - (pb[1] - pa[1]) * (R[:, 0] - pa[0]))
            d2 = sgn * ((pc[0] - pb[0]) * (R[:, 1] - pb[1]) - (pc[1] - pb[1]) * (R[:, 0] - pb[0]))
            d3 = sgn * ((pa[0] - pc[0]) * (R[:, 1] - pc[1]) - (pa[1] - pc[1]) * (R[:, 0] - pc[0]))
            ear = not bool(np.any((d1 > 0) & (d2 > 0) & (d3 > 0)))
        if ear:
            tris.append((a, b, c))
            idx.pop(i)
            stall = 0
            continue
        i += 1
        stall += 1
        if stall > m:                          # no ear left: fan the rest (a hole that overlaps itself)
            tris += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
            return tris
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return tris


SPLIT_MM = 2e-5                 # how far the two sides of a touching edge are moved apart (well over the audit's weld)


def split_touching(P: np.ndarray, F: np.ndarray, delta: float = SPLIT_MM) -> tuple[np.ndarray, np.ndarray, int]:
    """A solid that touches itself along an edge (two walls meeting in a line: four triangles on one edge) is a
    valid B-rep but not a manifold mesh. Around each end of such an edge the triangles fall into separate fans; each
    fan after the first gets its own copy of the vertex, moved `delta` toward that fan, so each side is closed on
    its own. Returns (P, F, vertices split); the surface moves by at most delta."""
    E, inv, c = _edges(F)
    bad_e = np.nonzero(c > 2)[0]
    if not len(bad_e):
        return P, F, 0
    tri_of = np.tile(np.arange(len(F)), 3)
    bad_key = set(bad_e.tolist())
    verts = set()
    for k in bad_e.tolist():
        a, b = E[np.nonzero(inv == k)[0][0]]
        verts.update((int(a), int(b)))
    key_of = {}
    for i, k in enumerate(inv.tolist()):
        key_of.setdefault(k, []).append(i)
    F = F.copy()
    P = list(map(tuple, P))
    split = 0
    for u in sorted(verts):
        ts = np.nonzero((F == u).any(axis=1))[0].tolist()
        parent = {t: t for t in ts}

        def root(t):
            while parent[t] != t:
                parent[t] = parent[parent[t]]
                t = parent[t]
            return t

        for t in ts:                           # join triangles across manifold edges at u
            for j in range(3):
                e_i = t + j * len(F)
                k = int(inv[e_i])
                if k in bad_key or c[k] != 2 or u not in E[e_i]:
                    continue
                for e2 in key_of[k]:
                    t2 = int(tri_of[e2])
                    if t2 != t and t2 in parent:
                        parent[root(t2)] = root(t)
        groups: dict = {}
        for t in ts:
            groups.setdefault(root(t), []).append(t)
        if len(groups) < 2:
            continue
        base = np.array(P[u])
        for g in list(groups.values())[1:]:
            cen = np.mean([np.mean([P[v] for v in F[t]], axis=0) for t in g], axis=0)
            d = cen - base
            n = np.linalg.norm(d)
            P.append(tuple(base + (d / n * delta if n > 0 else 0)))
            new = len(P) - 1
            for t in g:
                F[t][F[t] == u] = new
            split += 1
    return np.array(P), F, split


def _thin_nonmanifold(P: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, int]:
    """Where an edge has more than two triangles, drop the smallest of them until two remain (the hole left is
    filled afterwards): the extra triangles are slivers that a crack or a weld folded onto the edge."""
    E, inv, c = _edges(F)
    bad = np.nonzero(c > 2)[0]
    if not len(bad):
        return F, 0
    n = len(F)
    tri = np.tile(np.arange(n), 3)
    area = np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)
    drop = set()
    badset = set(bad.tolist())
    groups: dict = {}
    for e_i, k in enumerate(inv.tolist()):
        if k in badset:
            groups.setdefault(k, []).append(int(tri[e_i]))
    for ts in groups.values():
        ts = [t for t in ts if t not in drop]
        ts.sort(key=lambda t: area[t])
        drop.update(ts[:max(0, len(ts) - 2)])
    keep = np.ones(n, bool)
    keep[list(drop)] = False
    return F[keep], len(drop)


def _drop_twisted(F: np.ndarray) -> tuple[np.ndarray, int]:
    """Triangles on an edge that both use in the same direction after orienting: the surface cannot be oriented
    there (a sliver folded over its neighbours). They go, and the hole they leave is filled flat."""
    E, inv, c = _edges(F)
    fwd = (E[:, 0] < E[:, 1]).astype(np.int64)
    s = np.bincount(inv, weights=fwd, minlength=len(c))
    bad = (c == 2) & (s != 1)
    if not bad.any():
        return F, 0
    tri = np.tile(np.arange(len(F)), 3)
    drop = np.unique(tri[bad[inv]])
    keep = np.ones(len(F), bool)
    keep[drop] = False
    return F[keep], int(len(drop))


def _bad_triangles(F: np.ndarray, boundary: bool = False) -> np.ndarray:
    """Triangles with a non-manifold or twisted edge (or an open one, with boundary=True)."""
    E, inv, c = _edges(F)
    fwd = (E[:, 0] < E[:, 1]).astype(np.int64)
    s = np.bincount(inv, weights=fwd, minlength=len(c))
    bad = ((c > 2) | ((c == 2) & (s != 1)) | ((c == 1) & boundary))[inv]
    out = np.zeros(len(F), bool)
    out[np.tile(np.arange(len(F)), 3)[bad]] = True
    return out


def _fill(P: np.ndarray, F: np.ndarray, deadline: float, stats: dict) -> np.ndarray:
    edges = set(map(tuple, np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1).tolist()))
    new = []
    for L in _loops(F):
        if time.time() > deadline:
            break
        Q = P[L]
        c = Q.mean(axis=0)
        _, _, vt = np.linalg.svd(Q - c, full_matrices=False)
        stats["fill_deviation_mm"] = max(stats["fill_deviation_mm"], float(np.abs((Q - c) @ vt[2]).max()))
        stats["largest_hole_mm"] = max(stats["largest_hole_mm"], float(np.linalg.norm(Q - c, axis=1).max()) * 2)
        t = _earclip((Q - c) @ vt[:2].T, lambda i, j, L=L: (min(L[i], L[j]), max(L[i], L[j])) in edges)
        stats["self_overlapping_holes"] += int(len(t) != len(L) - 2)
        for x, y, z in t:
            new.append((L[x], L[y], L[z]))
            edges.update({(min(L[x], L[y]), max(L[x], L[y])), (min(L[y], L[z]), max(L[y], L[z])),
                          (min(L[x], L[z]), max(L[x], L[z]))})
        stats["holes_filled"] += 1
    if new:
        F = np.concatenate([F, np.array(new, dtype=F.dtype)])
    return _drop_duplicates(_drop_flat(P, _drop_degenerate(F)))


def repair(P: np.ndarray, F: np.ndarray, deadline: float, small: float = 0.01) -> tuple[np.ndarray, np.ndarray, dict]:
    """The last rung. Each pass: drop degenerate and duplicate triangles, thin edges with more than two triangles,
    orient consistently, and fill every hole flat from its own edges. A pass that leaves a defect first cuts the
    triangles around it out (one ring), so the next fill meets a clean hole. Returns (P, F, info): holes filled,
    the largest hole's span, triangles cut out (only ones smaller than `small` mm²), and the fill's deviation (the most a hole's edge is from its
    best-fit plane: a flat fill can be no closer to a curved surface than that)."""
    stats = {"holes_filled": 0, "largest_hole_mm": 0.0, "fill_deviation_mm": 0.0, "self_overlapping_holes": 0,
             "sliver_triangles_dropped": 0, "edges_split_apart": 0}
    F = _drop_duplicates(_drop_flat(P, _drop_degenerate(F)))
    P, F, stats["edges_split_apart"] = split_touching(P, F)
    for k in range(6):
        if time.time() > deadline:
            break
        F, n = _thin_nonmanifold(P, F)
        stats["sliver_triangles_dropped"] += n
        F = _orient(F)
        if closed(topology(P, F)):
            break
        if k:                                  # a defect survived a fill: cut out its small triangles (slivers, fins)
            area = 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)
            ring = _bad_triangles(F, boundary=k >= 3) & (area < small)   # open edges: filled as they are first
            stats["sliver_triangles_dropped"] += int(ring.sum())
            F = F[~ring]
            F = _orient(F)
        F = _fill(P, F, deadline, stats)
    F = _orient(F)
    F, n = _drop_flat_pieces(P, F, small * 1e-3)
    stats["sliver_triangles_dropped"] += n
    if _volume(P, F) < 0:                      # the whole piece came out inside out
        F = F[:, [0, 2, 1]]
    stats["largest_hole_mm"] = round(stats["largest_hole_mm"], 4)
    return P, F, stats


def components(F: np.ndarray) -> np.ndarray:
    """Connected piece of each triangle, triangles sharing an edge connected (as form/mesh_audit.py counts them)."""
    n = len(F)
    if not n:
        return np.zeros(0, np.int64)
    _E, inv, _c = _edges(F)
    tri = np.tile(np.arange(n), 3)
    parent = np.arange(n)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = np.argsort(inv, kind="stable")
    g, t = inv[order], tri[order]
    for j in np.nonzero(g[1:] == g[:-1])[0].tolist():
        ra, rb = root(int(t[j])), root(int(t[j + 1]))
        if ra != rb:
            parent[rb] = ra
    r = np.array([root(i) for i in range(n)])
    return np.unique(r, return_inverse=True)[1]


def _drop_flat_pieces(P: np.ndarray, F: np.ndarray, vol_eps: float) -> tuple[np.ndarray, int]:
    """Pieces that enclose no volume (a hole filled from both sides of a sliver makes a flat closed pillow)."""
    comp = components(F)
    if comp.max(initial=0) == 0:
        return F, 0
    keep = np.ones(len(F), bool)
    dropped = 0
    for k in range(comp.max() + 1):
        m = comp == k
        if abs(_volume(P, F[m])) <= vol_eps:
            keep &= ~m
            dropped += int(m.sum())
    return F[keep], dropped


def _volume(P: np.ndarray, F: np.ndarray) -> float:
    if not len(F):
        return 0.0
    a, b, c = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


# ---- OCCT side (kernel worker only) ----------------------------------------------------------------------------
def _mesh(shape, tol: float, ang: float, clean: bool = True) -> None:
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    if clean:
        BRepTools.Clean_s(shape.wrapped)
    BRepMesh_IncrementalMesh(shape.wrapped, tol, False, ang, True).Perform()


def _triangles(shape) -> tuple[np.ndarray, list]:
    """(triangles (n, 3, 3) of the shape's current triangulation, faces that have none). OCCT's STL writer does the
    walk over faces in C++; the file is read back as an array."""
    import os
    import tempfile
    from OCP.BRep import BRep_Tool
    from OCP.StlAPI import StlAPI_Writer
    from OCP.TopLoc import TopLoc_Location
    missing = []
    for f in shape.faces():
        tri = BRep_Tool.Triangulation_s(f.wrapped, TopLoc_Location())
        if tri is None or tri.NbTriangles() == 0:
            missing.append(f)
    fd, tmp = tempfile.mkstemp(suffix=".stl", prefix="form-mesh-")
    os.close(fd)
    try:
        w = StlAPI_Writer()
        w.ASCIIMode = False
        w.Write(shape.wrapped, tmp)
        raw = np.fromfile(tmp, dtype=np.uint8)
    finally:
        os.unlink(tmp)
    n = int(raw[80:84].view(np.uint32)[0]) if raw.size >= 84 else 0
    if not n:
        return np.zeros((0, 3, 3)), missing
    rec = raw[84:84 + 50 * n].reshape(n, 50)
    V = np.ascontiguousarray(rec[:, 12:48]).view(np.float32).reshape(n, 3, 3).astype(np.float64)
    return V, missing


def _sewn(solid, tol: float):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from build123d import Solid
    sw = BRepBuilderAPI_Sewing(tol)
    for f in solid.faces():
        sw.Add(f.wrapped)
    sw.Perform()
    ex = TopExp_Explorer(sw.SewedShape(), TopAbs_SHELL)
    if not ex.More():
        return None
    mk = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current()))
    fix = ShapeFix_Solid(mk.Solid())
    fix.Perform()
    return Solid(fix.Solid())


def surface_distance(solid, points: np.ndarray, deadline: float, cap: int = 3000) -> tuple[float | None, int, list]:
    """The largest distance from `points` to the solid's boundary surface (BRepExtrema), measured on up to `cap`
    of them (evenly spaced through the list) before the deadline, with where it is.
    (None, 0, []) when nothing could be measured."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    if not len(points):
        return 0.0, 0, []
    from build123d import Compound
    shells = solid.shells() if hasattr(solid, "shells") else []
    target = Compound(list(shells)).wrapped if shells else solid.wrapped   # every shell: voids have their own
    pick = points[np.linspace(0, len(points) - 1, min(cap, len(points))).astype(int)]
    d = BRepExtrema_DistShapeShape()
    d.LoadS2(target)
    worst, n, at = 0.0, 0, []
    for p in pick:
        if time.time() > deadline and n:
            break
        d.LoadS1(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex())
        d.Perform()
        if d.IsDone():
            if float(d.Value()) > worst:
                worst, at = float(d.Value()), [round(float(x), 3) for x in p]
            n += 1
    return (worst if n else None), n, at


def _pieces(shape) -> list:
    solids = shape.solids()
    return list(solids) if solids else [shape]


GUARD_FACES = 60                # a shape with more faces is meshed in a child process (form/meshguard.py)


class _Mesher:
    """Triangles of the solids of one shape at given settings: in this process for a small shape, else in a child
    process that is killed when it runs over (a hung BRepMesh cannot be interrupted here)."""

    def __init__(self, shape, guard: bool | None = None):
        self.shape, self.pieces = shape, _pieces(shape)
        self.guard = (len(shape.faces()) > GUARD_FACES) if guard is None else guard
        self.brep = None
        self.hung: list = []
        if self.guard:
            import tempfile
            from . import meshguard
            self.tmp = Path(tempfile.mkdtemp(prefix="form-meshclose-"))
            self.brep = self.tmp / "shape.brep"
            meshguard.write_brep(shape, self.brep)

    def mesh(self, piece: int, tol: float, ang: float, timeout: float, faces_alone: bool = False):
        """[(V, faces without triangles)] for piece (-1: every solid), or None when it did not finish in time."""
        if not self.guard:
            target = self.shape if piece < 0 else self.pieces[piece]
            _mesh(target, tol, ang)
            out = []
            for solid in (self.pieces if piece < 0 else [target]):
                V, miss = _triangles(solid)
                if faces_alone and miss:
                    for t, a in ((tol / 2, ang), (tol / 5, ang / 2), (tol / 20, ang / 2), (tol / 50, ang / 4)):
                        for f in miss:
                            _mesh(f, t, a, clean=False)
                        V, miss = _triangles(solid)
                        if not miss:
                            break
                out.append((V, len(miss)))
            return out
        from . import meshguard
        try:
            res = meshguard.run(self.brep, piece, tol, ang, faces_alone, timeout)
        except Exception as e:                 # noqa: BLE001 - reported with the rung that could not run
            self.hung.append({"tolerance": tol, "error": f"{type(e).__name__}: {e}"[:200]})
            return None
        if res is None:
            self.hung.append({"tolerance": tol, "seconds": round(timeout, 1), "piece": piece})
        return res

    def close(self):
        if self.brep is not None:
            import shutil
            shutil.rmtree(self.tmp, ignore_errors=True)


def close(shape, tol: float = 0.01, ang: float = 0.1, budget_s: float = 35.0) -> tuple[list, dict]:
    """Mesh every solid of `shape` closed: ([triangles (n, 3, 3) per solid], report). Never raises for a mesh that
    stays open: the report says which solid, which rung was reached and why."""
    t0 = time.time()
    deadline = t0 + budget_s
    M = _Mesher(shape)
    try:
        return _close(M, shape, tol, ang, budget_s, t0, deadline)
    finally:
        M.close()


def _close(M, shape, tol, ang, budget_s, t0, deadline):
    pieces = M.pieces
    reserve = min(12.0, budget_s * 0.35)          # kept for the mesh-side rungs (welded, repaired)
    mesh_by = deadline - reserve
    left = lambda: max(1.0, mesh_by - time.time())   # noqa: E731
    first = None
    used_tol = tol
    for t in (tol, 2 * tol, 4 * tol, 10 * tol):     # the whole shape: the asked-for settings, coarser if they hang
        first = M.mesh(-1, t, ang, min(max(left(), 4.0), max(8.0, budget_s * 0.3)))
        if first is not None:
            used_tol = t
            break
    if first is None:
        from .recipes import RecipeError
        raise RecipeError(f"The STL could not be made: OCCT's mesher did not finish for this shape at any deflection from "
                          f"{tol:g} to {10 * tol:g} mm within {budget_s:g} s.", "",
                          "Simplify the faces that are very small or very curved, then export again.")
    out, rows = [], []
    for k, solid in enumerate(pieces):
        V, n_missing = first[k]
        best = None
        tried = []

        def judge(V, rung, dev, extra=None):
            nonlocal best
            P, F = weld(V.astype(np.float32).astype(np.float64))   # judged as the STL stores it: float32 corners
            t = topology(P, F)
            tried.append({"rung": rung, "open_edges": open_edges(t), "at_s": round(time.time() - t0, 2),
                          **({"note": extra} if extra else {})})
            if TRACE:
                import sys
                print(f"meshclose: solid {k} {rung} open={open_edges(t)} t={time.time() - t0:.1f}s", file=sys.stderr, flush=True)
            cand = {"V": P[_drop_degenerate(F)], "topology": t, "rung": rung, "deviation_mm": dev, **(extra or {})}
            if best is None or open_edges(t) < open_edges(best["topology"]):
                best = cand
            return closed(t)

        note = {"faces_without_triangles": n_missing} if n_missing else {}
        if used_tol != tol:
            note["tolerance"] = used_tol
        done = judge(V, "mesh" if used_tol == tol else "finer", used_tol, note or None)
        settings = [(tol / 2, ang), (tol, ang * 2), (tol / 4, ang / 2), (tol / 10, ang / 2)]
        hung = min((h["tolerance"] for h in M.hung if "seconds" in h), default=0.0)
        for t, a in settings:                  # finer: the whole solid (never finer than a setting that ran over)
            if done or time.time() > mesh_by:
                break
            if (t >= used_tol and a == ang) or t <= hung:
                continue
            r = M.mesh(k, t, a, min(left(), max(5.0, budget_s * 0.25)))
            if r is None:
                break                          # finer than this hangs: no finer try
            V, n_missing = r[0]
            done = judge(V, "finer", max(t, 1e-6), {"tolerance": t, **({"faces_without_triangles": n_missing} if n_missing else {})})
        if not done and time.time() < mesh_by and n_missing:   # finer: only the faces that still got no triangles
            r = M.mesh(k, used_tol, ang, min(left(), max(5.0, budget_s * 0.25)), faces_alone=True)
            if r is not None:
                V, n_missing = r[0]
                done = judge(V, "finer", used_tol, {"faces_meshed_alone": True,
                                                    **({"faces_without_triangles": n_missing} if n_missing else {})})
        base_V = V
        if not done and time.time() < mesh_by and hasattr(solid, "faces"):
            try:
                sew_tol = min(1e-3, used_tol / 10)
                s2 = _sewn(solid, sew_tol)
                if s2 is not None:
                    M2 = _Mesher(s2, guard=M.guard)
                    try:
                        r = M2.mesh(-1, used_tol, ang, min(left(), max(5.0, budget_s * 0.25)))
                    finally:
                        M2.close()
                    if r is not None:
                        V2, missing2 = r[0]
                        done = judge(V2, "sewn", used_tol + sew_tol,
                                     {"sewing_mm": sew_tol, **({"faces_without_triangles": missing2} if missing2 else {})})
            except Exception as e:             # noqa: BLE001 - a rung that cannot run is reported, the next one runs
                tried.append({"rung": "sewn", "error": f"{type(e).__name__}: {e}"[:160]})
        welded_from = best["V"] if best is not None else base_V
        for eps in (tol / 4, tol / 2, tol):    # welded: cracks between faces (T-junctions stitched, then merged)
            if done or time.time() > deadline:
                break
            P, F = cluster(welded_from, tol / 100)
            F, n_split = stitch(P, _drop_flat(P, _drop_degenerate(F)), eps)
            F = _drop_duplicates(_drop_degenerate(F))
            done = judge(P[F], "welded", (best["deviation_mm"] if best else tol) + eps + 2 * (tol / 100) * 3 ** 0.5,
                         {"weld_mm": tol / 100, "stitch_mm": eps, "t_junctions_split": n_split})
        if not done and time.time() < deadline:   # repaired: the last resort, with its deviation stated
            src = best["V"] if best is not None else base_V
            P, F = cluster(src, tol / 10)
            F, _n = stitch(P, _drop_flat(P, _drop_degenerate(F)), tol / 2)
            before = set(map(tuple, np.sort(F, axis=1).tolist()))
            P, F, info = repair(P, F, deadline + min(10.0, budget_s / 3), small=(10 * tol) ** 2)
            added = np.array([f for f in F.tolist() if tuple(sorted(f)) not in before], dtype=np.int64).reshape(-1, 3)
            # how far the new triangles are from the CAD surface, measured: centroids and edge midpoints
            T = P[added] if len(added) else np.zeros((0, 3, 3))
            pts = np.concatenate([T.mean(axis=1), (T[:, 0] + T[:, 1]) / 2, (T[:, 1] + T[:, 2]) / 2,
                                  (T[:, 2] + T[:, 0]) / 2]) if len(T) else np.zeros((0, 3))
            try:
                meas, n_meas, at = surface_distance(solid, pts, deadline + min(10.0, budget_s / 3))
            except Exception:                  # noqa: BLE001 - then the bound from the fill's flatness stands
                meas, n_meas, at = None, 0, []
            base_dev = ((best["deviation_mm"] if best else tol) + 2 * (tol / 10) * 3 ** 0.5
                        + (SPLIT_MM if info.get("edges_split_apart") else 0.0))
            if meas is not None:
                info = {**info, "fill_measured_mm": round(meas, 6), "fill_points_measured": n_meas,
                        "fill_triangles": int(len(added)), **({"fill_worst_at": at} if at else {})}
                dev = base_dev + meas
            else:
                dev = base_dev + info["fill_deviation_mm"]
            done = judge(P[F], "repaired", dev, info)
        chosen = best
        t = chosen["topology"]
        row = {"solid": k, "closed": closed(t), "rung": chosen["rung"], "deviation_mm": round(float(chosen["deviation_mm"]), 6),
               "triangles": int(len(chosen["V"])), "tries": tried}
        for key in ("holes_filled", "largest_hole_mm", "self_overlapping_holes", "sliver_triangles_dropped", "weld_mm", "stitch_mm", "t_junctions_split",
                    "fill_measured_mm", "fill_points_measured", "fill_triangles", "fill_worst_at",
                    "edges_split_apart",
                    "sewing_mm", "tolerance",
                    "faces_without_triangles"):
            if chosen.get(key):
                row[key] = chosen[key]
        try:                                   # internal voids: closed shells of their own, inward facing
            shells = solid.shells() if hasattr(solid, "shells") else []
            if len(shells) > 1:
                row["voids_mm3"] = sorted((round(abs(float(sh.volume)), 3) for sh in shells), reverse=True)[1:]
        except Exception:                      # noqa: BLE001 - a note, not a measurement the export depends on
            pass
        if not row["closed"]:
            row["open"] = {k2: t[k2] for k2 in ("boundary", "nonmanifold", "winding", "duplicate", "flat") if t.get(k2)}
            row["why"] = _why(t, chosen, time.time() > deadline)
        rows.append(row)
        out.append(chosen["V"])
    ok = all(r["closed"] for r in rows)
    report = {"closed": ok, **({"mesher_ran_over": M.hung} if M.hung else {}), "solids": len(rows), "rung": _worst([r["rung"] for r in rows]),
              "deviation_mm": round(max((r["deviation_mm"] for r in rows), default=tol), 6),
              "seconds": round(time.time() - t0, 2), "per_solid": rows}
    if not ok:
        report["why"] = "; ".join(f"solid {r['solid'] + 1}: {r['why']}" for r in rows if not r["closed"])
    return out, report


RUNGS = ("mesh", "finer", "sewn", "welded", "repaired")


def _worst(rungs: list) -> str:
    return max(rungs, key=RUNGS.index) if rungs else "mesh"


def _why(t: dict, chosen: dict, out_of_time: bool) -> str:
    parts = []
    if t["boundary"]:
        parts.append(f"{t['boundary']} open edges" + (f" ({chosen['faces_without_triangles']} faces the mesher could not "
                                                     "triangulate)" if chosen.get("faces_without_triangles") else ""))
    if t["nonmanifold"]:
        parts.append(f"{t['nonmanifold']} edges shared by more than two triangles (the solid touches itself)")
    if t["winding"]:
        parts.append(f"{t['winding']} edges between triangles facing opposite ways")
    if t["duplicate"]:
        parts.append(f"{t['duplicate']} duplicate triangles")
    if t.get("flat"):
        parts.append(f"{t['flat']} triangles with no area")
    return ", ".join(parts) + (" after the time budget ran out" if out_of_time else f" after the last rung ({chosen['rung']})")


# ---- writing ---------------------------------------------------------------------------------------------------
def write(path, pieces: list) -> None:
    """A binary STL of the pieces in order (normals from the winding), and, for several pieces, the sidecar with each
    piece's triangle count (form/mesh_audit.py reads it)."""
    path = Path(path)
    V = np.concatenate([p for p in pieces if len(p)]) if any(len(p) for p in pieces) else np.zeros((0, 3, 3))
    n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0]) if len(V) else np.zeros((0, 3))
    ln = np.linalg.norm(n, axis=1, keepdims=True) if len(V) else np.zeros((0, 1))
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    rec = np.zeros(len(V), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, V
    with open(path, "wb") as fh:
        fh.write(b"Form Studio STL".ljust(80, b" "))
        fh.write(np.uint32(len(V)).tobytes())
        fh.write(rec.tobytes())
    side = Path(str(path) + PARTS_SUFFIX)
    if len(pieces) > 1:
        side.write_text(json.dumps({"parts": [int(len(p)) for p in pieces],
                                    "note": "triangles per solid, in order: each is audited as its own closed mesh"}),
                        encoding="utf-8")
    elif side.exists():
        side.unlink()
