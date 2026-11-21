"""Layer 2, the program route: the sketches and extrusions that make the mesh, read straight off it. Beta.

A designer models a prismatic part as sketches extruded between levels. This reads that program back:

1. Direction: the one along which most of the surface is caps (facing it) or walls (along it).
2. Levels: every height a mesh vertex sits at. Between two neighbouring levels the mesh is exactly a ruled solid,
   so each such slab is cut once and its loops (outlines and openings) are known exactly, with their positions at
   both ends. Caps and sharp horizontal creases are the "design levels".
3. Tubes and runs: a loop carried unchanged from one slab to the next is one tube; along a tube, slabs whose loop
   does not change (vertical walls) make one extrusion, and slabs over which it changes linearly between two design
   levels (a chamfer, a draft) make one ruled loft.
4. Sketches: each run's loop becomes lines, arcs and rounded corners (sketch.py), corners exactly where neighbours
   meet.
5. Regularisation: coordinates, levels, radii and diameters are pooled across the whole part; values within a
   quarter of the tolerance become one Param, snapped to a round number when that is within reach, mirrored
   coordinates become one Param when the part is symmetric about its centre plane, and circle diameters snap to
   standard hole sizes. Every Param says where its value came from.
6. Partial acceptance: what does not read as a sketch (a curved run, a loop the sketch does not hold, a run the
   verification blames) is kept as the mesh's own slices, booleaned in as a residual body. The rest stays
   parametric. Editability is the share of the result's surface that the accepted features make.
7. Verification: the recipe is built as the Studio builds it and compared with the mesh (two-sided Hausdorff); runs
   near the points outside the tolerance are moved into the residual and it is built again.

Kernel worker only (builds with build123d). Returns the same shape of result as tree.recipe.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import mesh as meshmod
from . import sketch as sk

CAP_DEG = 0.5                  # a facet within this of facing the direction is a cap
CREASE_DEG = 20.0              # a horizontal edge bending more than this is a design level
MAX_LEVELS = 2500              # more distinct heights than this: not a part made of sketches along this direction
MAX_NODES = 80                 # a loop needing more corners than this is not a sketch a person would draw
MIN_SCORE = 0.55               # share of the area in caps and walls below which the route is not tried
MIN_EXPLAINED = 0.4            # share of the walls read as sketches below which the route gives way to the others


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / max(float(np.linalg.norm(v)), 1e-300)


def _fmt(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ---- direction and levels ---------------------------------------------------------------------------------------------

def directions(N, A, k: int = 4) -> list:
    """Candidate directions with their score (share of the area in caps and walls), best first."""
    cands = [np.eye(3)[i] for i in (2, 0, 1)]
    big = np.argsort(-A)[: min(len(A), 4000)]
    for n in N[big]:
        if all(abs(abs(n @ c) - 1) > 1e-3 for c in cands):
            cands.append(_unit(n))
        if len(cands) > 12:
            break
    cc, cs = math.cos(math.radians(CAP_DEG)), math.sin(math.radians(CAP_DEG))
    tot = float(A.sum()) or 1.0
    out = []
    for d in cands:
        c = np.abs(N @ d)
        out.append((float(A[(c > cc) | (c < cs)].sum()) / tot, d))
    out.sort(key=lambda t: -t[0])
    return out[:k]


def _frame(d):
    """(d, u, w, names): the direction, two in-plane axes and the world-axis names of (u, w, d) ("U", "W", "H" when the
    direction is not a world axis). u, w, d is right-handed: Z -> (X, Y), X -> (Y, Z), Y -> (Z, X)."""
    k = int(np.argmax(np.abs(d)))
    if abs(abs(d[k]) - 1) < 1e-9:
        d = np.eye(3)[k]
        u = np.eye(3)[(k + 1) % 3]
        names = ("XYZ"[(k + 1) % 3], "XYZ"[(k + 2) % 3], "XYZ"[k])
    else:
        t = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
        u = _unit(t - (t @ d) * d)
        names = ("U", "W", "H")
    return d, u, np.cross(d, u), names


def _cluster(vals, eps):
    """Sorted values grouped where neighbours are within eps: (representatives, label per input)."""
    o = np.argsort(vals, kind="stable")
    s = vals[o]
    br = np.r_[True, np.diff(s) > eps]
    gid = np.cumsum(br) - 1
    reps = np.bincount(gid, weights=s) / np.bincount(gid)
    lab = np.empty(len(vals), dtype=np.int64)
    lab[o] = gid
    return reps, lab


def _groups(vals, eps):
    """Sorted values grouped so every group spans at most 2 eps and neighbours in it are within eps (a long chain
    of close values is cut, never pooled into one): (representatives, label per input)."""
    o = np.argsort(vals, kind="stable")
    s = vals[o]
    gid = np.zeros(len(s), dtype=np.int64)
    g, start = 0, s[0] if len(s) else 0.0
    for i in range(1, len(s)):
        if s[i] - s[i - 1] > eps or s[i] - start > 2 * eps:
            g += 1
            start = s[i]
        gid[i] = g
    reps = np.bincount(gid, weights=s) / np.bincount(gid)
    lab = np.empty(len(vals), dtype=np.int64)
    lab[o] = gid
    return reps, lab


@dataclass
class Frame:
    d: np.ndarray
    u: np.ndarray
    w: np.ndarray
    o: np.ndarray            # origin: plane coordinates are measured from here
    names: tuple = ("U", "W", "H")


class Slicer:
    """Sections of a closed mesh across one direction, by mesh edge: a loop is the list of edges the plane crosses,
    so the same loop can be evaluated at any height between the levels where those edges end."""

    def __init__(self, V, F, H, UV):
        self.H, self.UV = H, UV
        E, tri, eo, _ = meshmod.edges(F)
        self.E = E
        self.lo = np.minimum(H[E[:, 0]], H[E[:, 1]])
        self.hi = np.maximum(H[E[:, 0]], H[E[:, 1]])
        self.te = eo.reshape(3, -1).T                   # the three edges of each triangle

    def loops(self, h) -> list[np.ndarray]:
        cross = (self.lo < h) & (self.hi > h)
        tc = cross[self.te]
        rows = np.flatnonzero(tc.sum(axis=1) == 2)
        if not len(rows):
            return []
        te, m = self.te[rows], tc[rows]
        e1 = np.where(m[:, 0], te[:, 0], te[:, 1])
        e2 = np.where(m[:, 2], te[:, 2], te[:, 1])
        pairs = np.r_[np.c_[e1, e2], np.c_[e2, e1]]
        pairs = pairs[np.argsort(pairs[:, 0], kind="stable")]
        keys, cnt = np.unique(pairs[:, 0], return_counts=True)
        if np.any(cnt != 2):
            return []
        nb = {int(k): (int(a), int(b)) for k, a, b in zip(keys, pairs[0::2, 1], pairs[1::2, 1])}
        seen, out = set(), []
        for s in nb:
            if s in seen:
                continue
            loop, prev, cur = [s], -1, s
            seen.add(s)
            while True:
                a, b = nb[cur]
                nxt = a if a != prev else b
                if nxt == s or nxt in seen:
                    break
                prev, cur = cur, nxt
                seen.add(cur)
                loop.append(cur)
            if len(loop) >= 3:
                out.append(np.array(loop))
        return out

    def at(self, eids, h) -> np.ndarray:
        a, b = self.E[eids, 0], self.E[eids, 1]
        ha, hb = self.H[a], self.H[b]
        t = np.clip((h - ha) / np.where(hb != ha, hb - ha, 1.0), 0.0, 1.0)
        return self.UV[a] + t[:, None] * (self.UV[b] - self.UV[a])


def _bb(L):
    return np.r_[L.min(axis=0), L.max(axis=0)]


def _inside(pt, L) -> bool:
    x, y = L[:, 0], L[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    c = ((y > pt[1]) != (y2 > pt[1])) & (pt[0] < (x2 - x) * (pt[1] - y) / np.where(y2 != y, y2 - y, 1e-300) + x)
    return bool(np.count_nonzero(c) % 2)


def _interior_point(L):
    """A point inside the closed polygon L (near its first edge, on the inner side)."""
    area = sk._area2(L)
    for i in range(len(L)):
        a, b = L[i], L[(i + 1) % len(L)]
        t = b - a
        ln = float(np.linalg.norm(t))
        if ln < 1e-9:
            continue
        n = np.array([-t[1], t[0]]) / ln * (1 if area > 0 else -1)
        for eps in (1e-4, 1e-3, 1e-2):
            p = (a + b) / 2 + n * eps * max(ln, 1e-3)
            if _inside(p, L):
                return p
    return L.mean(axis=0)


@dataclass
class SubLoop:
    eids: np.ndarray
    bot: np.ndarray
    top: np.ndarray
    mid: np.ndarray
    depth: int = 0
    tube: int = -1


@dataclass
class Run:
    tube: int
    k0: int                 # first sub-slab
    k1: int                 # last sub-slab (inclusive)
    za: float
    zb: float
    kind: str               # prism | ruled | curved
    depth: int
    loops: list             # [(k, SubLoop)]
    bot: object = None      # sketch.Loop (prism: the loop; ruled: at za)
    top: object = None      # sketch.Loop at zb (ruled)
    why: str = ""
    id: str = ""
    label: str = ""
    fate: str = "feature"   # feature | envelope (the block of its levels holds it) | kept (the mesh's own slices)
    block: int = -1

    @property
    def add(self) -> bool:
        return self.depth % 2 == 0


# ---- reading the program ---------------------------------------------------------------------------------------------

def _nearest_on(P, L, k: int = 8):
    """Nearest point on the closed polyline L to each point of P (the k segments with the nearest middles are tried
    when the inputs are large)."""
    A, B = L, np.roll(L, -1, axis=0)
    if len(P) * len(A) > 40_000:
        from scipy.spatial import cKDTree
        tree = cKDTree((A + B) / 2)
        _, nn = tree.query(P, k=min(k, len(A)))
        nn = nn.reshape(len(P), -1)
        a, ab = A[nn], (B - A)[nn]
        t = np.clip(((P[:, None, :] - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-300), 0, 1)
        q = a + t[..., None] * ab
        j = np.linalg.norm(P[:, None, :] - q, axis=2).argmin(axis=1)
        return q[np.arange(len(P)), j]
    AB = B - A
    L2 = np.maximum((AB * AB).sum(1), 1e-300)
    best = np.full(len(P), np.inf)
    bq = np.zeros_like(P)
    for s in range(0, len(A), 256):
        a, ab, l2 = A[s:s + 256], AB[s:s + 256], L2[s:s + 256]
        t = np.clip(((P[:, None, :] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
        q = a[None] + t[..., None] * ab[None]
        d = np.linalg.norm(P[:, None, :] - q, axis=2)
        j = d.argmin(axis=1)
        dj = d[np.arange(len(P)), j]
        better = dj < best
        best[better] = dj[better]
        bq[better] = q[np.arange(len(P)), j][better]
    return bq


def _linear(bot, top, mids, tol) -> bool:
    """Do the sections `mids` [(t, polygon)] lie where the straight interpolation from bot (t=0) to top (t=1) puts
    them?"""
    for t, M in mids:
        qb, qt = _nearest_on(M, bot), _nearest_on(M, top)
        pred = (1 - t) * qb + t * qt
        if float(np.linalg.norm(M - pred, axis=1).max()) > tol:
            return False
    return True


def _same_structure(a, b) -> bool:
    if a is None or b is None or a.kind != b.kind:
        return False
    if a.kind == "circle":
        return True
    if len(a.nodes) != len(b.nodes):
        return False
    return all(x.kind == y.kind for x, y in zip(a.edges, b.edges)) and all((m.r > 0) == (n.r > 0) for m, n in zip(a.nodes, b.nodes))


def _align(a, b):
    """b's nodes rotated (and its loop kept) so node i of b corresponds to node i of a; None when no rotation fits."""
    if a.kind == "circle":
        return b
    n = len(a.nodes)
    if len(b.nodes) != n:
        return None
    A = np.array([q.p for q in a.nodes])
    B = np.array([q.p for q in b.nodes])
    best, bk = None, None
    for k in range(n):
        Bk = np.roll(B, -k, axis=0)
        e = float(np.linalg.norm(A - Bk, axis=1).max())
        if best is None or e < best:
            best, bk = e, k
    b2 = sk.Loop("path", b.nodes[bk:] + b.nodes[:bk], b.edges[bk:] + b.edges[:bk], err=b.err)
    return b2


