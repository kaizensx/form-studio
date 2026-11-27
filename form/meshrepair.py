"""Safe, listed repairs for a mesh someone brings, and a lighter working copy of a heavy one.

A real mesh (a scan, a sculpt, a game asset, a CAD export) is rarely perfect: a few sliver flaps hang off an edge, a
handful of triangles are missing, some face the wrong way, specks of debris float beside the part. None of that is a
reason to refuse it. `repair` fixes what can be fixed without guessing, in this order, and lists every step:

    fins          triangles that hang off the surface by one edge (the edge has three or more triangles and the
                  triangle's other edges are open): removed; the surface under them is already whole
    non-manifold  an edge that still has more than two triangles: the smallest extra ones go (the hole that leaves
                  is filled below)
    orientation   triangles that disagree with their neighbours about the outside: turned
    holes         open boundaries: filled when small (form/recon/mesh.fill_holes: at most half the part across and
                  2 % of its surface); with cap_planar=True a flat opening of any size is capped (the open underside
                  of a scan). A large opening that is not flat is never guessed: it stays open and is listed
    debris        with drop_debris=True, loose pieces smaller than 0.1 % of the surface: removed
    inside out    a mesh whose volume is negative as a whole: turned

Nothing is moved: repairs remove or add triangles, vertices stay where the file put them.

`working_copy` makes a lighter mesh of a closed one for drawing and for work that cannot use every triangle (a sewn
mesh body, a fitted surface). It is manifold3d's simplification (edge collapses that keep the mesh closed and within a
stated distance of the original; Apache-2.0), and the distance is then measured both ways, not assumed. Without
manifold3d, or for a mesh that is not closed, it falls back to vertex clustering (form/meshprep.decimate), says so,
and is for display only. The original file is never changed and stays the reference every deviation is measured to.

numpy and scipy; no kernel.
"""
from __future__ import annotations

import time

import numpy as np

from .recon import mesh as meshmod

DEBRIS_AREA_FRAC = 1e-3     # a loose piece under this share of the surface is debris (drop_debris)
NONMANIFOLD_MAX_FRAC = 0.01  # more triangles than this share on non-manifold edges: not a few slivers, left alone
WORK_TRIANGLES = 120_000    # a working copy aims at this many triangles (a sewn mesh body of this size builds in
                            # well under a minute; see form/recipes/meshsolid.py)
WORK_TOL_FRAC = 2e-5        # the first simplification tolerance, as a share of the bounding-box diagonal


def _edge_counts(F: np.ndarray):
    """(per-triangle edge use counts (m, 3), edge index per half-edge, counts per edge)."""
    _E, _tri, eo, _he = meshmod.edges(F)
    cnt = np.bincount(eo, minlength=int(eo.max()) + 1 if len(eo) else 0)
    m = len(F)
    return np.stack([cnt[eo[:m]], cnt[eo[m:2 * m]], cnt[eo[2 * m:]]], axis=1), eo, cnt


def _areas(V, F):
    return 0.5 * np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)


def _drop_fins(V, F):
    """Triangles hanging off an over-used edge with their other edges open. Returns (F, count, area)."""
    n, area = 0, 0.0
    for _ in range(8):
        if not len(F):
            break
        ec, _eo, _cnt = _edge_counts(F)
        fin = (ec > 2).any(axis=1) & (ec == 1).any(axis=1)
        if not fin.any():
            break
        n += int(fin.sum())
        area += float(_areas(V, F[fin]).sum())
        F = F[~fin]
    return F, n, area


