"""What each process's rules compare against: measured on one built model (kernel worker only).

``measure(model, process, spec, options)`` returns {"measures": {name: Measure}, "process_data": {...}, "overlay": ...}.
A Measure is {"state": "measured" | "not_checked", "reason", "method", "items": [{"value", "at", "faces", ...}]}:
every place on the part the rule can be judged at, with its value. The rules themselves (thresholds, sources,
verdicts) are applied by form/dfm/rules.py, outside the kernel, so a shop override never rebuilds anything.

`spec` carries the limits the measurement needs to know where to look (how thin a wall to search for), never the
verdict. Nothing here passes anything: a measure that could not be taken says not_checked and why.
"""
from __future__ import annotations

import base64
import math
import time

import numpy as np

from . import geom

VERSION = 1
AXES = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float)
AXIS_NAMES = ["+X", "−X", "+Y", "−Y", "+Z", "−Z"]
VERTICAL = 1e-3            # |n·d| under this: a face along the pull (or the tool axis)
FREE_SHARE = 0.98          # a cluster is released along a direction when this share of its area is
DRILLS = sorted({round(1.0 + 0.1 * i, 1) for i in range(121)} | {round(13.0 + 0.5 * i, 1) for i in range(15)})


def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _pt(p) -> list:
    return [round(float(x), 4) for x in p]


def _dir_name(d) -> str:
    d = np.asarray(d, float)
    for v, nm in zip(AXES, AXIS_NAMES):
        if float(v @ d) > 0.99999:
            return nm
    return "(" + ", ".join(f"{x:.3f}" for x in d) + ")"


def _measured(items, method, **extra) -> dict:
    return {"state": "measured", "items": items, "method": method, **extra}


def _not(reason: str) -> dict:
    return {"state": "not_checked", "items": [], "reason": reason}


def _faces_feat(surf, idx) -> list:
    return sorted({surf.faces[int(i)]["feature"] for i in idx})


def _by_face(surf, mask, values=None, worst=min, keep=None) -> list:
    """One item per B-rep face where mask is set: area, centroid of the flagged samples, worst value."""
    out = []
    for fi in np.unique(surf.F[mask]):
        m = mask & (surf.F == fi)
        a = float(surf.A[m].sum())
        at = (surf.S[m] * surf.A[m, None]).sum(axis=0) / max(a, 1e-12)
        it = {"faces": [int(fi)], "feature": surf.faces[int(fi)]["feature"], "area_mm2": round(a, 3), "at": _pt(at)}
        if values is not None:
            it["value"] = round(float(worst(values[m])), 4)
        if keep is None or keep(it):
            out.append(it)
    return out


def _nearest_sample(surf, p) -> int:
    return int(np.argmin(np.linalg.norm(surf.S - np.asarray(p, float), axis=1)))


# ---- shared measures ---------------------------------------------------------------------------------------------

def walls(model, surf, floor: float, upto: float) -> dict:
    """Thinnest walls by the thickness field (form/thickness.py): inward rays from every surface sample on the mesh,
    each thin region's minimum re-measured by an exact B-rep ray. Knife edges (two faces meeting at an edge, where
    material tapers to nothing by design) are listed but are not walls."""
    from .. import thickness
    res = thickness.regions(model, floor, upto=upto)
    items, knives = [], []
    for r in res.get("regions") or []:
        it = {"value": r["min_mm"], "at": r["at"], "to": r["to"], "kind": r["kind"], "feature": r["feature"],
              "area_mm2": r["area_mm2"], "faces": [int(surf.F[_nearest_sample(surf, r["at"])])]}
        (knives if r["kind"] == "knife_edge" else items).append(it)
    th = res.get("thinnest")
    if not items and th and th.get("t") is not None:
        items.append({"value": th["t"], "at": th["at"], "to": th.get("to"), "kind": th.get("kind", "wall"),
                      "feature": th.get("feature"), "faces": [int(surf.F[_nearest_sample(surf, th["at"])])],
                      "thinnest": True})
    return _measured(items, res.get("method", "thickness field"), knife_edges=knives[:8],
                     searched_below_mm=round(upto, 4), samples=res.get("samples"))


def wall_max(model, surf, floor: float) -> dict:
    """The thickest wall: per face, the 90th percentile of the inward wall ray (so a ray that runs along a corner
    does not set it), the largest of those. Labelled as that statistic."""
    from .. import thickness
    f = thickness.field(model, None, floor)
    t = np.asarray(f.t, float)
    ok = np.isfinite(t)
    items = []
    for fi in np.unique(f.face[ok]):
        m = ok & (f.face == fi)
        if m.sum() < 3:
            continue
        v = float(np.percentile(t[m], 90))
        at = f.S[m][int(np.argmin(np.abs(t[m] - v)))]
        items.append({"value": round(v, 4), "faces": [int(fi)], "feature": model["faces"][int(fi)]["feature"],
                      "at": _pt(at)})
    items.sort(key=lambda x: -x["value"])
    return _measured(items[:12], "Per face, the 90th percentile of the inward wall-ray thickness (form/thickness.py); "
                     "the 12 thickest faces are listed.")