def origin(V, tol):
    """The point all coordinates are measured from: the middle of the bounding box across, its bottom in Z, snapped
    to a round number when that is within a quarter of the tolerance (so mirrored values pair up)."""
    lo, hi = V.min(axis=0), V.max(axis=0)
    c = (lo + hi) / 2
    return np.array([_round_to(c[0], tol / 4), _round_to(c[1], tol / 4), _round_to(lo[2], tol / 4)])


def read(V, F, tol, d=None, deadline=None, progress=None, O=None, min_score=MIN_SCORE) -> dict | None:
    """The program's runs along direction d (or the best direction). Returns a plan dict, or None when the part is
    not made of sketches along any direction."""
    say = progress or (lambda x: None)
    N, A = meshmod.tri_normals(V, F)
    size = float(np.linalg.norm(np.ptp(V, axis=0))) or 1.0
    if d is None:
        dirs = directions(N, A)
        score, d = dirs[0]
    else:
        c = np.abs(N @ d)
        score = float(A[(c > math.cos(math.radians(CAP_DEG))) | (c < math.sin(math.radians(CAP_DEG)))].sum() / max(A.sum(), 1e-300))
    if score < min_score:
        return {"error": f"Only {100 * score:.0f}% of the surface faces or runs along one direction; this is not a part "
                         "made of sketches and extrusions.", "score": score}
    d, u, w, names = _frame(np.asarray(d, dtype=np.float64))
    O = origin(V, tol) if O is None else np.asarray(O, dtype=np.float64)
    H0 = (V - O) @ d
    reps, lab = _cluster(H0, max(1e-6 * size, 1e-7))
    if len(reps) > MAX_LEVELS:
        return {"error": f"{len(reps)} distinct heights along the direction: a curved part, not a stack of sketches.",
                "score": score}
    H = reps[lab]
    UV = np.c_[(V - O) @ u, (V - O) @ w]
    fr = Frame(d, u, w, O, names)
    Hz = H
    # design levels: caps and sharp horizontal creases
    cc = math.cos(math.radians(CAP_DEG))
    cap = np.abs(N @ d) > cc
    design = set(np.unique(lab[F[cap].ravel()]).tolist()) | {0, len(reps) - 1}
    E, tri, eo, _ = meshmod.edges(F)
    o_ = np.argsort(eo, kind="stable")
    eo_s, tri_s = eo[o_], tri[o_]
    nb = np.flatnonzero(eo_s[1:] == eo_s[:-1])
    t1, t2, e = tri_s[nb], tri_s[nb + 1], eo_s[nb]
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", N[t1], N[t2]), -1, 1)))
    flat_edge = lab[E[e, 0]] == lab[E[e, 1]]
    design |= set(np.unique(lab[E[e[(ang > CREASE_DEG) & flat_edge], 0]]).tolist())
    sl = Slicer(V, F, Hz, UV)
    subs = []
    for k in range(len(reps) - 1):
        if deadline is not None and time.perf_counter() > deadline:
            return {"error": "The time budget for this route ran out while slicing the part.", "score": score}
        if k and k % 100 == 0:
            say({"stage": "layer2", "text": f"Slicing: {k} of {len(reps) - 1} slabs", "fraction": 0.1 * k / len(reps)})
        a, b = float(reps[k]), float(reps[k + 1])
        loops = []
        for eids in sl.loops((a + b) / 2):
            bot, top, mid = sl.at(eids, a), sl.at(eids, b), sl.at(eids, (a + b) / 2)
            if sk._area2(mid) < 0:
                eids, bot, top, mid = eids[::-1], bot[::-1], top[::-1], mid[::-1]
            loops.append(SubLoop(eids, bot, top, mid))
        for i, lp in enumerate(loops):
            lp.depth = sum(1 for j, q in enumerate(loops) if j != i and _inside(lp.mid[0], q.mid))
        subs.append((a, b, loops))
    say({"stage": "layer2", "text": f"Read {len(subs)} slabs across {len(reps)} levels", "fraction": 0.1})
    # tubes: a loop carried on unchanged across a level
    geo = max(1e-4, tol / 50)
    tubes = []
    for k, (a, b, loops) in enumerate(subs):
        for i, lp in enumerate(loops):
            if lp.tube >= 0:
                continue
            lp.tube = len(tubes)
            chain = [(k, lp)]
            cur, kk = lp, k
            while kk + 1 < len(subs):
                nxt = [q for q in subs[kk + 1][2] if q.tube < 0 and q.depth == cur.depth
                       and np.abs(_bb(cur.top) - _bb(q.bot)).max() <= geo and sk.same(cur.top, q.bot, geo)]
                if len(nxt) != 1:
                    break
                nxt[0].tube = lp.tube
                chain.append((kk + 1, nxt[0]))
                cur, kk = nxt[0], kk + 1
            tubes.append(chain)
    # runs along each tube
    runs = []
    vert = max(1e-4, tol / 20)
    for ti, chain in enumerate(tubes):
        i = 0
        while i < len(chain):
            k0, l0 = chain[i]
            j = i
            prism = sk.same(l0.bot, l0.top, vert)
            while j + 1 < len(chain):
                k1, l1 = chain[j + 1]
                if prism:
                    if sk.same(l1.bot, l1.top, vert) and sk.same(l0.mid, l1.mid, vert):
                        j += 1
                        continue
                    break
                # ruled: the run's ends interpolate every section between them
                kb, lb = chain[i]
                mids = [((float(subs[kk][1]) - float(subs[kb][0])) / (float(subs[k1][1]) - float(subs[kb][0])), q.top)
                        for kk, q in chain[i:j + 1]]
                if sk.same(l1.bot, l1.top, vert) or not _linear(lb.bot, l1.top, mids, tol / 4):
                    break
                j += 1
            kA, kB = chain[i][0], chain[j][0]
            za, zb = float(subs[kA][0]), float(subs[kB][1])
            kind = "prism" if prism else "ruled"
            why = ""
            if zb - za < tol:
                kind, why = "curved", "it is thinner than the tolerance (a strip of a curved surface)"
            if kind == "ruled":
                ia, ib = int(np.searchsorted(reps, za - 1e-9)), int(np.searchsorted(reps, zb - 1e-9))
                if ia not in design or ib not in design:
                    kind, why = "curved", "its walls curve along the direction (a rounded or freeform edge)"
            runs.append(Run(ti, kA, kB, za, zb, kind, chain[i][1].depth, chain[i:j + 1], why=why))
            i = j + 1
    runs = _straighten(runs, tol)
    say({"stage": "layer2", "text": f"{len(runs)} candidate features; fitting their sketches", "fraction": 0.2})
    # sketches
    for r in runs:
        if deadline is not None and time.perf_counter() > deadline:
            r.kind, r.why = "curved", "the time budget ran out before its sketch was read"
            continue
        if r.kind == "curved":
            continue
        if r.kind == "prism":
            s = None
            for k, lp in sorted(r.loops, key=lambda t: subs[t[0]][0] - subs[t[0]][1])[:3]:
                for ft in (tol / 2, tol / 3):
                    s = sk.fit(lp.mid, ft, size)
                    if s is not None and s.err <= tol / 2:
                        break
                    s = None
                if s is not None:
                    break
            if s is None or s.err > tol / 2:
                r.kind, r.why = "curved", "its outline is not lines and arcs within the tolerance"
                continue
            r.bot = s
        else:
            b0 = r.loops[0][1].bot
            t1_ = r.loops[-1][1].top
            pair = None
            if len(r.loops) == 1:
                for ft in (tol / 2, tol / 3):
                    pair = sk.fit_pair(b0, t1_, ft, size)
                    if pair is not None and max(pair[0].err, pair[1].err) <= tol / 2:
                        break
                    pair = None
            # each end on its own (fewer corners, when they agree), else the two ends split at the same points
            cands = []
            sb, st = sk.fit(b0, tol / 2, size), sk.fit(t1_, tol / 2, size)
            st = _align(sb, st) if sb is not None and st is not None else None
            if _same_structure(sb, st) and sb.err <= tol / 2 and st.err <= tol / 2:
                cands.append((sb, st))
            if pair is not None and _same_structure(*pair):
                cands.append(pair)
            # each end alone only when its corners move no farther than the walls can slope over the slab
            reach = 3 * (r.zb - r.za) + tol
            cands = [c for c in cands if c[0].kind == "circle" or
                     float(np.linalg.norm(np.array([n.p for n in c[0].nodes]) - np.array([n.p for n in c[1].nodes]),
                                          axis=1).max()) <= reach]
            if cands:
                sb, st = cands[-1] if (pair is not None and cands[-1] is pair) else cands[0]
            if not _same_structure(sb, st) or sb.err > tol / 2 or st.err > tol / 2:
                r.kind, r.why = "curved", "its two ends do not read as the same sketch"
                continue
            r.bot, r.top = sb, st
        if r.bot.kind == "path" and len(r.bot.nodes) > MAX_NODES:
            r.kind, r.why = "curved", f"its outline needs {len(r.bot.nodes)} corners"
            r.bot = r.top = None
    for r in runs:
        r.fate = "feature" if r.kind != "curved" else "envelope"
    dl = np.array(sorted(float(reps[i]) for i in design))
    return {"frame": fr, "runs": runs, "subs": subs, "slicer": sl, "levels": reps, "design": design, "design_levels": dl, "tol": tol,
            "score": score, "size": size, "blocks": []}


