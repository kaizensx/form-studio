"""Layer 1, step one: split the mesh into regions that each lie on one analytic surface. numpy and scipy only.

1. Flat pieces: triangles joined across edges where the surface does not bend (under 0.25 degrees) and that share one
   plane within the tolerance.
2. Curved regions grow from seeds across smooth edges (under 40 degrees): the seed and its neighbours are fitted with
   the simplest surface that holds them (cylinder, then cone, sphere, torus); a neighbouring piece joins when every one
   of its vertices is within the tolerance of that surface and its facets face the same way as the surface. The surface
   is refitted as the region grows.
3. Flat pieces that are left become planes, unless they look like the facets of a curved surface (most of their border
   bends smoothly into other leftover pieces). Everything else stays as frozen facets.

A region is accepted only if its vertices are within `tol` of the surface and its facet centres within `tol` plus the
chord error a mesh of that edge length must have on that curvature.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from . import fit as fitmod
from .mesh import edges, tri_normals

FLAT_DEG = 0.25
SMOOTH_DEG = 40.0
CURVED = ("cylinder", "cone", "sphere", "torus")
NORMAL_DEG = 20.0          # a facet may lean this far from the fitted surface's normal (chord of a coarse curve)
FREEFORM_SEEDS = 24        # seeds tried in a smooth part before it is judged freeform


@dataclass
class Region:
    id: int
    kind: str                       # plane | cylinder | cone | sphere | torus | facet
    tris: np.ndarray
    prim: fitmod.Prim | None = None
    area: float = 0.0
    info: dict = field(default_factory=dict)

    @property
    def parametric(self) -> bool:
        return self.kind != "facet"


class Adjacency:
    def __init__(self, V, F):
        self.V, self.F = V, F
        self.N, self.A = tri_normals(V, F)
        E, tri, eo, he = edges(F)
        self.E = E
        order = np.argsort(eo, kind="stable")
        eo_s, tri_s = eo[order], tri[order]
        nb = np.flatnonzero(eo_s[1:] == eo_s[:-1])
        cnt = np.bincount(eo, minlength=len(E))
        ok = cnt[eo_s[nb]] == 2                         # manifold edges only
        self.t1, self.t2, self.e = tri_s[nb][ok], tri_s[nb + 1][ok], eo_s[nb][ok]
        c = np.clip(np.einsum("ij,ij->i", self.N[self.t1], self.N[self.t2]), -1, 1)
        self.angle = np.degrees(np.arccos(c))
        self.len = np.linalg.norm(V[E[self.e, 0]] - V[E[self.e, 1]], axis=1)
        # neighbour lists
        n = len(F)
        self.nbr = [[] for _ in range(n)]
        for k, (a, b) in enumerate(zip(self.t1.tolist(), self.t2.tolist())):
            self.nbr[a].append((b, k))
            self.nbr[b].append((a, k))


def _components(n, a, b):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n))
    return connected_components(g, directed=False)[1]


def _accept(prim, V, F, tris, N, tol, check_normals=True, size=None) -> bool:
    if prim is None:
        return False
    if size is not None and prim.kind != "plane":
        big = max(prim.p.get("r", 0.0), prim.p.get("R", 0.0))
        if big > 2 * size:
            return False
    vid = np.unique(F[tris])
    if np.abs(prim.dist(V[vid])).max() > tol:
        return False
    a, b, c = V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]]
    cen = (a + b + c) / 3
    dc = np.abs(prim.dist(cen))
    if prim.kind != "plane":
        if np.any(dc > tol + chord_error(prim, a, b, c)):
            return False
    elif dc.max() > tol:
        return False
    if check_normals:
        sn = prim.normal(cen)
        cosang = np.abs(np.einsum("ij,ij->i", sn, N[tris]))
        if cosang.min() < math.cos(math.radians(NORMAL_DEG if prim.kind != "plane" else 1.0)):
            return False
        # one region must face one way relative to the surface (no folding over)
        sg = np.sign(np.einsum("ij,ij->i", sn, N[tris]))
        if abs(sg.sum()) != len(sg):
            return False
    return True


def chord_error(prim, a, b, c) -> np.ndarray:
    """How far a flat triangle with corners on the surface may sit from it: the sagitta of its longest edge across
    the curvature (along a cylinder or cone axis the surface is straight, so only the part across the axis counts),
    with 50% margin."""
    E = [b - a, c - b, a - c]
    if prim.kind in ("cylinder", "cone"):
        ax = prim.p["a"]
        E = [e - (e @ ax)[:, None] * ax for e in E]
    L = np.maximum(np.maximum(np.linalg.norm(E[0], axis=1), np.linalg.norm(E[1], axis=1)), np.linalg.norm(E[2], axis=1))
    return 1.5 * L * L / (8 * _min_radius(prim))


def _min_radius(prim) -> float:
    p = prim.p
    if prim.kind == "torus":
        return max(min(p["r"], p["R"] - p["r"]), 1e-6)
    if prim.kind == "cone":
        return max(abs(p["r"]), 1e-3)
    return max(p.get("r", 1e9), 1e-6)


def segment(V, F, tol=0.02, budget_s=60.0, progress=None) -> tuple[list[Region], dict]:
    t0 = time.perf_counter()
    adj = Adjacency(V, F)
    size = float(np.linalg.norm(np.ptp(V, axis=0)))
    N, A = adj.N, adj.A
    n = len(F)
    # 1. flat pieces
    flat = adj.angle < FLAT_DEG
    lab = _components(n, adj.t1[flat], adj.t2[flat])
    pieces = {}
    for t, l in enumerate(lab.tolist()):
        pieces.setdefault(l, []).append(t)
    unit_of = np.empty(n, dtype=np.int64)
    units = []
    for l, ts in pieces.items():
        ts = np.array(ts)
        if len(ts) > 1:
            pr = fitmod.fit_plane(V[np.unique(F[ts])], N[ts])
            if not _accept(pr, V, F, ts, N, tol):        # a gently curved piece: let its triangles go their own way
                for t in ts:
                    unit_of[t] = len(units)
                    units.append(np.array([t]))
                continue
        unit_of[ts] = len(units)
        units.append(ts)
    nu = len(units)
    # unit adjacency over smooth edges, and how much of each unit's border is smooth
    ua, ub = unit_of[adj.t1], unit_of[adj.t2]
    cross = ua != ub
    smooth = cross & (adj.angle < SMOOTH_DEG)
    border = np.zeros(nu)
    np.add.at(border, ua[cross], adj.len[cross])
    np.add.at(border, ub[cross], adj.len[cross])
    unbr = [set() for _ in range(nu)]
    pairlen = {}
    for a, b, ln in zip(ua[smooth].tolist(), ub[smooth].tolist(), adj.len[smooth].tolist()):
        unbr[a].add(b)
        unbr[b].add(a)
        pairlen[(a, b)] = pairlen.get((a, b), 0.0) + ln
        pairlen[(b, a)] = pairlen.get((b, a), 0.0) + ln
    uarea = np.array([A[u].sum() for u in units])
    owner = -np.ones(nu, dtype=np.int64)           # region index per unit
    regions: list[Region] = []
    tried = np.zeros(nu, dtype=bool)
    stats = {"fits": 0, "seeds": 0, "timed_out": False}

    def verts_of(us):
        ts = np.concatenate([units[u] for u in us])
        return ts

    axes = []                                      # axes of the surfaces found so far: hints for the next fits

    def note_axis(prim, area):
        if prim.kind in ("cylinder", "cone", "torus"):
            if not any(abs(abs(a @ prim.p["a"]) - 1) < 1e-6 and np.linalg.norm(np.cross(prim.p["o"] - o, a)) < 1e-4
                       for _, (o, a) in axes):
                axes.append((area, (prim.p["o"].copy(), prim.p["a"].copy())))

    def try_fit(ts, kinds=("cylinder", "cone", "sphere", "torus")):
        vid = np.unique(F[ts])
        if len(vid) < 8:
            return None
        P = V[vid]
        # vertex normals for fitting: area-weighted from the region's own triangles
        vn = np.zeros((len(V), 3))
        for i in range(3):
            np.add.at(vn, F[ts, i], N[ts] * A[ts, None])
        Nv = vn[vid]
        Nv /= np.maximum(np.linalg.norm(Nv, axis=1), 1e-300)[:, None]
        if len(P) > 160:                               # fit on a spread-out subset; acceptance checks every vertex
            pick = np.random.default_rng(len(P)).choice(len(P), 160, replace=False)
            P, Nv = P[pick], Nv[pick]
        hints = [ax for _, ax in sorted(axes, key=lambda t: -t[0])[:6]]
        for k in kinds:
            stats["fits"] += 1
            pr = fitmod.fit(k, P, Nv, hints, good=0.5 * tol)
            if _accept(pr, V, F, ts, N, tol, size=size):
                return pr
        return None

    def grow(members, prim):
        grown_at = len(members)
        changed = True
        while changed:
            changed = False
            front = list(dict.fromkeys(b for u in members for b in unbr[u] if owner[b] < 0 and b not in members))
            for b in front:
                if _accept(prim, V, F, units[b], N, tol):
                    members.add(b)
                    changed = True
            if len(members) > 1.3 * grown_at:
                p2 = try_fit(verts_of(sorted(members)), (prim.kind,))
                if p2 is not None:
                    prim = p2
                grown_at = len(members)
        us = sorted(members)
        if len(us) < 2:
            return None
        ts = verts_of(us)
        prim = try_fit(ts, (prim.kind,)) or prim
        if not _accept(prim, V, F, ts, N, tol):
            return None
        return np.array(us), prim

    # 2. curved regions, seeded where the border bends smoothly the most
    sl = np.zeros(nu)
    np.add.at(sl, ua[smooth], adj.len[smooth])
    np.add.at(sl, ub[smooth], adj.len[smooth])
    smooth_frac = sl / np.maximum(border, 1e-300)
    order = np.argsort(-uarea, kind="stable")             # big pieces first: a strip of a cylinder says more than a speck
    # smooth parts of the mesh (bends under 30 degrees): where the first seeds of a part only find small pieces of
    # different surfaces, the part is freeform (a sculpt, a scan) and is left to the B-spline fit (freeform.py)
    from .freeform import SMOOTH_DEG as _FF_DEG
    smooth_part = _components(nu, ua[cross & (adj.angle < _FF_DEG)], ub[cross & (adj.angle < _FF_DEG)])
    part_area = np.bincount(smooth_part, weights=uarea)
    part_seeds = np.zeros(len(part_area), dtype=np.int64)
    part_found = np.zeros(len(part_area))
    part_big = np.zeros(len(part_area))
    freeform_parts = set()
    for k_seed, s in enumerate(order.tolist()):
        if time.perf_counter() - t0 > budget_s:
            stats["timed_out"] = True
            break
        if owner[s] >= 0 or tried[s] or smooth_frac[s] < 0.3:
            continue
        sp = int(smooth_part[s])
        if sp in freeform_parts:
            continue
        if part_seeds[sp] >= FREEFORM_SEEDS and part_big[sp] < 0.1 * part_area[sp] and part_found[sp] < 0.5 * part_area[sp]:
            freeform_parts.add(sp)
            continue
        part_seeds[sp] += 1
        tried[s] = True
        stats["seeds"] += 1
        if progress and stats["seeds"] % 25 == 0:
            progress({"stage": "layer1", "text": f"Fitting surfaces: {len(regions)} found", "fraction": min(0.95, k_seed / nu)})
        # seed: grow rings across smooth borders until there is enough to fit
        seed = [s]
        ring = [s]
        nv = len(np.unique(F[units[s]]))
        while (len(seed) < 6 or nv < 30) and len(seed) < 60:
            nxt = [b for u in ring for b in unbr[u] if owner[b] < 0 and b not in seed]
            nxt = list(dict.fromkeys(nxt))
            if not nxt:
                break
            seed += nxt[: 60 - len(seed)]
            ring = nxt
            nv = len(np.unique(F[verts_of(seed)]))
        # every kind that holds the seed is grown; the one that covers the most area wins (the simpler kind on a tie)
        best = None
        for kind in CURVED:
            prim, sd = None, seed
            for size in dict.fromkeys((len(seed), max(2, len(seed) // 3), 4, 2)):
                if size > len(seed) or size < 2:
                    continue
                ts = verts_of(seed[:size])
                if len(np.unique(F[ts])) >= 8:
                    prim = try_fit(ts, (kind,))
                    if prim is not None:
                        sd = seed[:size]
                        break
            if prim is None:
                continue
            got = grow(set(sd), prim)
            if got is None:
                continue
            area = float(uarea[got[0]].sum())
            if best is None or area > best[2] * 1.03:
                best = (got[0], got[1], area)
            inside = set(got[0].tolist())
            if not any(owner[b] < 0 and b not in inside for u in inside for b in unbr[u]):
                break                                  # it took every smooth neighbour: no other kind can cover more
        if best is None:
            continue
        us, prim, _ = best
        ts = verts_of(us)
        rid = len(regions)
        regions.append(Region(rid, prim.kind, ts, prim, float(A[ts].sum())))
        owner[us] = rid
        note_axis(prim, float(A[ts].sum()))
        part_found[sp] += float(A[ts].sum())
        part_big[sp] = max(part_big[sp], float(A[ts].sum()))

    # neighbouring curved regions that one surface holds become one region (a seed can stop short at a seam)
    merged = True
    while merged and time.perf_counter() - t0 < budget_s:
        merged = False
        for r in sorted(regions, key=lambda r: -r.area):
            if r.kind == "gone":
                continue
            mine = np.flatnonzero(owner == r.id)
            nbs = {int(owner[b]) for u in mine for b in unbr[u] if owner[b] >= 0 and owner[b] != r.id}
            for q in sorted(nbs):
                o = regions[q]
                if o.kind == "gone":
                    continue
                ts = np.concatenate([r.tris, o.tris])
                kinds = list(dict.fromkeys([r.kind, o.kind] + list(CURVED)))
                pr = try_fit(ts, kinds)
                if pr is not None:
                    r.tris, r.prim, r.kind, r.area = ts, pr, pr.kind, float(A[ts].sum())
                    owner[owner == q] = r.id
                    o.kind = "gone"
                    merged = True
            if merged:
                break
    keep = [r for r in regions if r.kind != "gone"]
    remap = {r.id: i for i, r in enumerate(keep)}
    for i, r in enumerate(keep):
        r.id = i
    owner = np.array([remap.get(int(o), -1) if o >= 0 else -1 for o in owner], dtype=np.int64)
    regions = keep

    # where two curved regions meet tangentially, a strip near the seam fits both; give it to the one it fits better
    for _sweep in range(30):
        moved = set()
        for u in np.flatnonzero(owner >= 0).tolist():
            r = regions[owner[u]]
            vu = V[np.unique(F[units[u]])]
            dr = np.abs(r.prim.dist(vu)).max()
            if dr < 1e-6:
                continue
            for b in unbr[u]:
                if owner[b] < 0 or owner[b] == owner[u]:
                    continue
                q = regions[owner[b]]
                dq = np.abs(q.prim.dist(vu)).max()
                if dq < 0.5 * dr and _accept(q.prim, V, F, units[u], N, tol):
                    moved.update((r.id, q.id))
                    owner[u] = q.id
                    break
        if not moved:
            break
        for rid in moved:
            r = regions[rid]
            us = np.flatnonzero(owner == rid)
            ts = verts_of(us) if len(us) else np.zeros(0, dtype=np.int64)
            pr = try_fit(ts, (r.kind,)) if len(us) else None
            r.tris, r.area = ts, float(A[ts].sum()) if len(ts) else 0.0
            if pr is not None:
                r.prim = pr
    for r in regions:                                  # a region emptied by the exchange, or no longer one surface
        us = np.flatnonzero(owner == r.id)
        if not len(us) or not _accept(r.prim, V, F, r.tris, N, tol):
            owner[us] = -1
            r.kind = "gone"
    keep = [r for r in regions if r.kind != "gone"]
    remap = {r.id: i for i, r in enumerate(keep)}
    for i, r in enumerate(keep):
        r.id = i
    owner = np.array([remap.get(int(o), -1) if o >= 0 else -1 for o in owner], dtype=np.int64)
    regions = keep

    # 3. planes: flat pieces left over, unless they are facets of a curved surface
    left = np.flatnonzero(owner < 0)
    for u in left.tolist():
        ts = units[u]
        nb_left = [b for b in unbr[u] if owner[b] < 0 or regions[owner[b]].kind == "facet"]
        sm_left = sum(pairlen.get((u, b), 0.0) for b in nb_left)
        facet_like = sm_left > 0.5 * border[u]
        pr = fitmod.fit_plane(V[np.unique(F[ts])], N[ts])
        rid = len(regions)
        if not facet_like and _accept(pr, V, F, ts, N, tol):
            regions.append(Region(rid, "plane", ts, pr, float(A[ts].sum())))
        else:
            regions.append(Region(rid, "facet", ts, None, float(A[ts].sum())))
        owner[u] = rid
    for r in regions:                                  # report the fit on every vertex, not on the fitting subset
        if r.prim is not None:
            fitmod._finish(r.prim, V[np.unique(F[r.tris])])
    stats["freeform_parts"] = len(freeform_parts)
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    return regions, stats


def summary(regions: list[Region]) -> dict:
    tot = sum(r.area for r in regions) or 1.0
    by = {}
    for r in regions:
        d = by.setdefault(r.kind, {"regions": 0, "area_mm2": 0.0})
        d["regions"] += 1
        d["area_mm2"] += r.area
    par = sum(r.area for r in regions if r.parametric and r.kind != "bspline")
    ff = sum(r.area for r in regions if r.kind == "bspline")
    return {"parametric_area_pct": round(100 * par / tot, 2), "freeform_area_pct": round(100 * ff / tot, 2),
            "frozen_area_pct": round(100 * (tot - par - ff) / tot, 2),
            "by_kind": {k: {"regions": v["regions"], "area_mm2": round(v["area_mm2"], 3)} for k, v in sorted(by.items())}}