def hole_measures(shape) -> dict:
    hs = geom.holes(shape)
    d_items, depth_items, drill_items = [], [], []
    for h in hs:
        base = {"at": _pt(h["at"]), "axis": _pt(h["axis"]), "d_mm": round(h["d"], 4), "depth_mm": round(h["depth"], 4)}
        d_items.append({**base, "value": round(h["d"], 4)})
        depth_items.append({**base, "value": round(h["depth"] / h["d"], 3)})
        if h["d"] <= DRILLS[-1] + 1e-9:
            near = min(DRILLS, key=lambda x: abs(x - h["d"]))
            drill_items.append({**base, "value": round(abs(near - h["d"]), 4), "nearest_drill_mm": near})
    method = "Full concave cylinders on the B-rep (coaxial faces of one radius closing 360°); diameter exact, depth along the axis."
    out = {"hole_d_mm": _measured(d_items, method), "hole_depth_over_d": _measured(depth_items, method)}
    out["hole_off_drill_mm"] = _measured(drill_items, method + " Holes over 20 mm are not compared with a drill series.")
    for k in out:
        out[k]["none"] = "no holes" if not hs else None
    return out


def trapped(shape) -> dict:
    vs = geom.voids(shape)
    items = [{"value": len(vs), "voids": [{"volume_mm3": round(v["volume"], 3), "at": _pt(v["at"]), "bbox": v["bbox"]}
                                          for v in vs], "at": _pt(vs[0]["at"]) if vs else None}]
    return _measured(items, "Enclosed voids are the solid's inner shells on the B-rep (exact). A cavity that opens to "
                     "the outside only through a hole is not counted: whether its hole is large enough is not judged.")


def fits(model, up, machine) -> dict:
    if not machine:
        return _not("No machine stated: pass machine=[x, y, z] in mm (the source's machine is used when the rule "
                    "table names one).")
    R = _frame(up)
    bb = np.asarray(model["bbox"], float)
    corners = np.array([[x, y, z] for x in bb[:, 0] for y in bb[:, 1] for z in bb[:, 2]])
    q = corners @ R.T
    size = q.max(axis=0) - q.min(axis=0)
    m = [float(x) for x in machine]
    ok = (size[0] <= m[0] and size[1] <= m[1] or size[0] <= m[1] and size[1] <= m[0]) and size[2] <= m[2]
    return _measured([{"value": bool(ok), "size_mm": _pt(size), "machine_mm": m}],
                     "The part's box in the build orientation (turning about the vertical allowed) against the machine.")


def _frame(up) -> np.ndarray:
    """Rotation taking `up` to +Z (rows: x', y', z')."""
    z = geom.unit(up)
    u, w = geom.basis(z)
    return np.stack([u, w, z])


def overhang(surf, up, plate_tol: float = 0.05) -> dict:
    """Downward-facing surface, by its angle from level (0° a flat ceiling, 90° a wall); faces on the plate are not
    overhangs. Per face: the smallest angle. Exact per sample from the tessellation normal (within 0.05 mm of the
    B-rep)."""
    up = geom.unit(up)
    nz = surf.N @ up
    hz = surf.S @ up
    plate = (hz <= hz.min() + plate_tol) & (nz < -0.999)
    down = (nz < -VERTICAL) & ~plate
    ang = np.degrees(np.arccos(np.clip(np.abs(nz), 0, 1)))
    items = _by_face(surf, down & (ang < 89.0), ang, min)
    return _measured(items, f"Samples {surf.h:.2f} mm apart; angle from level = arccos|n·up| on surfaces facing down, "
                     "the plate contact excluded."), ang, down


# ---- printing ------------------------------------------------------------------------------------------------------

def printing(model, surf, spec, options) -> tuple[dict, dict]:
    up = options.get("up") or [0, 0, 1]
    m = {}
    if "wall_min_mm" in spec:
        lo, hi = spec["wall_min_mm"]
        m["wall_min_mm"] = walls(model, surf, lo, hi * 1.0001)
    pdata = {"up": _pt(geom.unit(up))}
    if "overhang_from_level_deg" in spec:
        meas, ang, down = overhang(surf, up)
        m["overhang_from_level_deg"] = meas
        pdata["_map"] = ("overhang", np.where(down, ang, np.nan))
    if "hole_d_mm" in spec:
        m["hole_d_mm"] = hole_measures(model["shape"])["hole_d_mm"]
    if "trapped_voids" in spec:
        m["trapped_voids"] = trapped(model["shape"])
    if "fits_machine" in spec:
        m["fits_machine"] = fits(model, up, options.get("machine") or spec.get("machine"))
    return m, pdata