def _straighten(runs, tol):
    """Neighbouring curved runs of one tube whose sections all lie within a third of the tolerance of the section in
    their middle are one extrusion of that section: walls that lean or wave by less than the tolerance (a slight
    draft, a mesh's own noise) are vertical within it, and a person would have drawn them so."""
    out, i = [], 0
    while i < len(runs):
        r = runs[i]
        if r.kind != "curved":
            out.append(r)
            i += 1
            continue
        j = i
        while j + 1 < len(runs) and runs[j + 1].kind == "curved" and runs[j + 1].tube == r.tube and \
                runs[j + 1].k0 == runs[j].k1 + 1:
            j += 1
        span = runs[i:j + 1]
        loops = [x for q in span for x in q.loops]
        best = None
        if len(loops) >= 1 and span[-1].zb - span[0].za >= tol:
            mid = loops[len(loops) // 2][1].mid
            if all(sk.same(lp.bot, mid, tol / 3) and sk.same(lp.top, mid, tol / 3) for _, lp in loops):
                best = Run(r.tube, span[0].k0, span[-1].k1, span[0].za, span[-1].zb, "prism", r.depth, loops,
                           why="its walls are vertical within a third of the tolerance")
        if best is not None:
            out.append(best)
        else:
            out += span
        i = j + 1
    return out


def _round_to(x, within):
    for g in (10, 5, 1, 0.5, 0.25, 0.1, 0.05, 0.01, 0.005, 0.001):
        s = round(x / g) * g
        if abs(s - x) <= within:
            return float(round(s, 6))
    return float(x)


# ---- parameters: pooled, snapped, mirrored ---------------------------------------------------------------------------

GRIDS = (10.0, 5.0, 1.0, 0.5, 0.25, 0.1, 0.05, 0.01)
KIND_LABEL = {"X": "X", "Y": "Y", "Z": "Z", "U": "U", "W": "W", "H": "Level", "r": "Radius", "d": "Diameter",
              "L": "Length", "P": "Pitch circle Ø"}
SIZE_KINDS = ("r", "d", "L", "P")      # sizes: always positive, ranged by a share of their value
MIRROR = ("X", "Y", "U", "W")
USE_WORD = {"X": "corners", "Y": "corners", "Z": "corners and levels", "U": "corners", "W": "corners", "H": "levels",
            "r": "radii", "d": "circles", "L": "lengths", "P": "patterns"}


# ---- envelopes: a block of levels that does not read as sketches along this direction --------------------------------

def _inside_many(P, L):
    """Even-odd test of many points against one closed polygon (vectorised over the points)."""
    x, y = L[:, 0], L[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    out = np.zeros(len(P), dtype=bool)
    for s in range(0, len(L), 512):
        xa, ya, xb, yb = x[s:s + 512], y[s:s + 512], x2[s:s + 512], y2[s:s + 512]
        c = ((ya[None] > P[:, 1:2]) != (yb[None] > P[:, 1:2])) & (
            P[:, 0:1] < (xb - xa)[None] * (P[:, 1:2] - ya[None]) / np.where(yb != ya, yb - ya, 1e-300)[None] + xa[None])
        out ^= (np.count_nonzero(c, axis=1) % 2).astype(bool)
    return out


def _material_area(loops) -> float:
    return sum(abs(sk._area2(P)) * (1 if dep % 2 == 0 else -1) for P, dep in loops)


def _holds(loops, P, tol) -> bool:
    """Is every point of P in the material of `loops` (or within tol of its boundary)?"""
    inside = np.zeros(len(P), dtype=np.int64)
    for L, _ in loops:
        inside += _inside_many(P, L)
    ok = inside % 2 == 1
    if ok.all():
        return True
    rest = P[~ok]
    near = np.zeros(len(rest), dtype=bool)
    for L, _ in loops:
        near |= sk._seg_dist(rest, L, np.roll(L, -1, axis=0)) <= tol
    return bool(near.all())


def envelopes(plan, tol, superset=False):
    """For every group of levels (between two design levels) holding a run with fate "envelope": the union of the
    material of every section in it, as sketches (an outline that holds the mesh's material at every height there,
    so other directions can carve it). Sets plan["blocks"] and each run's block."""
    subs, dl = plan["subs"], plan["design_levels"]
    size = plan["size"]
    groups = {}
    for r in plan["runs"]:
        if r.fate != "envelope":
            continue
        A = float(dl[dl <= r.za + 1e-9].max()) if np.any(dl <= r.za + 1e-9) else r.za
        B = float(dl[dl >= r.zb - 1e-9].min()) if np.any(dl >= r.zb - 1e-9) else r.zb
        groups.setdefault((A, B), []).append(r)
    blocks = []
    for (A, B), rs in sorted(groups.items()):
        # the section with the most material, if it holds every other section between the two levels (a cross
        # hole, a chamfer or a rounding only takes material away from it)
        secs = []
        for k, (a, b, loops) in enumerate(subs):
            if a < A - 1e-9 or b > B + 1e-9:
                continue
            for side in ("bot", "top"):
                secs.append([(getattr(lp, side), lp.depth) for lp in loops])
        secs.sort(key=lambda sec: -_material_area(sec))
        chosen = None
        for cand in secs[:3]:
            if all(_holds(cand, np.vstack([P for P, _ in sec]), tol / 2) for sec in secs if sec is not cand and sec):
                chosen = cand
                break
        blk = {"A": A, "B": B, "loops": [], "runs": rs, "fate": "envelope"}
        if chosen is None and superset and secs:
            P = np.vstack([P for sec in secs for P, _ in sec])
            lo, hi = P.min(axis=0), P.max(axis=0)
            chosen = [(np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]), 0)]
            blk["bbox"] = True
        if chosen is None:
            blk["fate"] = "kept"
        else:
            polys = [P[::-1] if sk._area2(P) < 0 else P for P, _ in chosen if abs(sk._area2(P)) > tol * tol]
            for i, P in enumerate(polys):
                dep = sum(1 for j, Q in enumerate(polys) if j != i and _inside(P[0], Q))
                lp = sk.fit(P, tol / 2, size)
                if lp is None or lp.err > tol / 2 or (lp.kind == "path" and len(lp.nodes) > MAX_NODES):
                    if dep % 2 == 1:
                        continue                         # an opening the sketch cannot hold: left out (more material)
                    lo, hi = P.min(axis=0), P.max(axis=0)
                    lp = sk.Loop("path", [sk.Node(np.array([lo[0], lo[1]])), sk.Node(np.array([hi[0], lo[1]])),
                                          sk.Node(np.array([hi[0], hi[1]])), sk.Node(np.array([lo[0], hi[1]]))],
                                 [sk.Edge("line")] * 4)
                    blk["bbox"] = True
                blk["loops"].append((lp, dep))
            if not blk["loops"]:
                blk["fate"] = "kept"
        for r in rs:
            r.block = len(blocks)
        blocks.append(blk)
    plan["blocks"] = blocks
    return blocks


# ---- parameters: pooled, snapped, mirrored ---------------------------------------------------------------------------

class Pool:
    """Every length the sketches use, pooled per kind (world X, Y, Z coordinates from the part's origin, radii,
    diameters) and turned into Params."""

    def __init__(self, tol):
        self.tol = tol
        self.snap = tol / 4
        self.items = {k: [] for k in KIND_LABEL}      # kind -> [(value, user)]
        self.raw = {k: [] for k in KIND_LABEL}        # kind -> [value as read off the mesh]
        self.expr = {}                                 # (kind, index) -> code
        self.params = []

    def add(self, kind, value, user) -> tuple:
        self.items[kind].append((float(value), user))
        self.raw[kind].append(float(value))
        return (kind, len(self.items[kind]) - 1)

    def remap(self, kind):
        """A function from a value read off the mesh to the value the Params give it: exact for the values the
        sketches use, linear between them (so the levels of a kept slice of the mesh stay in order)."""
        if not self.raw[kind]:
            return lambda z: z
        pairs = {}
        for r_, (v_, _) in zip(self.raw[kind], self.items[kind]):
            pairs[round(r_, 9)] = v_
        xs = np.array(sorted(pairs))
        ys = np.array([pairs[x] for x in xs])

        def f(z):
            if len(xs) == 1:
                return float(z + (ys[0] - xs[0]))
            if z <= xs[0]:
                return float(z + (ys[0] - xs[0]))
            if z >= xs[-1]:
                return float(z + (ys[-1] - xs[-1]))
            return float(np.interp(z, xs, ys))
        return f

    def solve(self, name_of=None):
        from . import holes as holemod
        for kind, items in self.items.items():
            if not items:
                continue
            vals = np.array([v for v, _ in items])
            sym = kind in MIRROR
            key_vals = np.abs(vals) if sym else vals
            reps, lab = _groups(key_vals, self.snap)
            all_reps = sorted(set(np.round(reps, 9).tolist()))
            n_kind = 0
            for g in range(len(reps)):
                members = np.flatnonzero(lab == g)
                mv = key_vals[members]
                m = float(mv.mean())
                val, how = m, None
                if kind == "d":
                    sz = holemod.snap(m, within=self.snap)
                    if sz.get("standard") and float(np.abs(mv - sz["diameter_mm"]).max()) <= self.snap:
                        val, how = sz["diameter_mm"], sz["standard"]
                if how is None:
                    for gr in GRIDS:
                        s = round(m / gr) * gr
                        if float(np.abs(mv - s).max()) <= self.snap:
                            val, how = float(round(s, 6)), f"{_fmt(gr)} mm grid"
                            break
                if how is None:
                    val = float(round(m, 4))
                users = [items[i][1] for i in members]
                if abs(val) < 1e-9 and kind not in SIZE_KINDS:
                    for i in members:
                        self.expr[(kind, int(i))] = "0"
                        self.items[kind][int(i)] = (0.0, items[int(i)][1])
                    continue
                signs = np.sign(vals[members]) if sym else np.ones(len(members))
                mirrored = bool(sym and np.any(signs > 0) and np.any(signs < 0))
                n_kind += 1
                key = f"{kind.lower()}{n_kind}"
                feats = list(dict.fromkeys(users))
                shown = val if (mirrored or not sym) else val * float(signs[0])
                if mirrored:
                    label = f"{KIND_LABEL[kind]} ±{_fmt(val)}"
                elif kind in SIZE_KINDS + ("H",):
                    label = f"{KIND_LABEL[kind]} {_fmt(val)}"
                else:
                    label = f"{KIND_LABEL[kind]} {_fmt(shown)}"
                if name_of is not None:
                    names = list(dict.fromkeys(name_of(f) for f in feats))
                    label += " · " + ", ".join(names[:3]) + (" …" if len(names) > 3 else "")
                note = [f"computed from the mesh: {float(mv.min()):.4f}"
                        + (f" to {float(mv.max()):.4f}" if len(mv) > 1 and float(np.ptp(mv)) > 5e-5 else "")]
                if how:
                    note.append(f"snapped to {_fmt(val)} ({how}, within {self.snap:g} mm)")
                if len(members) > 1:
                    note.append(f"one value for {len(members)} {USE_WORD[kind]}")
                if mirrored:
                    note.append("mirrored about the centre plane (both sides measured within the tolerance)")
                others = [x for x in all_reps if abs(x - float(reps[g])) > 1e-9]
                # room on each side: 0.4 of the way to the nearest other value of this kind below and above, so two
                # neighbouring values can never be slid past each other (and a value with nothing on one side gets
                # its own size there)
                below = min([val - x for x in others if x < val] or [max(abs(val), 1.0)])
                above = min([x - val for x in others if x > val] or [max(abs(val), 1.0)])
                if kind in SIZE_KINDS:
                    lo, hi = max(0.05, val * 0.7), val * 1.3
                else:
                    lo, hi = val - max(0.4 * below, self.tol), val + max(0.4 * above, self.tol)
                    if mirrored or (kind in ("Z", "H") and val > 0):
                        lo = max(lo, 0.05 * val)
                if sym and not mirrored and signs[0] < 0:
                    lo, hi = -hi, -lo
                p = {"key": key, "kind": kind, "value": float(shown), "label": label, "note": "; ".join(note),
                     "uses": int(len(members)), "features": feats, "mirrored": mirrored,
                     "lo": float(round(lo, 4)), "hi": float(round(hi, 4))}
                self.params.append(p)
                for i, sgn in zip(members, signs):
                    i = int(i)
                    neg = mirrored and sgn < 0
                    self.expr[(kind, i)] = f"-v[{key!r}]" if neg else f"v[{key!r}]"
                    self.items[kind][i] = (-val if neg else float(shown), items[i][1])

    def value(self, h) -> float:
        return self.items[h[0]][h[1]][0]

    def code(self, h) -> str:
        return self.expr[h]