def _thin(V, F):
    """Where an edge still has more than two triangles, the smallest extra ones go. Returns (F, count, edges)."""
    ec, eo, cnt = _edge_counts(F)
    bad = np.flatnonzero(cnt > 2)
    if not len(bad):
        return F, 0, 0
    m = len(F)
    tri = np.tile(np.arange(m), 3)
    on_bad = cnt[eo] > 2
    if len(np.unique(tri[on_bad])) > max(64, NONMANIFOLD_MAX_FRAC * m):
        return F, 0, int(len(bad))                    # not a few slivers: two surfaces that share edges on purpose
    area = _areas(V, F)
    order = np.lexsort((area[tri[on_bad]], eo[on_bad]))
    e_s, t_s = eo[on_bad][order], tri[on_bad][order]
    start = np.r_[True, e_s[1:] != e_s[:-1]]
    size = np.diff(np.r_[np.flatnonzero(start), len(e_s)])
    rank = np.arange(len(e_s)) - np.repeat(np.flatnonzero(start), size)
    drop = np.unique(t_s[rank < np.repeat(size, size) - 2])   # all but the two largest on each edge
    keep = np.ones(m, bool)
    keep[drop] = False
    return F[keep], int(len(drop)), int(len(bad))


def _compact(V, F):
    used = np.unique(F)
    remap = -np.ones(len(V), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return V[used], remap[F]


def repair(V: np.ndarray, F: np.ndarray, fill: bool = True, cap_planar: bool = False, drop_debris: bool = False,
           top: dict | None = None) -> tuple[np.ndarray, np.ndarray, list, dict]:
    """Repair a welded mesh (V, F). Returns (V, F, repairs, topology): every repair is one record with what was done
    and how much; topology is form.recon.mesh.topology of the result, with "before" (the counts as given) and, when
    openings were too large to fill, "large_holes"."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    top0 = top or meshmod.topology(V, F)
    before = {k: top0[k] for k in ("boundary_edges", "boundary_loops", "non_manifold_edges", "flipped_edges", "pieces")}
    repairs: list = []
    large: list = []
    if top0["non_manifold_edges"]:
        F, n, area = _drop_fins(V, F)
        if n:
            repairs.append({"repair": "removed fin triangles", "count": n, "area_mm2": round(area, 4),
                            "why": "each hung off the surface by one edge that already had its two triangles"})
        F, n, edges = _thin(V, F)
        if n:
            repairs.append({"repair": "removed extra triangles on non-manifold edges", "count": n, "edges": edges,
                            "why": "an edge can have two triangles; the smallest extra ones went"})
        elif edges:
            repairs.append({"repair": "non-manifold edges left as they are", "edges": edges, "fixed": False,
                            "why": "too many to be slivers: two surfaces share these edges"})
    top = meshmod.topology(V, F) if repairs else top0
    if top["flipped_edges"] and not top["non_manifold_edges"]:
        from .meshclose import _orient
        F2 = _orient(F)
        turned = int((F2[:, 1] != F[:, 1]).sum())
        F = F2
        repairs.append({"repair": "turned triangles to agree with their neighbours", "count": turned})
        top = meshmod.topology(V, F)
    if top["boundary_edges"] and fill and not top["non_manifold_edges"]:
        diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
        loops = top["_loops"]
        V2, F2, rec = meshmod.fill_holes(V, F, loops, max_span=meshmod.HOLE_SPAN_FRAC * diag,
                                         max_area=meshmod.HOLE_AREA_FRAC * top["area_mm2"])
        left = [r for r in rec if not r.get("filled", True)]
        if left and cap_planar:                         # a flat opening of any size has one honest closure: its plane
            flat = [i for i, r in enumerate(rec) if not r.get("filled", True)
                    and r["flatness_mm"] <= 0.01 * max(r["span_mm"], 1e-9)]
            if flat:
                V2, F2, rec2 = meshmod.fill_holes(V, F, [loops[i] for i in range(len(loops))
                                                          if rec[i].get("filled", True) or i in flat])
                keep = [r for i, r in enumerate(rec) if not r.get("filled", True) and i not in flat]
                for r in rec2:
                    if r.get("filled") and any(r["at"] == rec[i]["at"] for i in flat):
                        r["repair"] = "capped a flat opening"
                rec = rec2 + keep
        V, F = V2, F2
        large = [r for r in rec if not r.get("filled", True)]
        filled = [r for r in rec if r.get("filled", True)]
        caps = [r for r in filled if r["repair"] == "capped a flat opening"]
        small = [r for r in filled if r["repair"] != "capped a flat opening"]
        if len(small) > 12:                             # a scan with many small holes: one summary, the largest listed
            how: dict = {}
            for r in small:
                how[r["method"]] = how.get(r["method"], 0) + 1
            big = sorted(small, key=lambda r: -r["span_mm"])[:5]
            repairs.append({"repair": "filled holes", "count": len(small), "by_method": how,
                            "planar": sum(1 for r in small if r["planar"]),
                            "area_mm2": round(sum(r["area_mm2"] for r in small), 4),
                            "largest_span_mm": big[0]["span_mm"], "largest": big})
        else:
            repairs += small
        repairs += caps + large
        top = meshmod.topology(V, F)
    if drop_debris and top["pieces"] > 1:
        lab = top["_piece_of"]
        area = np.bincount(lab, weights=_areas(V, F))
        small = area < DEBRIS_AREA_FRAC * area.sum()
        if small.any() and not small.all():
            gone = small[lab]
            repairs.append({"repair": "removed loose debris", "pieces": int(small.sum()), "triangles": int(gone.sum()),
                            "area_mm2": round(float(area[small].sum()), 4),
                            "why": f"each is under {DEBRIS_AREA_FRAC:.1%} of the surface and touches nothing"})
            F = F[~gone]
            V, F = _compact(V, F)
            top = meshmod.topology(V, F)
    if top["volume_mm3"] < 0:                           # inside out as a whole
        F = F[:, [0, 2, 1]]
        repairs.append({"repair": "turned the whole mesh outside in (its volume was negative)"})
        top = meshmod.topology(V, F)
    if len(np.unique(F)) != len(V):
        V, F = _compact(V, F)
        top = meshmod.topology(V, F)
    top = {**top, "before_repair": before}
    if large:
        top["large_holes"] = large
    return V, F, repairs, top


def open_text(top: dict) -> str:
    """What is open about a mesh, in words, from its topology (never "0 open boundaries" beside open edges)."""
    bits = []
    if top.get("boundary_edges"):
        n = top["boundary_edges"]
        loops = top.get("boundary_loops") or 0
        bits.append(f"{n} open edge{'s' if n != 1 else ''}" + (f" in {loops} hole{'s' if loops != 1 else ''}" if loops else ""))
    if top.get("non_manifold_edges"):
        n = top["non_manifold_edges"]
        bits.append(f"{n} non-manifold edge{'s' if n != 1 else ''}")
    return ", ".join(bits) or "no open edges"


def has_manifold() -> bool:
    import importlib.util
    return importlib.util.find_spec("manifold3d") is not None


def deviation(V, F, W, G, n: int = 60000, seed: int = 0) -> dict:
    """Measured distance between a mesh (V, F) and its copy (W, G), both ways: up to n of the original's vertices
    against the copy, and up to n points on the copy (the centroids and edge midpoints of its triangles) against
    the original; exact point-to-triangle distance (form/recon/distance.py). Evidence: computed, sampled."""
    from .recon import distance
    rng = np.random.default_rng(seed)
    diag = float(np.linalg.norm(np.ptp(V, axis=0)))
    A = V if len(V) <= n else V[rng.choice(len(V), size=n, replace=False)]
    # the copy: its triangles' centroids and edge midpoints (where a flat triangle is furthest from a curved surface)
    Gs = G if 4 * len(G) <= n else G[rng.choice(len(G), size=n // 4, replace=False)]
    p0, p1, p2 = W[Gs[:, 0]], W[Gs[:, 1]], W[Gs[:, 2]]
    B = np.vstack([(p0 + p1 + p2) / 3, (p0 + p1) / 2, (p1 + p2) / 2, (p2 + p0) / 2])
    a = distance.MeshDistance(W, G).closest(A)[0]
    b = distance.MeshDistance(V, F).closest(B)[0]
    return {"max_mm": round(float(max(a.max(), b.max())), 4), "original_to_copy_max_mm": round(float(a.max()), 4),
            "copy_to_original_max_mm": round(float(b.max()), 4),
            "p99_mm": round(float(np.percentile(np.r_[a, b], 99)), 4), "mean_mm": round(float(np.r_[a, b].mean()), 4),
            "points": int(len(a) + len(b)),
            "evidence": "computed (sampled points both ways, exact point-to-triangle distance)"}


def working_copy(V: np.ndarray, F: np.ndarray, target: int = WORK_TRIANGLES, tol: float | None = None,
                 max_tol: float | None = None, measure: bool = True) -> tuple[np.ndarray, np.ndarray, dict]:
    """A lighter mesh of (V, F) with at most about `target` triangles. Returns (V, F, record).

    A closed mesh is simplified with manifold3d: it stays closed, and the tolerance grows from `tol` (default: 0.002 %
    of the diagonal) until the count is at or under the target or the tolerance reaches `max_tol` (default: 1 % of
    the diagonal). The record states the triangles before and after, the tolerance used and the measured deviation.
    A mesh already at or under the target is returned as it is ("simplified": False)."""
    t0 = time.perf_counter()
    n0 = int(len(F))
    rec = {"repair": "working copy", "triangles_in": n0, "triangles": n0, "simplified": False, "target": int(target)}
    if n0 <= target:
        return V, F, rec
    diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
    lo = float(tol) if tol else WORK_TOL_FRAC * diag
    hi = float(max_tol) if max_tol else max(lo, 0.01 * diag)
    W = G = None
    if has_manifold():
        import manifold3d as m3
        try:
            man = m3.Manifold(m3.Mesh(vert_properties=np.asarray(V, np.float32), tri_verts=np.asarray(F, np.uint32)))
            ok = man.status() == m3.Error.NoError and man.num_tri() > 0
        except Exception:                               # noqa: BLE001
            ok = False
        if ok:
            # the largest count at or under the target: grow the tolerance until under it, then bisect back
            t, best, over = lo, None, None
            for _ in range(12):
                s = man.simplify(t)
                k = s.num_tri()
                if 0 < k <= target:
                    best = (t, k, s)
                    break
                if k and (over is None or k < over[1]):
                    over = (t, k, s)
                if t >= hi:
                    break
                t = min(hi, t * 2.0)
            if best is not None and over is not None and over[0] < best[0]:
                a_, b_ = over[0], best[0]
                for _ in range(5):
                    if best[1] >= 0.8 * target:
                        break
                    mid = (a_ * b_) ** 0.5
                    s = man.simplify(mid)
                    k = s.num_tri()
                    if 0 < k <= target:
                        if k > best[1]:
                            best = (mid, k, s)
                        b_ = mid
                    else:
                        a_ = mid
            if best is None:
                best = over
                rec["over_target"] = True
            if best is not None and best[1] < n0:
                mesh = best[2].to_mesh()
                W = np.asarray(mesh.vert_properties)[:, :3].astype(np.float64)
                G = np.asarray(mesh.tri_verts).astype(np.int64)
                rec.update({"method": "edge collapse (manifold3d): stays closed; the deviation is measured, not assumed",
                            "collapse_tolerance_mm": round(best[0], 4), "closed": True})
    if W is None:
        from .meshprep import decimate
        W, G, h = decimate(V, F, target)
        rec.update({"method": "vertex clustering (display only: thin walls and fine detail merge)",
                    "cell_mm": round(h, 4), "closed": bool(meshmod.topology(W, G)["closed"])})
    rec.update({"triangles": int(len(G)), "simplified": True})
    if measure:
        rec["deviation"] = deviation(V, F, W, G)
    rec["seconds"] = round(time.perf_counter() - t0, 2)
    return W, G, rec