# ---- injection moulding --------------------------------------------------------------------------------------------

def _release(surf, pr, d, sub=None):
    """Per sample: +1 released by the half that opens along +d, −1 by the −d half, 0 an undercut."""
    idx = np.arange(len(surf.S)) if sub is None else sub
    S, N = surf.S[idx], surf.N[idx]
    nd = N @ d
    org = S + N * 1e-3
    up_free = ~pr.blocked(org, +1)
    dn_free = ~pr.blocked(org, -1)
    side = np.zeros(len(idx), np.int8)
    side[(nd > VERTICAL) & up_free] = 1
    side[(nd < -VERTICAL) & dn_free] = -1
    vert = np.abs(nd) <= VERTICAL
    side[vert & up_free] = 1
    side[vert & ~up_free & dn_free] = -1
    return side, nd


def _score(surf, d, sub, min_draft):
    pr = geom.Projection(surf, d, cells=96)
    side, nd = _release(surf, pr, d, sub)
    A = surf.A[sub]
    under = float(A[side == 0].sum())
    # faces with no draft anywhere (along the pull): their area, from the samples' max |n·d| per face
    F = surf.F[sub]
    mx = np.zeros(len(surf.faces))
    np.maximum.at(mx, F, np.abs(nd))
    flat = mx[F] < math.sin(math.radians(min_draft))
    return under, float(A[flat & (side != 0)].sum())