# ---- source ----------------------------------------------------------------------------------------------------------

def _volume_loop(lp, h) -> float:
    if lp is None:
        return 0.0
    a = math.pi * lp.r ** 2 if lp.kind == "circle" else abs(sk._area2(sk.points(lp, 8)))
    return a * h


def _name(plan, prefix):
    acc = [r for r in plan["runs"] if r.fate == "feature"]
    adds = sorted([r for r in acc if r.add], key=lambda r: -_volume_loop(r.bot, r.zb - r.za))
    cuts = sorted([r for r in acc if not r.add], key=lambda r: -_volume_loop(r.bot, r.zb - r.za))
    n = {"boss": 0, "step": 0, "hole": 0, "cut": 0}
    for i, r in enumerate(adds):
        if i == 0 and not prefix and not plan.get("revolve"):
            r.id, r.label = "base", "Base"
        elif r.bot.kind == "circle":
            n["boss"] += 1
            r.id, r.label = f"{prefix}boss{n['boss']}", f"Boss {n['boss']} (Ø{_fmt(2 * r.bot.r)})"
        else:
            n["step"] += 1
            r.id, r.label = f"{prefix}step{n['step']}", f"Step {n['step']}"
        if r.kind == "ruled":
            r.label += ", tapered"
    for r in cuts:
        if r.bot.kind == "circle":
            n["hole"] += 1
            r.id, r.label = f"{prefix}hole{n['hole']}", f"Hole {n['hole']} (Ø{_fmt(2 * r.bot.r)})"
        else:
            n["cut"] += 1
            r.id, r.label = f"{prefix}cut{n['cut']}", f"Cut {n['cut']}"
        if r.kind == "ruled":
            r.label += ", tapered"
    for i, b in enumerate(plan["blocks"]):
        b["id"], b["label"] = f"{prefix}block{i + 1}", f"Block {i + 1} (levels {_fmt(b['A'])} to {_fmt(b['B'])})"


def _loop_handles(pool, lp, fid, kx, ky):
    if lp.kind == "circle":
        return ("circle", pool.add(kx, lp.c[0], fid), pool.add(ky, lp.c[1], fid), pool.add("d", 2 * lp.r, fid))
    nodes = [(pool.add(kx, n.p[0], fid), pool.add(ky, n.p[1], fid), pool.add("r", n.r, fid) if n.r > 0 else None)
             for n in lp.nodes]
    edges = [None if e.kind == "line" else (pool.add("r", e.R, fid), e.ccw, e.large) for e in lp.edges]
    return ("path", nodes, edges)


def _loop_code(pool, h, plane):
    if h[0] == "circle":
        return f"disc({plane}, {pool.code(h[1])}, {pool.code(h[2])}, {pool.code(h[3])})"
    nodes = ", ".join(f"({pool.code(x)}, {pool.code(y)}, {pool.code(r) if r else 0})" for x, y, r in h[1])
    if all(e is None for e in h[2]):
        return f"profile({plane}, [{nodes}])"
    edges = ", ".join("None" if e is None else f"({pool.code(e[0])}, {e[1]}, {e[2]})" for e in h[2])
    return f"profile({plane}, [{nodes}], [{edges}])"


def _at(z):
    return "at(0)" if z == "0" else f"at({z})"


def _opens(plan, r, below: bool) -> bool:
    """Is there air beyond this cut's end (so the cut can run past it)?"""
    subs = plan["subs"]
    k = r.k0 - 1 if below else r.k1 + 1
    if k < 0 or k >= len(subs):
        return True
    lp = r.loops[0][1] if below else r.loops[-1][1]
    p = _interior_point(lp.bot if below else lp.top)
    inside = sum(1 for q in subs[k][2] if _inside(p, q.mid))
    return inside % 2 == 0


class Program:
    """One direction's features, registered with the pool, then written out as code."""

    def __init__(self, plan, pool, prefix, owner=None):
        self.plan, self.pool, self.prefix = plan, pool, prefix
        self.owner = owner                       # the feature id every Param of a secondary direction belongs to
        _name(plan, prefix)
        kx, ky, kz = plan["frame"].names
        self.h = {}
        self._polar = []
        if not prefix:
            from . import turned
            self._polar = turned.polar([r for r in plan["runs"] if r.fate == "feature"], plan["tol"])
        in_pattern = {id(r) for pt in self._polar for r in pt["runs"]}
        for r in plan["runs"]:
            if r.fate != "feature" or id(r) in in_pattern:
                continue
            fid = owner or r.id
            self.h[r.id] = (pool.add(kz, r.za, fid), pool.add(kz, r.zb, fid), _loop_handles(pool, r.bot, fid, kx, ky),
                            _loop_handles(pool, r.top, fid, kx, ky) if r.kind == "ruled" else None)
        # a turned body (turned.revolve): its half-section's corners are diameters and levels, its rounds radii
        self.rv = None
        rv = plan.get("revolve") if not prefix else None
        if rv is not None:
            fid = "base"
            lp = rv["loop"]
            eps = plan["tol"] / 10
            nodes = [(pool.add("d", 2 * n.p[0], fid) if n.p[0] > eps else None, pool.add(kz, n.p[1], fid),
                      pool.add("r", n.r, fid) if n.r > 0 else None) for n in lp.nodes]
            edges = [None if e.kind == "line" else (pool.add("r", e.R, fid), e.ccw, e.large) for e in lp.edges]
            self.rv = (pool.add(kx, rv["centre"][0], fid), pool.add(ky, rv["centre"][1], fid), nodes, edges)
        # polar patterns of equal holes (turned.polar): one pitch circle diameter instead of a position per hole
        self.patterns = []
        if not prefix:
            for i, pt in enumerate(self._polar):
                fid = f"pattern{i + 1}"
                r0 = pt["runs"][0]
                pt["id"] = fid
                pt["label"] = f"Pattern {i + 1}: {pt['n']} × Ø{_fmt(2 * r0.bot.r)} on Ø{_fmt(pt['pcd'])}"
                pt["h"] = (pool.add(kz, r0.za, fid), pool.add(kz, r0.zb, fid), pool.add(kx, pt["centre"][0], fid),
                           pool.add(ky, pt["centre"][1], fid), pool.add("P", pt["pcd"], fid), pool.add("d", 2 * r0.bot.r, fid))
                self.patterns.append(pt)
        self.in_pattern = {id(r): pt for pt in self.patterns for r in pt["runs"]}
        self.bh = {}
        for b in plan["blocks"]:
            if b["fate"] != "envelope":
                continue
            fid = owner or b["id"]
            self.bh[b["id"]] = (pool.add(kz, b["A"], fid), pool.add(kz, b["B"], fid),
                                [(_loop_handles(pool, lp, fid, kx, ky), dep) for lp, dep in b["loops"]])

    def ops(self):
        acc = [r for r in self.plan["runs"] if r.fate == "feature"]
        return sorted(acc, key=lambda r: (r.depth, -_volume_loop(r.bot, r.zb - r.za)))

    def code(self, var, stages: bool) -> tuple[list, list]:
        """(lines, features): code that leaves this direction's solid in `var`."""
        pool, plan = self.pool, self.plan
        L, feats = [], []
        first = True
        if self.rv is not None:
            cx, cy, nodes, edges = self.rv
            nd = ", ".join(f"({pool.code(d) + ' / 2' if d else 0}, {pool.code(z)}, {pool.code(rr) if rr else 0})"
                           for d, z, rr in nodes)
            ed = ", ".join("None" if e is None else f"({pool.code(e[0])}, {e[1]}, {e[2]})" for e in edges)
            feats.append(("base", "Turned body", "structure",
                          f"A half-section revolved about the {plan['frame'].names[2]} axis: its steps, chamfers, "
                          "grooves and rounds are the section's lines, arcs and corner radii."))
            L.append("# Turned body: the half-section revolved about the axis")
            L.append("_f = 'base'")
            L.append(f"{var} = turn(pl, {pool.code(cx)}, {pool.code(cy)}, [{nd}], [{ed}])")
            if stages:
                L.append(f"stages.append(Stage('base', {var}))")
            first = False
        for r in self.ops():
            pt = self.in_pattern.get(id(r))
            if pt is not None:
                if pt["runs"][0] is not r:
                    continue
                za, zb, cx, cy, ph, dh = pt["h"]
                zac, zbc = pool.code(za), pool.code(zb)
                lo, hi = zac, zbc
                if _opens(plan, r, below=True):
                    lo = f"{zac} - OVER" if zac != "0" else "-OVER"
                if _opens(plan, r, below=False):
                    hi = f"{zbc} + OVER"
                feats.append((pt["id"], pt["label"], "interface",
                              f"Cut: {pt['n']} equal holes on a pitch circle (a polar pattern), from "
                              f"{plan['frame'].names[2]} {_fmt(r.za)} to {_fmt(r.zb)}."))
                L.append(f"# {pt['label']}")
                L.append(f"_f = {pt['id']!r}")
                L.append(f"for _x, _y in polar({pool.code(cx)}, {pool.code(cy)}, {pool.code(ph)}, {pt['n']}, "
                         f"{_fmt(pt['phase_deg'])}):")
                L.append(f"    {var} = {var} - slab(disc({_at(lo)}, _x, _y, {pool.code(dh)}), {0 if lo == '0' else lo}, {hi})")
                if stages:
                    L.append(f"stages.append(Stage({pt['id']!r}, {var}))")
                continue
            za, zb, hb, ht = self.h[r.id]
            zac, zbc = pool.code(za), pool.code(zb)
            lo, hi = zac, zbc
            if not r.add and r.kind == "prism":
                if _opens(plan, r, below=True):
                    lo = f"{zac} - OVER" if zac != "0" else "-OVER"
                if _opens(plan, r, below=False):
                    hi = f"{zbc} + OVER"
            if r.kind == "prism":
                solid = f"slab({_loop_code(pool, hb, _at(lo))}, {0 if lo == '0' else lo}, {hi})"
            else:
                solid = (f"slab({_loop_code(pool, hb, _at(zac))}, {0 if zac == '0' else zac}, {zbc}, "
                         f"top={_loop_code(pool, ht, _at(zbc))})")
            what = "extrusion" if r.kind == "prism" else "ruled loft (walls slope from one sketch to the other)"
            feats.append((r.id, r.label, "interface" if (not r.add and r.bot.kind == "circle") else "structure",
                          f"{'Added' if r.add else 'Cut'}: a sketch {what} from {plan['frame'].names[2]} "
                          f"{_fmt(r.za)} to {_fmt(r.zb)}."))
            L.append(f"# {r.label}")
            L.append(f"_f = {r.id!r}")
            if first:
                L.append(f"{var} = {solid}")
                first = False
            else:
                L.append(f"{var} = {var} {'+' if r.add else '-'} {solid}")
            if stages:
                L.append(f"stages.append(Stage({r.id!r}, {var}))")
        for b in plan["blocks"]:
            if b["fate"] != "envelope":
                continue
            za, zb, loops = self.bh[b["id"]]
            zac, zbc = pool.code(za), pool.code(zb)
            parts = sorted(loops, key=lambda t: t[1])
            expr = None
            for h, dep in parts:
                s_ = f"slab({_loop_code(pool, h, _at(zac))}, {0 if zac == '0' else zac}, {zbc})"
                expr = s_ if expr is None else f"({expr}) {'+' if dep % 2 == 0 else '-'} {s_}"
            feats.append((b["id"], b["label"], "structure",
                          f"The outline that holds the part at every height from {plan['frame'].names[2]} {_fmt(b['A'])} to "
                          f"{_fmt(b['B'])}; what it does not show is cut by the sketches seen along the other directions."))
            L.append(f"# {b['label']}")
            L.append(f"_f = {b['id']!r}")
            if first:
                L.append(f"{var} = {expr}")
                first = False
            else:
                L.append(f"{var} = {var} + {expr}")
            if stages:
                L.append(f"stages.append(Stage({b['id']!r}, {var}))")
        return L, feats


def source(name, plans, tol, residual_ref=None, residual_cut_ref=None) -> tuple:
    """The recipe text: the main direction's features, intersected with each other direction's (when there are
    others), then the residual references. Returns (text, pool, programs)."""
    pool = Pool(tol)
    progs = []
    for i, plan in enumerate(plans):
        if i == 0:
            progs.append(Program(plan, pool, ""))
        else:
            ax = plan["frame"].names[2].lower()
            progs.append(Program(plan, pool, f"{ax}_", owner=f"along_{ax}"))
    labels = {}
    for pr in progs:
        for r in pr.plan["runs"]:
            if r.fate == "feature":
                labels[pr.owner or r.id] = r.label if not pr.owner else f"Seen along {pr.owner[-1].upper()}"
        for b in pr.plan["blocks"]:
            labels[pr.owner or b.get("id", "")] = b.get("label", "") if not pr.owner else f"Seen along {pr.owner[-1].upper()}"
    pool.solve(lambda f: labels.get(f, f))
    L, feats = [], []
    O = plans[0]["frame"].o
    for i, pr in enumerate(progs):
        fr = pr.plan["frame"]
        d, u = fr.d, fr.u
        L.append(f"pl = Plane(origin=O, x_dir=({_fmt(u[0])}, {_fmt(u[1])}, {_fmt(u[2])}), "
                 f"z_dir=({_fmt(d[0])}, {_fmt(d[1])}, {_fmt(d[2])}))")
        L.append("at = pl.offset")
        if i == 0:
            lines, fs = pr.code("body", True)
            L += lines
            feats += fs
        else:
            lines, _ = pr.code("seen", False)
            ax = fr.names[2]
            L.append(f"# Seen along {ax}: the sketches across {ax}, kept where they overlap the part so far")
            L += lines
            L.append(f"_f = {pr.owner!r}")
            L.append("body = body & seen")
            L.append(f"stages.append(Stage({pr.owner!r}, body))")
            feats.append((pr.owner, f"Seen along {ax}", "structure",
                          f"Sketches across {ax} (extrusions and cuts along {ax}), intersected with the part: they cut what "
                          f"the main direction cannot see, such as holes and roundings along {ax}."))
    if residual_ref or residual_cut_ref:
        feats.append(("kept", "Kept as the mesh", "structure",
                      "Material that does not read as a sketch along any direction (curved or freeform detail), kept "
                      "exactly as the mesh's own slices. Not driven by Params."))
        L.append("# Kept as the mesh: slices of the mesh where no sketch holds")
        L.append("_f = 'kept'")
        if residual_ref:
            L.append(f"body = body + self.reference({residual_ref!r})")
        if residual_cut_ref:
            L.append(f"body = body - self.reference({residual_cut_ref!r})")
        L.append("stages.append(Stage('kept', body))")
    params = []
    for p in pool.params:
        params.append(f"        Param({p['key']!r}, {p['label']!r}, {_fmt(p['value'])}, {_fmt(p['lo'])}, {_fmt(p['hi'])}, 0.01, "
                      f"'mm', 'form', {p['features'][0]!r}, {p['note']!r}, provenance='mesh'),")
    n_feat = sum(len(pr.ops()) for pr in progs)
    doc = (f"{name}: reconstructed from a mesh by Form Studio (Layer 2, sketches and extrusions, beta).\n\n"
           f"{n_feat} features read as sketches extruded or lofted between levels"
           + (f", seen along {', '.join(p['frame'].names[2] for p in plans)}" if len(plans) > 1 else "")
           + ". Every coordinate, level, radius and diameter is a Param computed from the mesh, measured from the "
           "origin O (pooled, snapped and mirrored where the tolerance allows; each Param says so)."
           + (" Material that does not read as a sketch is kept as the mesh's own slices (feature “kept”)."
              if residual_ref or residual_cut_ref else ""))
    text = "\n".join([
        '"""' + doc + '\n"""',
        "from build123d import Plane",
        "",
        "from form.recipes.base import Feature, Param, Recipe, Stage",
        "from form.recon.ops import disc, polar, profile, slab, turn",
        "",
        f"O = ({_fmt(O[0])}, {_fmt(O[1])}, {_fmt(O[2])})          # every coordinate is measured from here",
        f"OVER = {_fmt(max(4 * tol, 0.2))}          # how far a cut runs past a face it opens through",
        "",
        "",
        "class Design(Recipe):",
        f"    title = {(name + ' (reconstructed)')!r}",
        "    summary = 'Rebuilt from a mesh as sketches extruded between levels; every dimension is a Param.'",
        "    params = [",
        *params,
        "    ]",
        "    features = [",
        *[f"        Feature({fid!r}, {label!r}, {role!r}, {doc_!r})," for fid, label, role, doc_ in feats],
        "    ]",
        "",
        "    def build(self, v):",
        "        stages = []",
        *["        " + x for x in L],
        "        return stages",
    ]) + "\n"
    return text, pool, progs


# ---- the residual: the mesh's own slices where no sketch holds -------------------------------------------------------

def residual(plan, runs, tol, prog=None):
    """(add solid or None, cut solid or None, error) from these runs, built from the mesh's slices: between two
    neighbouring levels a loop's walls are exactly the planar pieces its triangles make, so each slab of a loop is a
    solid with planar faces, exactly the mesh's material there. Its levels are the Params' levels (snapped), and where
    it meets a feature its end follows the feature's sketch, so the two meet edge to edge."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    from . import solid
    fr = plan["frame"]
    size = plan["size"]
    eps = max(1e-7 * size, 1e-9)
    zmap = prog.pool.remap(fr.names[2]) if prog is not None else (lambda z: z)

    def poly(pts):
        clean = [pts[0]]
        for q in pts[1:]:
            if np.linalg.norm(q - clean[-1]) > eps:
                clean.append(q)
        if len(clean) > 1 and np.linalg.norm(clean[0] - clean[-1]) <= eps:
            clean.pop()
        if len(clean) < 3:
            return None
        mp = BRepBuilderAPI_MakePolygon()
        for q in clean:
            mp.Add(gp_Pnt(float(q[0]), float(q[1]), float(q[2])))
        mp.Close()
        if not mp.IsDone():
            return None
        f = BRepBuilderAPI_MakeFace(mp.Wire(), True)
        return f.Face() if f.IsDone() else None

    def w3(Q, z):
        return fr.o + Q[:, :1] * fr.u + Q[:, 1:2] * fr.w + zmap(z) * fr.d

    def w3m(Q, zm):
        return fr.o + Q[:, :1] * fr.u + Q[:, 1:2] * fr.w + zm * fr.d

    def piece(r, snap):
        """A kept slice; where it meets a feature its end follows the feature's sketch (snapped), so the boolean
        leaves no sliver between the mesh's straight segments and the sketch's arcs."""
        faces = []
        first_bot, last_top = r.loops[0][1].bot, r.loops[-1][1].top
        lo_z, hi_z = zmap(r.za), zmap(r.zb)
        if snap:
            first_bot = _onto(plan, r, first_bot, below=True, tol=tol, prog=prog)
            last_top = _onto(plan, r, last_top, below=False, tol=tol, prog=prog)
        for idx, (k, lp) in enumerate(r.loops):
            a, b = float(plan["subs"][k][0]), float(plan["subs"][k][1])
            B = w3m(first_bot, lo_z) if idx == 0 else w3(lp.bot, a)
            T = w3m(last_top, hi_z) if idx == len(r.loops) - 1 else w3(lp.top, b)
            n = len(B)
            for i in range(n):
                j = (i + 1) % n
                Q = np.array([B[i], B[j], T[j], T[i]])
                nrm = np.cross(Q[1] - Q[0], Q[3] - Q[0])
                ln = float(np.linalg.norm(nrm))
                if ln > 0 and abs(float((Q[2] - Q[0]) @ nrm)) / ln > 1e-10 * size:     # not flat: two triangles
                    for f in (poly(Q[[0, 1, 2]]), poly(Q[[0, 2, 3]])):
                        if f is not None:
                            faces.append(f)
                    continue
                f = poly(Q)
                if f is not None:
                    faces.append(f)
        for f in (poly(w3m(first_bot[::-1], lo_z)), poly(w3m(last_top, hi_z))):
            if f is not None:
                faces.append(f)
        sh, info = solid.shape_from_faces(faces, tol=max(1e-6, 1e-7 * size))
        return sh if info.get("solid") else None, info

    # runs that follow one another along a tube are one piece of the mesh: sewn once
    groups = []
    for r in sorted(runs, key=lambda r: (r.tube, r.k0)):
        if groups and groups[-1][-1].tube == r.tube and groups[-1][-1].k1 + 1 == r.k0:
            groups[-1].append(r)
        else:
            groups.append([r])
    adds, cuts = [], []
    for grp in groups:
        r = Run(grp[0].tube, grp[0].k0, grp[-1].k1, grp[0].za, grp[-1].zb, "curved", grp[0].depth,
                [x for g in grp for x in g.loops])
        sh, info = piece(r, prog is not None)
        if sh is None and prog is not None:             # moving the ends pinched the outline: the mesh's own points
            sh, info = piece(r, False)
        if sh is None:                                  # one slab at a time
            parts = []
            for k, lp in r.loops:
                a, b = float(plan["subs"][k][0]), float(plan["subs"][k][1])
                one, info = piece(Run(r.tube, k, k, a, b, "curved", r.depth, [(k, lp)]), False)
                if one is None and b - a < tol / 4:     # a sliver where the loop shrinks to an edge: left out (within
                    continue                            # a quarter of the tolerance of the mesh)
                if one is None:
                    return None, None, (f"a kept slice of the mesh did not close ({info.get('free_edges', 0)} free edges, "
                                        f"{fr.names[2]} {a:.4g} to {b:.4g})")
                parts.append(one)
            (adds if r.add else cuts).extend(parts)
            continue
        (adds if r.add else cuts).append(sh)
    return _fuse(adds), _fuse(cuts), None


def _touches(plan, r, below) -> bool:
    """Does an accepted feature start or end at this kept piece's bottom (or top) level?"""
    z = r.za if below else r.zb
    return any(q.fate == "feature" and (abs(q.zb - z) < 1e-9 or abs(q.za - z) < 1e-9) for q in plan["runs"])