def pull_search(surf, model, min_draft: float, budget_s: float = 40.0) -> dict:
    """The pull direction with the least undercut area, then the least area with no draft: directions on the
    Gaussian sphere (a golden-angle spiral over the hemisphere; a two-plate pull and its reverse release the same
    surface), the axes and the normals of the largest flat faces and the axes of cylinders, then a local refinement
    around the best three. Scored on a subset of samples, the winner measured on all of them."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(0)
    n = len(surf.S)
    sub = np.sort(rng.choice(n, size=min(n, 6000), replace=False)) if n > 6000 else np.arange(n)
    cands = [AXES[0], AXES[2], AXES[4]]
    areas = {}
    for i, f in enumerate(surf.faces):
        areas[i] = f["area"]
    for i in sorted(areas, key=lambda k: -areas[k])[:8]:
        fc = surf.faces[i]["face"]
        g = geom._gtype(fc)
        if g == "PLANE":
            cands.append(geom._vec(fc.normal_at(fc.center())))
        elif g == "CYLINDER":
            cands.append(geom.cylinder_of(fc)[1])
    princ = [geom.unit(c) for c in cands]
    cands += list(geom.fibonacci(120, hemisphere=True))
    seen, uniq = [], []
    for c in cands:
        c = geom.unit(c)
        if c[2] < 0 or (abs(c[2]) < 1e-12 and (c[1] < 0 or (abs(c[1]) < 1e-12 and c[0] < 0))):
            c = -c
        if all(abs(float(c @ s)) < 0.9998 for s in seen):
            seen.append(c)
            uniq.append(c)
    scored = []
    for c in uniq:
        if time.perf_counter() - t0 > budget_s * 0.7 and len(scored) >= 6:
            break
        scored.append((*_score(surf, c, sub, min_draft), c))
    searched = len(scored)
    scored.sort(key=lambda x: (round(x[0], 2), round(x[1], 2)))
    best = list(scored[:3])
    for _u, _f, c in list(best):
        u, w = geom.basis(c)
        for ang in (3.0, 8.0):
            for k in range(8):
                a = math.radians(ang)
                phi = 2 * math.pi * k / 8
                v = geom.unit(math.cos(a) * c + math.sin(a) * (math.cos(phi) * u + math.sin(phi) * w))
                if time.perf_counter() - t0 > budget_s:
                    break
                scored.append((*_score(surf, v, sub, min_draft), v))
    scored.sort(key=lambda x: (round(x[0], 2), round(x[1], 2)))
    # a tool opens along an axis or a face's normal: when one of those has (within 0.2 % of the surface) the least
    # undercut, it wins over an oblique direction, whose only gain would be draft that tilting the tool fakes
    tol = 0.002 * float(surf.A[sub].sum())
    best_u = scored[0][0]
    principal = [s for s in scored if s[0] <= best_u + tol and any(abs(float(s[2] @ c)) > 0.99999 for c in princ)]
    top = min(principal, key=lambda s: (round(s[0], 2), round(s[1], 2))) if principal else scored[0]
    return {"pull": geom.unit(top[2]), "searched": len(scored), "sphere": searched,
            "seconds": round(time.perf_counter() - t0, 2), "complete": time.perf_counter() - t0 <= budget_s}


def _clusters(P, link):
    """Connected groups of points within `link` of each other (a voxel hash with union-find)."""
    if not len(P):
        return np.zeros(0, int)
    key = np.floor(P / link).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    parent = np.arange(len(uniq))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    index = {tuple(k): i for i, k in enumerate(uniq)}
    for i, k in enumerate(uniq):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    j = index.get((k[0] + dx, k[1] + dy, k[2] + dz))
                    if j is not None:
                        ra, rb = find(i), find(j)
                        if ra != rb:
                            parent[ra] = rb
    roots = np.array([find(i) for i in range(len(uniq))])
    _r, lab = np.unique(roots, return_inverse=True)
    return lab[inv]


def side_actions(surf, d, under_idx, cache) -> list:
    """For each connected undercut region, the way out it has, if any. Directions searched: 16 around the parting
    plane and the region's own mean normal projected on it.

    side action  a direction in the parting plane along which every sample of the region leaves the part (a slide
                 pulled out sideways before the tool opens)
    lifter       no way out, but a stroke along such a direction as long as the undercut is deep (+ 0.5 mm) is free:
                 an insert that moves in by that stroke as the part is ejected (an undercut inside the part). The
                 lifter's own path through the tool is not designed or checked
    none         neither: a collapsible core, a split insert or a change to the part"""
    if not len(under_idx):
        return []
    lab = _clusters(surf.S[under_idx], 2.5 * surf.h)
    u, w = geom.basis(d)
    out = []

    def proj(v):
        k = tuple(np.round(v, 6))
        if k not in cache:
            cache[k] = geom.Projection(surf, v, cells=96)
        return cache[k]

    def free(idx, v, maxd=None):
        S, N, A = surf.S[idx], surf.N[idx], surf.A[idx]
        ok = (N @ v > -VERTICAL) & ~proj(v).blocked(S + N * 1e-3, +1, maxd=maxd)
        return float(A[ok].sum()) / max(float(A.sum()), 1e-12)
    for c in range(int(lab.max()) + 1 if len(lab) else 0):
        idx = under_idx[lab == c]
        area = float(surf.A[idx].sum())
        if area < 2 * surf.h * surf.h:
            continue
        mean_n = (surf.N[idx] * surf.A[idx, None]).sum(axis=0)
        inplane = [math.cos(2 * math.pi * k / 16) * u + math.sin(2 * math.pi * k / 16) * w for k in range(16)]
        mp = mean_n - (mean_n @ d) * d
        if np.linalg.norm(mp) > 1e-9:
            inplane.insert(0, geom.unit(mp))
        at = (surf.S[idx] * surf.A[idx, None]).sum(axis=0) / area
        item = {"area_mm2": round(area, 3), "at": _pt(at), "faces": sorted({int(x) for x in surf.F[idx]}),
                "features": _faces_feat(surf, surf.F[idx])}
        best = max(((free(idx, v), v) for v in inplane), key=lambda x: x[0])
        if best[0] >= FREE_SHARE:
            item.update({"action": "side action", "direction": _pt(best[1]), "released_share": round(best[0], 4)})
        else:
            found = None
            for v in inplane:
                ps = surf.S[idx] @ v
                stroke = float(ps.max() - ps.min()) + 0.5
                sh = free(idx, v, maxd=stroke)
                if sh >= FREE_SHARE and (found is None or stroke < found[0]):
                    found = (stroke, v, sh)
            if found:
                item.update({"action": "lifter", "direction": _pt(found[1]), "stroke_mm": round(found[0], 3),
                             "released_share": round(found[2], 4),
                             "note": "The lifter's path through the tool is not designed or checked."})
            else:
                item.update({"action": "none", "released_share": round(best[0], 4),
                             "note": "No straight release found: a collapsible core, a split insert or a change to "
                                     "the part."})
        out.append(item)
    return out


def parting_line(surf, model, d, pr):
    """The silhouette parting curve for pull d: tessellation edges between a triangle released by the +d half and
    one released by the −d half (faces along the pull go with the +d half, so the line runs at their −d end).
    Returns (segments (n, 6) float32, heights along d)."""
    P, T = [], []
    off = 0
    for f in model["faces"]:
        P.append(np.asarray(f["P"], float))
        T.append(np.asarray(f["T"], np.int64) + off)
        off += len(f["P"])
    P, T = np.concatenate(P), np.concatenate(T)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 1e-14
    T, a, b, c, n = T[keep], a[keep], b[keep], c[keep], n[keep] / ln[keep, None]
    cen = (a + b + c) / 3

    class _S:
        pass
    s = _S()
    s.S, s.N = cen, n
    side, _nd = _release(s, pr, d)
    q = np.round(P / 1e-5).astype(np.int64)
    _u, vid = np.unique(q, axis=0, return_inverse=True)
    vid = vid.ravel()
    E = np.concatenate([vid[T[:, [0, 1]]], vid[T[:, [1, 2]]], vid[T[:, [2, 0]]]])
    owner = np.tile(np.arange(len(T)), 3)
    key = np.sort(E, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, owner, E = key[order], owner[order], E[order]
    same = np.all(key[1:] == key[:-1], axis=1)
    i = np.flatnonzero(same)
    t1, t2 = owner[i], owner[i + 1]
    cut = (side[t1] * side[t2]) == -1
    segs = []
    pos = {}
    for k, vv in enumerate(vid):
        pos.setdefault(int(vv), P[k])
    for j in np.flatnonzero(cut):
        e = key[i[j]]
        segs.append(np.concatenate([pos[int(e[0])], pos[int(e[1])]]))
    S = np.asarray(segs, dtype=np.float32).reshape(-1, 6)
    heights = np.concatenate([S[:, :3] @ d, S[:, 3:] @ d]) if len(S) else np.zeros(0)
    return S, heights


def injection(model, surf, spec, options) -> tuple[dict, dict]:
    m: dict = {}
    min_draft = spec.get("draft_deg", (0.5, 2.0))[0]
    want = options.get("pull")
    if want in (None, "", "auto"):
        search = pull_search(surf, model, min_draft)
        d = search["pull"]
    else:
        d = geom.unit(want)
        search = {"pull": d, "searched": 0, "given": True}
    pr = geom.Projection(surf, d)
    side, nd = _release(surf, pr, d)
    under = side == 0
    m["undercut_mm2"] = _measured(
        [{**it, "value": it["area_mm2"]} for it in _by_face(surf, under)] or [{"value": 0.0}],
        f"Rays along ±pull from {len(surf.S):,} samples {surf.h:.2f} mm apart, against every triangle of the "
        "tessellation. A sample neither half can release is undercut.", total_mm2=round(float(surf.A[under].sum()), 3))
    segs, heights = parting_line(surf, model, d, pr)
    # draft per B-rep face, against its half, exact on planes and on cylinders and cones along the pull
    items = []
    near_pl = np.zeros(len(surf.S), bool)
    if len(segs):
        mids = np.concatenate([segs[:, :3], segs[:, 3:]]).astype(float)
        for i0 in range(0, len(surf.S), 4000):
            dd = np.linalg.norm(surf.S[i0:i0 + 4000, None, :] - mids[None, ::max(1, len(mids) // 2000), :], axis=2)
            near_pl[i0:i0 + 4000] = dd.min(axis=1) < 2.0 * surf.h
    fside = np.zeros(len(surf.faces))
    np.add.at(fside, surf.F, side * surf.A)
    vals = np.degrees(np.arcsin(np.clip(nd, -1, 1))) * np.where(side == 0, 1, side)
    for fi, f in enumerate(surf.faces):
        mk = surf.F == fi
        if not mk.any() or not (mk & ~under).any():
            continue
        sgn = 1.0 if fside[fi] >= 0 else -1.0
        fd = geom.face_draft(f["face"], d)
        if fd["exact"]:
            v = sgn * fd["min"] if sgn > 0 else -fd["max"]
            how = "exact"
        else:
            sel = mk & ~under & ~near_pl
            if not sel.any():
                continue
            v = float(vals[sel].min())
            how = "sampled (the band at the parting line excluded)"
        if v >= 45.0:
            continue
        at = (surf.S[mk] * surf.A[mk, None]).sum(axis=0) / float(surf.A[mk].sum())
        items.append({"value": round(float(v), 4), "faces": [fi], "feature": f["feature"], "at": _pt(at),
                      "half": "+pull" if sgn > 0 else "−pull", "how": how, "area_mm2": round(float(surf.A[mk].sum()), 3)})
    m["draft_deg"] = _measured(items, "Draft = asin(n·pull) toward the half that releases the face: exact for planes "
                               "and for cylinders and cones along the pull, sampled on other surfaces. Faces steeper "
                               "than 45° are not listed.")
    lo, hi = spec.get("wall_min_mm", (None, None)), None
    if "wall_min_mm" in spec and spec["wall_min_mm"][0] is not None:
        lo, hi = spec["wall_min_mm"]
        m["wall_min_mm"] = walls(model, surf, lo, hi * 1.0001)
    elif "wall_min_mm" in spec:
        m["wall_min_mm"] = _not("No resin stated: the wall range is per resin (resin=abs, pc, pp, ...).")
    if "wall_max_mm" in spec:
        if spec["wall_max_mm"][0] is None:
            m["wall_max_mm"] = _not("No resin stated: the wall range is per resin.")
        else:
            m["wall_max_mm"] = wall_max(model, surf, max(0.3, spec["wall_max_mm"][0] / 4))
    ext = float(np.linalg.norm(surf.hi - surf.lo))
    pix = max(ext / 500.0, 0.05)
    area, err = pr.covered(pix)
    m["projected_in2"] = _measured([{"value": round(area / 645.16, 4), "mm2": round(area, 2), "error_mm2": round(err, 2)}],
                                   f"Shadow of the part along the pull on a {pix:.3f} mm pixel grid; ± half the "
                                   "boundary pixels.")
    hts = np.asarray(heights) if len(heights) else None
    z = surf.S @ d
    if hts is not None and len(hts):
        depth = max(float(z.max() - hts.min()), float(hts.max() - z.min()))
        m["depth_from_parting_mm"] = _measured([{"value": round(depth, 3)}], "Largest distance along the pull from the "
                                               "parting line to the far end of either half.")
    else:
        m["depth_from_parting_mm"] = _not("No parting line was found for this pull.")
    cache: dict = {}
    sa = side_actions(surf, d, np.flatnonzero(under), cache)
    data = {"pull": _pt(d), "pull_name": _dir_name(d), "search": {k: v for k, v in search.items() if k != "pull"},
            "parting_line": {"segments": int(len(segs)), "lines": _b64(segs.astype(np.float32)) if len(segs) else "",
                             "height_range_mm": [round(float(hts.min()), 3), round(float(hts.max()), 3)] if hts is not None and len(hts) else None,
                             "note": "Line proposed for a two-plate tool. The parting surface is not designed."},
            "projected_mm2": round(area, 2), "projected_error_mm2": round(err, 2),
            "side_actions": sa, "_map": ("draft", np.degrees(np.arcsin(np.clip(nd, -1, 1)))),
            "_flags": {"undercut": under}}
    return m, data


# ---- CNC -------------------------------------------------------------------------------------------------------

def _directions(axes: int, rotary: str = "x"):
    """Tool directions and the setups they belong to: [(setup name, [directions])]."""
    if axes <= 3:
        return [(f"setup {nm}", [v]) for v, nm in zip(AXES, AXIS_NAMES)]
    if axes == 4:
        ax = {"x": AXES[0], "y": AXES[2], "z": AXES[4]}[rotary]
        u, w = geom.basis(ax)
        ring = [geom.unit(math.cos(math.radians(a)) * u + math.sin(math.radians(a)) * w) for a in range(0, 360, 15)]
        return [(f"rotary about {rotary.upper()}", ring), (f"end +{rotary.upper()}", [ax]), (f"end −{rotary.upper()}", [-ax])]
    dirs = geom.fibonacci(96)
    out = []
    for v, nm in zip(AXES, AXIS_NAMES):
        out.append((f"3+2 with {nm} up", [d for d in dirs if float(d @ v) >= -1e-9] + [v]))
    return out


def _reach(surf, a, r, flute, holder_r, pix):
    """Per sample: can a flat end mill of radius r coming down −a touch it, and how far below the surrounding
    material its tip is (reach, mm). Centres tried: the sample pushed out along its normal by r (a wall), the sample
    itself and 16 points around it (a floor)."""
    pr = geom.Projection(surf, a, cells=128)
    H, lo, p = pr.heightmap(pix, pad=2 * r + (holder_r or 0.0) + 2 * pix)    # room for the tool beside the part
    Ht = geom.disc_max(H, max(0.0, (r - p) / p))
    Hr = geom.disc_max(H, 2 * r / p)
    Hh = geom.disc_max(H, holder_r / p) if holder_r else None
    nx, ny = H.shape
    S, N = surf.S, surf.N
    za = S @ a
    na = N @ a
    q = np.stack([S @ pr.u, S @ pr.w], axis=1)
    nh = np.stack([N @ pr.u, N @ pr.w], axis=1)
    nl = np.linalg.norm(nh, axis=1)
    cands = []
    wall = np.where(nl[:, None] > 1e-6, nh / np.maximum(nl, 1e-12)[:, None], 0.0)
    cands.append(q + r * wall)
    cands.append(q)
    for rho in (0.5, 0.8, 1.0):
        for k in range(16):
            ang = 2 * math.pi * k / 16
            cands.append(q + rho * r * np.array([math.cos(ang), math.sin(ang)]))
    tol = 0.5 * p + 0.02
    ok = np.zeros(len(S), bool)
    reach = np.full(len(S), np.nan)
    for c in cands:
        ij = np.rint((c - lo) / p).astype(np.int64)
        inb = (ij[:, 0] >= 0) & (ij[:, 1] >= 0) & (ij[:, 0] < nx) & (ij[:, 1] < ny)
        ij = np.clip(ij, 0, [nx - 1, ny - 1])
        ht = np.where(inb, Ht[ij[:, 0], ij[:, 1]], -np.inf)          # beyond the grid there is no material
        hit = ht <= za + tol
        if Hh is not None and flute:
            hit &= np.where(inb, Hh[ij[:, 0], ij[:, 1]], -np.inf) <= za + flute + tol
        rr = np.maximum(0.0, np.where(inb, Hr[ij[:, 0], ij[:, 1]], -np.inf) - za)
        better = hit & (~ok | (rr < np.nan_to_num(reach, nan=np.inf)))
        reach = np.where(better, rr, reach)
        ok |= hit
    ok &= na > -0.05
    return ok, reach


def cnc(model, surf, spec, options) -> tuple[dict, dict]:
    m: dict = {}
    axes = int(options.get("axes") or 3)
    tool_d = options.get("tool_d")
    data: dict = {"axes": axes}
    shape = model["shape"]
    if "wall_min_mm" in spec:
        if spec["wall_min_mm"][0] is None:
            m["wall_min_mm"] = _not("No material class stated: material=metal or material=plastic.")
        else:
            lo, hi = spec["wall_min_mm"]
            m["wall_min_mm"] = walls(model, surf, lo, hi * 1.0001)
    m.update(hole_measures(shape))
    if not tool_d:
        why = "No tool stated: tool_d (flat end mill diameter, mm) sets what can be reached and the smallest corner."
        for k in ("unreached_mm2", "corner_r_mm", "corner_r_over_depth", "reach_over_d", "setups"):
            m[k] = _not(why)
        return m, data
    r = float(tool_d) / 2
    flute = float(options.get("flute_l") or 0) or None
    holder_r = float(options.get("holder_d") or 0) / 2 or None
    ext = float((surf.hi - surf.lo).max())
    pix = max(min(r / 4, 0.5), ext / 700.0)
    groups = _directions(axes, str(options.get("rotary_axis") or "x"))
    masks, reaches, used_dirs, dir_masks = [], [], [], []
    t0 = time.perf_counter()
    memo: dict = {}                                    # a direction shared by several setups is measured once
    for name, dirs in groups:
        gm = np.zeros(len(surf.S), bool)
        gr = np.full(len(surf.S), np.inf)
        for a in dirs:
            a = geom.unit(a)
            k = tuple(np.round(a, 9))
            if k not in memo:
                memo[k] = _reach(surf, a, r, flute, holder_r, pix)
                used_dirs.append(a)
                dir_masks.append((a, memo[k][0]))
            ok, rc = memo[k]
            gr = np.where(ok, np.minimum(gr, np.nan_to_num(rc, nan=np.inf)), gr)
            gm |= ok
        masks.append(gm)
        reaches.append(gr)
    anyok = np.any(masks, axis=0)
    drilled = np.zeros(len(surf.S), bool)              # bores are drilled: judged by the hole rules, not the mill
    for h in geom.holes(shape):
        for f in h["faces"]:
            fi = _face_index(surf, f)
            if fi >= 0:
                drilled |= surf.F == fi
    anyok |= drilled
    # greedy set cover of the reachable surface by setups
    left, chosen = anyok.copy(), []
    while left.any():
        gains = [float(surf.A[mk & left].sum()) for mk in masks]
        k = int(np.argmax(gains))
        if gains[k] <= 0:
            break
        chosen.append({"setup": groups[k][0], "area_mm2": round(gains[k], 2)})
        left &= ~masks[k]
    unreached = ~anyok
    res = 2 * pix * pix
    items = [it for it in _by_face(surf, unreached) if it["area_mm2"] >= res]
    for it in items:
        it["value"] = it["area_mm2"]
    m["unreached_mm2"] = _measured(items or [{"value": 0.0}],
                                   f"A flat end mill Ø{tool_d:g} mm coming down each tool direction of a {axes}-axis "
                                   f"machine ({len(used_dirs)} directions in {len(groups)} setups) on a height field of "
                                   f"{pix:.3f} mm pixels; areas under {res:.3f} mm² are within the pixel and not counted.",
                                   total_mm2=round(float(sum(i.get("area_mm2", 0) for i in items)), 3))
    m["setups"] = _measured([{"value": len(chosen), "setups": chosen}], "Greedy set cover of the reachable surface.")
    best = np.min(np.stack(reaches), axis=0)
    rod = np.where(np.isfinite(best), best / float(tool_d), np.nan)
    ritems = _by_face(surf, np.isfinite(rod) & (rod >= 1.0), np.nan_to_num(rod, nan=0), max)
    ritems.sort(key=lambda x: -x["value"])
    m["reach_over_d"] = _measured(ritems[:16], "Depth of the tool tip below the highest material within two tool radii "
                                  "of its axis, divided by the tool diameter, in the best setup for each sample.")
    # internal vertical corners: sharp concave edges and concave blends along a tool direction
    face_reached = {}
    for a, mk in dir_masks:
        face_reached[tuple(np.round(a, 6))] = set(np.unique(surf.F[mk]).tolist())

    def par(v, fis):
        # a corner along v matters when a tool along v reaches the faces beside it (else it is a floor edge)
        for a in used_dirs:
            if abs(float(v @ a)) > 0.9986 or axes >= 5:
                got = face_reached[tuple(np.round(a, 6))]
                if all(fi in got for fi in fis if fi >= 0):
                    return True
        return False
    citems, ditems = [], []
    for e in geom.concave_line_edges(shape):
        if not par(e["dir"], [_face_index(surf, f) for f in e["faces"]]):
            continue
        base = {"at": _pt(e["mid"]), "axis": _pt(e["dir"]), "depth_mm": round(e["length"], 4), "sharp": True,
                "angle_deg": round(e["angle_deg"], 2), "features": _faces_feat(surf, [_face_index(surf, f) for f in e["faces"]])}
        citems.append({**base, "value": 0.0})
        ditems.append({**base, "value": 0.0})
    for c in geom.fillet_corners(shape):
        fi = _face_index(surf, c["face"])
        if not par(c["axis"], [fi]):
            continue
        base = {"at": _pt(c["at"]), "axis": _pt(c["axis"]), "depth_mm": round(c["length"], 4), "sharp": False,
                "r_mm": round(c["r"], 4), "faces": [fi] if fi >= 0 else []}
        citems.append({**base, "value": round(c["r"], 4)})
        ditems.append({**base, "value": round(c["r"] / max(c["length"], 1e-9), 4)})
    cm = "Concave straight edges (exact on the B-rep: the faces' normals at the edge) and concave cylindrical blends "
    cm += "along a tool direction; depth is the corner's length along the tool."
    m["corner_r_mm"] = _measured(citems, cm, none=None if citems else "no internal vertical corners")
    m["corner_r_over_depth"] = _measured(ditems, cm, none=None if ditems else "no internal vertical corners")
    data.update({"tool_d": float(tool_d), "pixel_mm": round(pix, 4), "setups": chosen,
                 "directions": len(used_dirs), "seconds": round(time.perf_counter() - t0, 2),
                 "_map": ("reach", rod), "_flags": {"unreached": unreached}})
    return m, data


def _face_index(surf, face) -> int:
    for i, f in enumerate(surf.faces):
        if f["face"].wrapped.IsSame(face.wrapped):
            return i
    return -1


# ---- the kernel op ---------------------------------------------------------------------------------------------

PROCS = {"cnc": cnc, "injection": injection, "fdm": printing, "sla": printing, "sls": printing, "mjf": printing,
         "lpbf": printing}


def measure_model(model, process: str, spec: dict, options: dict) -> dict:
    t0 = time.perf_counter()
    if getattr(model.get("recipe"), "mesh", False):
        return {"version": VERSION, "process": process, "mesh": True, "measures": {},
                "reason": "A mesh design has no B-rep: manufacturability is measured on the exact solid only."}
    surf = geom.Surface(model)
    meas, data = PROCS[process](model, surf, spec, options)
    out = {"version": VERSION, "process": process, "measures": meas, "samples": int(len(surf.S)),
           "spacing_mm": round(surf.h, 4), "bbox": [_pt(surf.lo), _pt(surf.hi)], "faces": len(surf.faces),
           "features": [f["feature"] for f in surf.faces]}
    mp = data.pop("_map", None)
    flags = data.pop("_flags", {})
    out["data"] = data
    Q = surf.Q.reshape(-1, 3).astype(np.float32)
    ov = {"positions": _b64(Q), "tri_face": _b64(surf.F.astype(np.int32)), "triangles": int(len(surf.F))}
    if mp is not None:
        ov["map"] = mp[0]
        ov["values"] = _b64(np.asarray(mp[1], dtype=np.float32))
    for k, v in flags.items():
        ov["flag_" + k] = _b64(np.asarray(v, dtype=np.uint8))
    out["overlay"] = ov
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def op_dfm(key, recipe_id, values, process, spec, options, tol=0.05):
    from .. import kernel
    model = kernel._get(key, recipe_id, values, tol)
    return measure_model(model, process, spec, options)


KERNEL_OPS = {"dfm": op_dfm}