def _onto(plan, r, P, below, tol, prog=None):
    """The points P of a kept piece's end moved onto the outline of any feature that starts or ends at that level,
    where they are within the tolerance of it: the piece and the feature then meet edge to edge and leave no sliver
    between the mesh's straight segments and the sketch's arcs."""
    z = r.za if below else r.zb
    outlines = []
    for q in plan["runs"]:
        if q.fate != "feature":
            continue
        h = prog.h.get(q.id) if prog is not None else None
        if abs(q.zb - z) < 1e-9:
            outlines.append(_outline(prog, h[3] if h[3] is not None else h[2]) if h else
                            sk.points(q.top if q.top is not None else q.bot, 64))
        if abs(q.za - z) < 1e-9:
            outlines.append(_outline(prog, h[2]) if h else sk.points(q.bot, 64))
    if not outlines:
        return P
    best = np.full(len(P), np.inf)
    out = P.copy()
    for S in outlines:
        Q = _nearest_on(P, S)
        d = np.linalg.norm(Q - P, axis=1)
        take = (d <= tol) & (d < best)
        out[take] = Q[take]
        best = np.minimum(best, d)
    return out


def _outline(prog, h):
    """A sketch as the Params build it (snapped values), as a dense closed polyline."""
    v = _loop_value(prog.pool, h)
    if v[0] == "circle":
        t = np.linspace(0, 2 * math.pi, 256, endpoint=False)
        return np.c_[v[1] + v[3] / 2 * np.cos(t), v[2] + v[3] / 2 * np.sin(t)]
    try:
        return sk.polyline(v[1], v[2], 64)
    except ValueError:
        return np.zeros((0, 2))


def _loop_value(pool, h):
    if h[0] == "circle":
        return ("circle", pool.value(h[1]), pool.value(h[2]), pool.value(h[3]))
    return ("path", [(pool.value(x), pool.value(y), pool.value(r) if r else 0.0) for x, y, r in h[1]],
            [None if e is None else (pool.value(e[0]), e[1], e[2]) for e in h[2]])


def _fuse(shapes):
    if not shapes:
        return None
    from build123d import Solid
    from . import solid
    out = Solid(shapes[0])
    if len(shapes) > 1:
        out = out.fuse(*[Solid(s) for s in shapes[1:]])
    try:
        return solid.unify(out.wrapped, 1e-6, 1e-7)
    except Exception:                                   # noqa: BLE001
        return out.wrapped


# ---- building and checking -------------------------------------------------------------------------------------------

def build_stages(src, refs=None):
    """Build a source as the Studio does; returns its stages (each Stage(feature, shape))."""
    import tempfile
    from ..recipes import SOURCE_PREFIX, load_source, meshsolid, source_id
    rid = source_id(src)
    meshsolid.set_paths(refs or {})
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{rid[len(SOURCE_PREFIX):]}.py"
            p.write_text(src, encoding="utf-8")
            rec = load_source(p, rid)
            return rec.build(rec.validate(rec.defaults())), rec
    finally:
        meshsolid.set_paths({})


def _local(plan, pts):
    fr = plan["frame"]
    rel = pts - fr.o
    return rel @ fr.d, np.c_[rel @ fr.u, rel @ fr.w]


def _surface_dist(plan, pts, loops, za, zb, tol):
    """Distance from 3-D points to the surface of a slab of `loops` (2-D polygons) between levels za and zb: to its walls
    (within its levels) or to its end faces (inside it)."""
    z, q = _local(plan, pts)
    d = np.full(len(pts), np.inf)
    inz = (z >= za - tol) & (z <= zb + tol)
    if inz.any():
        for S in loops:
            d[inz] = np.minimum(d[inz], sk._seg_dist(q[inz], S, np.roll(S, -1, axis=0)))
    inside = np.zeros(len(pts), dtype=np.int64)
    for S in loops:
        inside += _inside_many(q, S)
    cap = inside % 2 == 1
    d[cap] = np.minimum(d[cap], np.minimum(np.abs(z[cap] - za), np.abs(z[cap] - zb)))
    return d


def _blame(plans, pts, tol):
    """Each point where the rebuild is outside the tolerance is put on the feature or block whose surface is nearest
    to it (of every direction's plan). Returns [(plan, run or None, block index or None)] that got points."""
    if len(pts) > 3000:
        pts = pts[np.random.default_rng(0).choice(len(pts), 3000, replace=False)]
    cands, D = [], []
    for p in plans:
        for r in p["runs"]:
            if r.fate != "feature":
                continue
            d = _surface_dist(p, pts, [sk.points(r.bot, 16)], r.za, r.zb, tol)
            if r.top is not None:
                d = np.minimum(d, _surface_dist(p, pts, [sk.points(r.top, 16)], r.za, r.zb, tol))
            cands.append((p, r, None))
            D.append(d)
        for i, b in enumerate(p["blocks"]):
            if b["fate"] != "envelope":
                continue
            cands.append((p, None, i))
            D.append(_surface_dist(p, pts, [sk.points(lp, 16) for lp, _ in b["loops"]], b["A"], b["B"], tol))
    if not cands or not len(pts):
        return []
    D = np.array(D)
    j = D.argmin(axis=0)
    ok = D[j, np.arange(D.shape[1])] <= 6 * tol
    return [cands[k] for k in sorted(set(j[ok].tolist()))]


def face_meshes(shape, tol, per_face=40):
    """[(area, centroids (n, 3), triangle areas (n,))] per face of a shape, from one meshing of the whole shape."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    BRepMesh_IncrementalMesh(shape, tol, False, 0.35, True)
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face(ex.Current())
        ex.Next()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        n = tri.NbNodes()
        P = np.empty((n, 3))
        for i in range(1, n + 1):
            q = tri.Node(i).Transformed(trsf)
            P[i - 1] = (q.X(), q.Y(), q.Z())
        T = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.int64) - 1
        a = np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1) / 2
        C = P[T].mean(axis=1)
        tot = float(a.sum())
        if len(T) > per_face:                          # a fair sample of the face (by area) is enough to classify it
            pick = np.random.default_rng(len(T)).choice(len(T), per_face, replace=False, p=a / max(tot, 1e-300))
            C, a = C[pick], np.full(per_face, tot / per_face)
        out.append((tot, C, a))
    return out


def editable_share(final, features_only, tol) -> float:
    """Share of the final solid's surface area that lies on the surface the accepted features make (the rest is the
    residual's, kept as the mesh). A face counts when most of its area is within a fifth of the tolerance of it."""
    from . import distance, solid
    if features_only is None:
        return 0.0
    Pc, Tc = solid.tessellate(features_only, max(tol / 10, 1e-4))
    if not len(Tc):
        return 0.0
    md = distance.MeshDistance(Pc, Tc)
    faces = face_meshes(final, max(tol / 2, 1e-4))
    if not faces:
        return 0.0
    C = np.vstack([c for _, c, _ in faces])
    W = np.concatenate([w for _, _, w in faces])
    d = md.closest(C)[0]
    near = d <= max(tol / 5, 1e-4)
    tot = drv = 0.0
    i = 0
    for area, c, w in faces:
        n = len(c)
        tot += area
        if w[near[i:i + n]].sum() >= 0.5 * area:
            drv += area
        i += n
    del W
    return round(100 * drv / tot, 2) if tot else 0.0


def explained(plan) -> float:
    """Share of the wall area (sections' perimeter times height) that the plan reads as sketch features."""
    if not plan or plan.get("error"):
        return 0.0
    subs = plan["subs"]
    tot = got = 0.0
    for r in plan["runs"]:
        a = sum(float(np.linalg.norm(np.diff(np.r_[lp.mid, lp.mid[:1]], axis=0), axis=1).sum()) * (subs[k][1] - subs[k][0])
                for k, lp in r.loops)
        tot += a
        if r.fate == "feature":
            got += a
    return got / tot if tot > 0 else 0.0


def best_plan(V, F, tol, O, deadline=None, progress=None, cache=None):
    """The plan along the direction (of the three best) whose sketches explain the most of the walls. Plans read
    along world axes are left in `cache` (axis index -> plan) for the other directions to use."""
    N, A = meshmod.tri_normals(V, F)
    best = None
    for score, d in directions(N, A, k=3):
        if score < MIN_SCORE:
            continue
        p = read(V, F, tol, d=d, deadline=deadline, progress=progress, O=O)
        k = int(np.argmax(np.abs(d)))
        if cache is not None and abs(abs(d[k]) - 1) < 1e-9 and p is not None and not p.get("error"):
            cache[k] = p
        if p is None or p.get("error"):
            if best is None:
                best = (-1.0, p)
            continue
        e = explained(p)
        p["explained"] = e
        if best is None or e > best[0] + 1e-6:
            best = (e, p)
        if e >= 0.95:                                   # explains nearly every wall: no need to look further
            break
    return best[1] if best else {"error": "No direction has enough of the surface facing or running along it."}


def _secondary(V, F, tol, plan0, O, deadline, progress, cache=None):
    """Plans along the other world axes, every run that is not a sketch made an envelope (so each is a solid that
    holds the whole mesh)."""
    out = []
    d0 = plan0["frame"].d
    for k in range(3):
        d = np.eye(3)[k]
        if abs(d @ d0) > 0.5:
            continue
        p = (cache or {}).get(k)
        if p is None:
            p = read(V, F, tol, d=d, deadline=deadline, progress=None, O=O, min_score=0.0)
        if p is None or p.get("error"):
            continue
        envelopes(p, tol, superset=True)
        if any(b["fate"] != "envelope" for b in p["blocks"]):
            continue
        out.append(p)
    return out


def recipe(V, F, tol, name="part", limit=None, out_dir=None, progress=None, deadline=None, d=None) -> dict:
    """The program recipe of a mesh. Returns {"report", "source", "verified", "shape", "P", "T", "cmp", "refs",
    "params"}."""
    say = progress or (lambda x: None)
    t0 = time.perf_counter()
    limit = tol if limit is None else limit
    rep = {"beta": True, "method": "sketches and extrusions"}
    O = origin(V, tol)
    cache = {}
    if d is None:
        plan = best_plan(V, F, tol, O, deadline, progress, cache)
    else:
        plan = read(V, F, tol, d=d, deadline=deadline, progress=progress, O=O)
    if plan is None or plan.get("error"):
        rep["error"] = (plan or {}).get("error", "no plan")
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep}
    fr = plan["frame"]
    rep["direction"] = [round(float(x), 6) for x in fr.d]
    rep["levels"] = len(plan["levels"])
    rep["direction_score_pct"] = round(100 * plan["score"], 2)
    e = plan.get("explained", explained(plan))
    rep["walls_read_as_sketches_pct"] = round(100 * e, 1)
    if e < MIN_EXPLAINED:                              # mostly curved: the other layers do better, and sooner
        rep["error"] = (f"Only {100 * e:.0f}% of the walls read as sketches along the best direction; this part is mostly "
                        "curved surfaces, left to the surface fitting.")
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep}
    envelopes(plan, tol)
    out = Path(out_dir or ".")
    snap = ([(r.fate, r.why, r.block) for r in plan["runs"]], [blk["fate"] for blk in plan["blocks"]])
    blocks0 = list(plan["blocks"])
    block_runs = [list(b["runs"]) for b in blocks0]

    def restore():
        plan.pop("revolve", None)
        plan["blocks"] = list(blocks0)
        for blk, rs in zip(blocks0, block_runs):
            blk["runs"] = list(rs)
        for r, (f, w, k) in zip(plan["runs"], snap[0]):
            r.fate, r.why, r.block = f, w, k
        for blk, f in zip(plan["blocks"], snap[1]):
            blk["fate"] = f

    # a turned body first (turned.revolve: every slab one outer circle and at most one bore about one axis): its
    # half-section is one revolved sketch, holes off the axis stay features
    tries = []
    from . import turned
    rv = turned.revolve(plan, tol)
    if rv is not None:
        say({"stage": "layer2", "text": "A turned part: reading its half-section", "fraction": 0.3})
        plan["revolve"] = rv
        ids = {id(r) for r in rv["runs"]}
        for r in rv["runs"]:
            r.fate, r.why = "revolved", "part of the turned body"
        for b in blocks0:
            b["runs"] = [r for r in b["runs"] if id(r) not in ids]
        plan["blocks"] = [b for b in blocks0 if b["runs"]]
        t = _attempts(V, F, tol, limit, name, out, plan, [], say, deadline, "_r")
        t["revolve"] = True
        tries.append(t)
        rep["turned"] = {"profile_points": rv["points"], "corners": len(rv["loop"].nodes), "verified": bool(t["ok"]),
                         **({"hausdorff_mm": round(t["hausdorff"], 6)} if t.get("hausdorff") is not None else {})}
        if not (t["ok"] and t["edit"] >= 100.0):
            restore()

    # then the main direction alone (what reads as no sketch is kept as the mesh); then, when blocks of levels did
    # not read as sketches, again with the other directions carving them, and the best is the result
    if not tries or not tries[0]["ok"] or tries[0]["edit"] < 100.0:
        first = _attempts(V, F, tol, limit, name, out, plan, [], say, deadline, "")
        tries.append(first)
    else:
        first = tries[0]
    if not first.get("revolve") and plan["blocks"] and (not first["ok"] or first["edit"] < PROGRAM_GOOD) and \
            (deadline is None or time.perf_counter() < deadline):
        restore()
        say({"stage": "layer2", "text": "Reading the part along the other directions", "fraction": 0.6})
        others = _secondary(V, F, tol, plan, O, deadline, progress, cache)
        if others:
            second = _attempts(V, F, tol, limit, name, out, plan, others, say, deadline, "_x")
            second["others"] = True
            tries.append(second)
    best = max(tries, key=lambda t: (t["ok"], t["edit"], -t.get("hausdorff", 1e9)))
    if best.get("revolve") and best is not tries[-1]:
        plan["revolve"] = rv                       # the turned body was kept: the plan reports it
    if best is not tries[-1] and best["result"] is not None:
        # the plan's fates are the last try's: put back those of the one kept
        for r, f in zip(plan["runs"], best["fates"]):
            r.fate, r.why = f
    # the stepwise loop (stepwise.py): what the batch kept as the mesh, one feature at a time, kept only when the
    # residual drops; only for a result read along the main direction alone, as the plan now stands. It runs on a
    # verified result only; STEPWISE_S past the route's deadline only for a result the pipeline takes alone
    step_deadline = None if deadline is None else (max(deadline, time.perf_counter()) + STEPWISE_S if _alone(best)
                                                   else deadline)
    if best["result"] is not None and best["ok"] and best["edit"] < 100.0 and not best.get("others") and \
            (best is tries[-1] or not best.get("revolve")):
        from . import stepwise
        got = stepwise.refine(V, F, tol, limit, name, out, plan, best, say, step_deadline)
        rep["stepwise"] = got.get("steps", [])
        if got is not best and got["result"] is not None and got["edit"] > best["edit"]:
            best = got
            tries.append(got)
    # with other directions carving: drop each of their features that the result does not need (it still verifies,
    # as much of its surface comes from features, with fewer Params)
    if best["result"] is not None and best["ok"] and best.get("others") and best is tries[-1]:
        from . import stepwise
        got = stepwise.prune(V, F, tol, limit, name, out, plan, best, say, step_deadline)
        rep["pruned"] = got.get("pruned", [])
        if got is not best:
            best = got
            tries.append(got)
    # more of the surface from features is not worth fewer of the Params being dimensions: the other directions'
    # result is kept over the main direction's own verified result only when the share of its Params that are
    # dimensions does not drop and it has at most PARAM_GROWTH times as many Params
    if best.get("others") and first.get("ok") and first is not best and first["result"] is not None:
        ds_b, ds_f = _dimension_share(best["result"][7]), _dimension_share(first["result"][7])
        n_b, n_f = len(best["result"][7].params), len(first["result"][7].params)
        if ds_b < ds_f or n_b > PARAM_GROWTH * max(n_f, 1):
            rep["other_directions"] = {"kept": False, "feature_area_pct": best["edit"], "dimension_share_pct": ds_b,
                                       "why": f"{n_b} Params, {ds_b:g}% of them dimensions, against {n_f} and "
                                              f"{ds_f:g}% without it"}
            best = first
            for r, f in zip(plan["runs"], best["fates"]):
                r.fate, r.why = f
            for b in plan["blocks"]:
                b["fate"] = "kept"
            tries.append(first)
    rep["attempts"] = [x for t in tries for x in t["attempts"]]
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    if best["result"] is None:
        rep.setdefault("error", next((t["error"] for t in tries if t.get("error")), "The program did not build."))
        return {"report": rep}
    src, shape, ck, P, T, cmp, refs, pool, progs, feats_only, ok = best["result"]
    edit = best["edit"]
    kept = [r for r in plan["runs"] if r.fate == "kept"]
    feats = []
    for pr in progs:
        if pr.rv is not None:
            feats.append({"id": "base", "label": "Turned body", "direction": pr.plan["frame"].names[2], "kind": "revolve",
                          "op": "add", "profile": f"{len(pr.rv[2])} corners"})
        for pt in pr.patterns:
            r0 = pt["runs"][0]
            feats.append({"id": pt["id"], "label": pt["label"], "direction": pr.plan["frame"].names[2],
                          "kind": "polar pattern", "op": "cut", "count": pt["n"], "pcd_mm": round(pt["pcd"], 4),
                          "from_mm": round(r0.za, 4), "to_mm": round(r0.zb, 4)})
        for r in pr.ops():
            if id(r) in pr.in_pattern:
                continue
            feats.append({"id": r.id, "label": r.label, "direction": pr.plan["frame"].names[2],
                          "kind": "extrusion" if r.kind == "prism" else "ruled loft", "op": "add" if r.add else "cut",
                          "from_mm": round(r.za, 4), "to_mm": round(r.zb, 4),
                          "sketch": "circle" if r.bot.kind == "circle" else f"{len(r.bot.nodes)} corners"})
        for b in pr.plan["blocks"]:
            if b["fate"] == "envelope":
                feats.append({"id": b["id"], "label": b["label"], "direction": pr.plan["frame"].names[2], "kind": "block",
                              "op": "add", "from_mm": round(b["A"], 4), "to_mm": round(b["B"], 4)})
    rep.update({"kind": "program", "base": "sketches and extrusions", "valid": ck["valid"], "solids": ck["solids"],
                "volume_mm3": round(ck["volume_mm3"], 4), "verified": bool(ok), "editable_pct": edit,
                "driven_by_params_pct": edit, "params": len(pool.params),
                "origin": [round(float(x), 6) for x in plan["frame"].o],
                "param_table": [{k: v for k, v in q.items()} for q in pool.params],
                "directions": [p.plan["frame"].names[2] for p in progs],
                "features": feats,
                "kept": [{"op": "add" if r.add else "cut", "from_mm": round(r.za, 4), "to_mm": round(r.zb, 4), "why": r.why,
                          "label": r.label or None, "size_mm": [round(float(x), 3) for x in np.ptp(r.loops[0][1].mid, axis=0)]}
                         for r in kept][:60],
                "regularised": _regularised(pool),
                **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")}})
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    if not ok:
        rep["error"] = (f"The program builds, but it is {cmp['hausdorff_mm']:.4f} mm from the mesh (limit {limit:.4f} mm)"
                        if ck["valid"] else "The program builds an invalid solid.")
    return {"report": rep, "source": src, "verified": ok, "shape": shape.wrapped, "P": P, "T": T, "cmp": cmp, "refs": refs,
            "params": pool.params, "plan": plan}


PARAM_GROWTH = 1.5       # how many times the Params the other directions may bring (see recipe)


def _alone(t) -> bool:
    """Is this try a result the pipeline takes without building the slower layers (pipeline.PROGRAM_ENOUGH)?"""
    from .pipeline import PROGRAM_ENOUGH
    return bool(t.get("ok") and t.get("edit", 0.0) >= PROGRAM_ENOUGH)


def _dimension_share(pool) -> float:
    ps = pool.params
    return round(100.0 * sum(1 for p in ps if is_dimension(p["key"], p["label"], "mm")) / len(ps), 1) if ps else 0.0


STEPWISE_S = 60.0        # seconds past the deadline the stepwise loop may take on a verified result the pipeline
                         # takes alone (_alone): the slower layers are then not built
PROGRAM_GOOD = 80.0      # % of the surface from features under which the other directions are tried as well. Measured
                         # (docs/RECON_BENCH.md): above it they gain surface but cost the share of dimension Params


def _attempts(V, F, tol, limit, name, out, plan, others, say, deadline, tag) -> dict:
    """Build the plan (with `others` carving its blocks), compare with the mesh, move what the comparison blames into
    the residual or the blocks, and build again, a few times. Returns {"result", "ok", "edit", "attempts", "fates"}."""
    from . import solid, verify
    from .pipeline import _step
    attempts, result, error = [], None, None
    for attempt in range(6):
        if deadline is not None and attempt and time.perf_counter() > deadline:
            attempts.append({"stopped": "the time budget ran out"})
            break
        for b in plan["blocks"]:
            if not others:                             # nothing else can carve a block: keep it as the mesh
                b["fate"] = "kept"
            if b["fate"] == "kept":
                for r in b["runs"]:
                    r.fate = "kept"
        kept = [r for r in plan["runs"] if r.fate == "kept"]
        refs = {}
        ra = f"{name}_kept{tag}.step" if any(r.add for r in kept) else None
        rc = f"{name}_kept{tag}_cut.step" if any(not r.add for r in kept) else None
        used = [plan] + ([p for p in others] if any(b["fate"] == "envelope" for b in plan["blocks"]) else [])
        if not any(r.fate == "feature" for r in plan["runs"]) and not any(b["fate"] == "envelope" for b in plan["blocks"]) \
                and not plan.get("revolve"):
            error = "No part of the mesh reads as a sketch."
            break
        src, pool, progs = source(name, used, tol, ra, rc)
        if kept:
            say({"stage": "layer2", "text": f"Keeping {len(kept)} pieces as the mesh's own slices", "fraction": 0.4 + 0.08 * attempt})
            add, cut, err = residual(plan, kept, tol, progs[0])
            if err:
                error = f"The residual did not build: {err}."
                break
            for ref, sh in ((ra, add), (rc, cut)):
                if ref and sh is not None:
                    _step(sh, out / ref)
                    refs[ref] = str(out / ref)
            if (ra and add is None) or (rc and cut is None):
                src, pool, progs = source(name, used, tol, ra if add is not None else None, rc if cut is not None else None)
        n_ops = sum(len(p.ops()) for p in progs)
        say({"stage": "layer2", "text": f"Building {n_ops} sketch features and comparing with the mesh",
             "fraction": 0.5 + 0.08 * attempt})
        try:
            stages, _rec = build_stages(src, refs)
        except Exception as e:                         # noqa: BLE001
            fid, tb = None, e.__traceback__
            while tb is not None:
                if tb.tb_frame.f_code.co_name == "build" and "_f" in tb.tb_frame.f_locals:
                    fid = tb.tb_frame.f_locals["_f"]
                tb = tb.tb_next
            attempts.append({"error": f"{type(e).__name__}: {e}"[:300], "feature": fid})
            if not _drop(plan, others, fid, f"its feature did not build ({type(e).__name__})"):
                break
            continue
        shape = stages[-1].shape
        feats_only = next((s.shape for s in reversed(stages) if s.feature != "kept"), None) if refs else None
        ck = solid.check(shape.wrapped)
        fl = []
        P, T = solid.tessellate(shape, max(tol / 10, 1e-4), faces_out=fl)
        diag = float(np.linalg.norm(np.ptp(V, axis=0)))
        cmp = verify.compare(V, F, P, T, spacing=max(diag / 80, 1e-3), shape=shape.wrapped, check_above=limit, faces=fl)
        if ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit:     # a quick look first, then in full
            cmp = verify.compare(V, F, P, T, spacing=max(diag / 200, 1e-3), shape=shape.wrapped, check_above=limit,
                                 faces=fl)
        ok = ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit
        attempts.append({"features": n_ops, "directions": len(used), "kept_pieces": len(kept),
                         "hausdorff_mm": round(cmp["hausdorff_mm"], 6), "valid": ck["valid"], "solids": ck["solids"]})
        result = (src, shape, ck, P, T, cmp, refs, pool, progs, feats_only, ok)
        if ok:
            break
        bad = P[cmp["_rec_dev"] > limit]
        tri_bad = cmp["_tri_dev"] > limit
        if tri_bad.any():
            bad = np.r_[bad.reshape(-1, 3), V[F[tri_bad]].mean(axis=1)]
        if not ck["valid"] or ck["solids"] != 1:
            bad = np.r_[bad.reshape(-1, 3), P[::max(1, len(P) // 2000)]]
        moved = 0
        touched = set()
        for p, r, bi in _blame([plan] + others, bad.reshape(-1, 3), limit):
            if r is not None:
                r.fate = "kept" if p is plan else "envelope"
                r.why = f"with it the rebuild was {cmp['hausdorff_mm']:.4f} mm from the mesh"
                touched.add(id(p))
                moved += 1
            elif p is plan:
                p["blocks"][bi]["fate"] = "kept"
                moved += 1
            else:                                      # a block of another direction that does not carve: drop it
                others = [o for o in others if o is not p]
                moved += 1
        for p in others:
            if id(p) in touched:
                envelopes(p, tol, superset=True)
        others = [p for p in others if all(b["fate"] == "envelope" for b in p["blocks"])]
        if not moved:
            break
    out_ = {"result": result, "attempts": attempts, "error": error, "ok": bool(result and result[-1]), "edit": 0.0,
            "fates": [(r.fate, r.why) for r in plan["runs"]], "others_list": list(others)}
    if result is not None:
        src, shape, ck, P, T, cmp, refs, pool, progs, feats_only, ok = result
        say({"stage": "layer2", "text": "Measuring how much of the surface the Params drive", "fraction": 0.9})
        out_["edit"] = 100.0 if not refs else editable_share(shape.wrapped, feats_only.wrapped if feats_only is not None else None, tol)
        out_["hausdorff"] = cmp["hausdorff_mm"]
    return out_


def _drop(plan, others, fid, why) -> bool:
    """A feature or block that failed to build: the main direction keeps it as the mesh, another direction makes it
    part of an envelope (or is dropped). Returns False when there was nothing to drop."""
    if fid is None:
        return False
    for r in plan["runs"]:
        if r.id == fid and r.fate == "feature":
            r.fate, r.why = "kept", why
            return True
    for b in plan["blocks"]:
        if b.get("id") == fid and b["fate"] == "envelope":
            b["fate"] = "kept"
            return True
    for p in list(others):
        hit = [r for r in p["runs"] if r.id == fid and r.fate == "feature"]
        if hit:                                        # another direction's feature: part of its block instead
            for r in hit:
                r.fate, r.block = "envelope", -1
            envelopes(p, plan.get("tol", 0.02), superset=True)
            return True
        if fid == f"along_{p['frame'].names[2].lower()}" or any(b.get("id") == fid for b in p["blocks"]):
            others.remove(p)
            return True
    return False


def _regularised(pool) -> dict:
    ps = pool.params
    return {"params": len(ps), "values_pooled": int(sum(p["uses"] for p in ps)),
            "snapped": sum(1 for p in ps if "snapped" in p["note"]),
            "mirrored": sum(1 for p in ps if p["mirrored"]),
            "standard_sizes": sum(1 for p in ps if p["kind"] == "d" and ("ISO" in p["note"] or "drill" in p["note"]))}


# ---- the editability sweep -------------------------------------------------------------------------------------------

DIMENSION_UNITS = ("mm", "°", "deg")
COORDINATE_LABEL = re.compile(r"^([XYUW])\s+(±)?")     # the program route's corner coordinates: "X 12.5 · Step 4"
DIMENSION_MOVE = 0.5                                    # a dimension counts when it moves this far and still builds


def is_dimension(key: str, label: str, unit: str) -> bool:
    """A Param a person would call a dimension: a length, diameter, radius, angle or level, in mm or degrees.
    The program route's Params count this way: radii, diameters and levels (Z, Level) are dimensions; a mirrored
    coordinate ("X ±30") is half of a symmetric width, so it is one too; a plain X, Y, U or W coordinate of a sketch
    corner ("X 12.5 · Step 4") is a position, not a dimension. A scale or a count is never one."""
    if str(unit or "") not in DIMENSION_UNITS:
        return False
    m = COORDINATE_LABEL.match(str(label or "").strip())
    return m is None or bool(m.group(2))


def movable_dimensions(src, refs=None, deadline=None, move: float = DIMENSION_MOVE) -> dict:
    """The Params that are real dimensions (is_dimension) and can move at least `move` (mm or degrees) inside their
    range with the recipe still building one valid solid. Each is rebuilt once at default + move (or - move when the
    range has no room above). A dimension not checked before the deadline is not counted.
    Returns {"params", "dimensions", "movable", "checked", "unchecked", "keys", "move"}."""
    import tempfile
    from ..recipes import SOURCE_PREFIX, load_source, meshsolid, source_id
    rid = source_id(src)
    out = {"params": 0, "dimensions": 0, "movable": 0, "checked": 0, "unchecked": 0, "keys": [], "move": move}
    meshsolid.set_paths(refs or {})
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{rid[len(SOURCE_PREFIX):]}.py"
            p.write_text(src, encoding="utf-8")
            rec = load_source(p, rid)
            base = rec.defaults()
            out["params"] = len(rec.params)
            for prm in rec.params:
                if not is_dimension(prm.key, prm.label, prm.unit):
                    continue
                out["dimensions"] += 1
                if prm.max - prm.default >= move - 1e-9:
                    x = prm.default + move
                elif prm.default - prm.min >= move - 1e-9:
                    x = prm.default - move
                else:
                    continue                           # its range is narrower than a useful move
                if deadline is not None and time.perf_counter() > deadline:
                    out["unchecked"] += 1
                    continue
                out["checked"] += 1
                try:
                    sh = rec.build(rec.validate({**base, prm.key: x}))[-1].shape
                    good = sh.is_valid and len(sh.solids()) == getattr(rec, "solids", 1)
                except Exception:                      # noqa: BLE001
                    good = False
                if good:
                    out["movable"] += 1
                    out["keys"].append(prm.key)
    finally:
        meshsolid.set_paths({})
    return out


def sweep(src, refs=None, keys=None, samples: int = 5, deadline=None) -> list:
    """For each Param (or those in `keys`): does changing it change the solid, and across how much of its range does
    the recipe still build one valid solid? Each Param is set to `samples` values spread over its range (the others at
    their defaults). Returns [{"key", "label", "changes", "rebuilds_pct", "tried"}]."""
    import tempfile
    from ..recipes import SOURCE_PREFIX, load_source, meshsolid, source_id
    rid = source_id(src)
    out = []
    meshsolid.set_paths(refs or {})
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{rid[len(SOURCE_PREFIX):]}.py"
            p.write_text(src, encoding="utf-8")
            rec = load_source(p, rid)
            base = rec.defaults()
            s0 = rec.build(rec.validate(base))[-1].shape
            v0, a0 = s0.volume, s0.area
            for prm in rec.params:
                if keys is not None and prm.key not in keys:
                    continue
                if deadline is not None and time.perf_counter() > deadline:
                    break
                ok = moved = 0
                vals = [prm.min + (prm.max - prm.min) * t for t in np.linspace(0.0, 1.0, samples)]
                for x in vals:
                    try:
                        sh = rec.build(rec.validate({**base, prm.key: x}))[-1].shape
                        good = sh.is_valid and len(sh.solids()) == getattr(rec, "solids", 1)
                    except Exception:                  # noqa: BLE001
                        good, sh = False, None
                    if good:
                        ok += 1
                        if abs(x - prm.default) > 1e-9 and (abs(sh.volume - v0) > 1e-6 * max(v0, 1.0)
                                                            or abs(sh.area - a0) > 1e-6 * max(a0, 1.0)):
                            moved += 1
                out.append({"key": prm.key, "label": prm.label, "changes": moved > 0,
                            "rebuilds_pct": round(100.0 * ok / len(vals), 1), "tried": len(vals)})
    finally:
        meshsolid.set_paths({})
    return out
