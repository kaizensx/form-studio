"""analyze_reference: what an engineer measures on a mesh before modelling it again as clean CAD.

Everything is measured on the mesh as given (evidence: computed). The surfaces come from form/recon's segmentation
(planes, cylinders, cones, spheres, tori within the tolerance); the features are read from them:

- holes and bosses: full cylinders, concave or convex, with diameter, depth, axis and whether they go through;
- fillets: part cylinders and tori of small radius (convex: a rounded edge; concave: a filleted inside corner);
- chamfers: narrow plane strips between two planes, about halfway between their normals, with width and angles;
- ramps: planes that lean against the part's axes, with angle, rise and run; tilted walls give the draft;
- steps: the levels of faces across the up axis, with their areas;
- walls, ribs, rails and slots/grooves: pairs of opposite parallel planes facing away from each other (material
  between: a wall of that thickness) or toward each other (a gap of that width), long ones named rails and grooves;
- openings (pockets, slots, cutouts): the inner loops of sections across the up axis;
- detail areas: clusters of facets and tiny faces (text, embossing, knurls, freeform blends);
- symmetry: mirror planes, with the largest deviation from mirror image.

Sections are cut in the three principal planes at several levels and returned as images with dimensions and as
vector outlines (within 0.01 mm unless the outline is long).
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import sections as secmod

AXES = "xyz"


def where(p, lo, hi) -> str:
    """Words for a point's place in a box: 'left front, bottom' and so on (x left to right, y front to back,
    z bottom to top)."""
    p, lo, hi = (np.asarray(x, dtype=np.float64) for x in (p, lo, hi))
    f = (p - lo) / np.maximum(hi - lo, 1e-9)
    def pick(v, names):
        return names[0] if v < 1 / 3 else names[2] if v > 2 / 3 else names[1]
    xs, ys, zs = pick(f[0], ("left", "centre", "right")), pick(f[1], ("front", "middle", "back")), \
        pick(f[2], ("bottom", "mid-height", "top"))
    return f"{xs} {ys}, {zs}".replace("centre middle", "centre")


def _r(x, n=3):
    return [round(float(v), n) for v in x] if hasattr(x, "__len__") else round(float(x), n)


def load(path) -> tuple[np.ndarray, np.ndarray, dict]:
    from pathlib import Path
    from ..recon.mesh import read_triangles, topology, weld
    T, info = read_triangles(Path(path))
    V, F, w = weld(T, 1e-6)
    top = topology(V, F)
    if top["volume_mm3"] < 0:
        F = F[:, [0, 2, 1]]
    info["closed"] = top["closed"]
    info["triangles"] = int(len(F))
    return V, F, info


def principal(V, F) -> dict:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    A = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    C = (a + b + c) / 3
    m = (C * A[:, None]).sum(0) / A.sum()
    X = C - m
    cov = (X * A[:, None]).T @ X / A.sum()
    w, U = np.linalg.eigh(cov)
    U = U[:, ::-1]
    axes = []
    for k in range(3):
        u = U[:, k]
        j = int(np.argmax(np.abs(u)))
        ang = math.degrees(math.acos(min(1.0, abs(u[j]))))
        axes.append({"direction": _r(u * np.sign(u[j]), 5), "nearest_world_axis": AXES[j],
                     "angle_to_it_deg": round(ang, 3), "extent_mm": round(float(np.ptp(V @ u)), 3)})
    # flat faces say how a part is squared up better than its mass does: the share of the area facing along X, Y or Z
    N = np.cross(b - a, c - a) / np.maximum(2 * A, 1e-300)[:, None]
    along = float(A[np.abs(N).max(axis=1) > 0.99985].sum() / A.sum())
    aligned = along > 0.5 or (all(x["angle_to_it_deg"] < 0.5 for x in axes) and len({x["nearest_world_axis"] for x in axes}) == 3)
    return {"centroid": _r(m), "inertia_axes": axes, "area_facing_world_axes_pct": round(100 * along, 1),
            "aligned_to_world": aligned,
            "note": ("The part's principal axes are the world axes: model it in these coordinates." if aligned else
                     "The part is not aligned to the world axes: model it in its principal frame, then place it.")}


def _coverage(ang):
    h = np.zeros(72, dtype=bool)
    h[(np.floor((ang + math.pi) / (2 * math.pi) * 72).astype(int)) % 72] = True
    return float(h.mean())


def _plane_frame(n):
    t = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, t)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _axis_name(d, eps_deg=1.0):
    j = int(np.argmax(np.abs(d)))
    return AXES[j] if math.degrees(math.acos(min(1.0, abs(d[j])))) < eps_deg else None


def analyse(V, F, tol: float = 0.05, budget_s: float = 60.0, name: str = "part", up: int | None = None,
            section_levels: dict | None = None) -> dict:
    """The full analysis (with private keys "_..." that carry triangle lists and section loops)."""
    from ..recon import segment as segmod
    from ..recon.distance import MeshDistance
    t0 = time.perf_counter()
    lo, hi = V.min(axis=0), V.max(axis=0)
    size = hi - lo
    diag = float(np.linalg.norm(size))
    a_, b_, c_ = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol = float(np.einsum("ij,ij->i", a_, np.cross(b_, c_)).sum() / 6.0)
    out = {"name": name, "evidence": "computed (measured on the mesh as given)", "tolerance_mm": tol,
           "size_mm": _r(size), "bbox": [_r(lo), _r(hi)], "volume_mm3": round(vol, 2),
           "triangles": int(len(F)), "principal": principal(V, F)}

    regions, st = segmod.segment(V, F, tol, budget_s=budget_s)
    adj = segmod.Adjacency(V, F)
    N, TA = adj.N, adj.A
    reg_of = -np.ones(len(F), dtype=np.int64)
    for r in regions:
        reg_of[r.tris] = r.id
    summ = segmod.summary(regions)
    out["surfaces"] = {**summ, "segmentation_seconds": st.get("seconds")}

    # neighbours and shared edge length between regions
    ra, rb = reg_of[adj.t1], reg_of[adj.t2]
    x = ra != rb
    shared = {}
    for i, j, ln in zip(ra[x].tolist(), rb[x].tolist(), adj.len[x].tolist()):
        shared[(i, j)] = shared.get((i, j), 0.0) + ln
        shared[(j, i)] = shared.get((j, i), 0.0) + ln
    nbrs = {}
    for (i, j), ln in shared.items():
        nbrs.setdefault(i, []).append((ln, j))
    for v in nbrs.values():
        v.sort(reverse=True)

    # the up axis: the world axis with the most planar area across it
    planes = [r for r in regions if r.kind == "plane"]
    from .occupancy import Occupancy
    occ0 = Occupancy(V, F, h=max(float(size.max()) / 900, 0.04))
    across = np.zeros(3)
    for r in planes:
        k = _axis_name(r.prim.p["a"])
        if k:
            across[AXES.index(k)] += r.area
    if up is None:
        up = int(np.argmax(across)) if across.max() > 0 else 2
    out["up_axis"] = AXES[up]

    feats = []
    fid = {}

    def add(kind, rows, tris=None, **kw):
        fid[kind] = fid.get(kind, 0) + 1
        f = {"id": f"{kind} {fid[kind]}", "kind": kind, **kw}
        if "at" in f:
            f["where"] = where(f["at"], lo, hi)
        if tris is not None:
            f["_tris"] = np.asarray(tris, dtype=np.int64)
        rows.append(f)
        return f

    small_r = min(6.0, 0.2 * float(np.sort(size)[1]))
    chamfer_w = min(3.0, 0.12 * float(np.sort(size)[1]))
    rows = []
    # ---- round surfaces
    for r in regions:
        if r.kind not in ("cylinder", "cone", "torus", "sphere") or r.prim is None:
            continue
        P = V[np.unique(F[r.tris])]
        cen = (a_[r.tris] + b_[r.tris] + c_[r.tris]) / 3
        pn = r.prim.normal(cen)
        convex = float((np.einsum("ij,ij->i", pn, N[r.tris]) * TA[r.tris]).sum()) > 0
        p = r.prim.p
        if r.kind == "sphere":
            add("sphere", rows, r.tris, convex=convex, radius=_r(p["r"]), at=_r(p["o"]), area_mm2=round(r.area, 2))
            continue
        o, a = p["o"], p["a"]
        s = (P - o) @ a
        u, w = _plane_frame(a)
        ang = np.arctan2((P - o) @ w, (P - o) @ u)
        cov = _coverage(ang)
        mid = o + a * (s.min() + s.max()) / 2
        ax = _axis_name(a)
        axis_txt = ax or _r(a, 4)
        length = float(np.ptp(s))
        if r.kind == "torus":
            add("fillet", rows, r.tris, convex=convex, radius=_r(p["r"]), around="a round edge", ring_radius=_r(p["R"]),
                axis=axis_txt, at=_r(mid), note="a fillet where a round face meets a flat one (torus)")
            continue
        if r.kind == "cone":
            ha = math.degrees(p.get("half_angle", 0.0))
            kind = "countersink or chamfered hole" if not convex else "cone or chamfered round edge"
            add("cone", rows, r.tris, convex=convex, half_angle_deg=round(ha, 2), axis=axis_txt, at=_r(mid),
                length_mm=round(length, 3), note=kind)
            continue
        rad = float(p["r"])
        if cov >= 0.9:
            # through when the axis just past both ends is outside the part
            ends = np.array([mid + a * (length / 2 + 0.3), mid - a * (length / 2 + 0.3)])
            through = not occ0.inside(ends).any()
            if not convex:
                add("hole", rows, r.tris, diameter=round(2 * rad, 3), depth_mm=round(length, 3), through=bool(through),
                    axis=axis_txt, at=_r(mid))
            else:
                add("boss", rows, r.tris, diameter=round(2 * rad, 3), height_mm=round(length, 3), axis=axis_txt, at=_r(mid),
                    note="a pin, boss or round post")
        elif rad <= small_r:
            add("fillet", rows, r.tris, convex=convex, radius=round(rad, 3), length_mm=round(length, 3), axis=axis_txt,
                at=_r(mid), span_deg=round(cov * 360), note="rounded outside edge" if convex else "filleted inside corner")
        else:
            add("arc wall", rows, r.tris, convex=convex, radius=round(rad, 3), span_deg=round(cov * 360), axis=axis_txt,
                centre=_r(o + a * (s.min() + s.max()) / 2), height_mm=round(length, 3),
                at=_r(cen[np.argmax(TA[r.tris])]))
    # ---- planes: chamfers, ramps, tilted walls
    upv = np.eye(3)[up]
    min_area = max(0.05, 2e-5 * summ_area(regions))
    for r in planes:
        if r.area < min_area:
            continue
        n = r.prim.p["a"]
        P = V[np.unique(F[r.tris])]
        u, w = _plane_frame(n)
        Q = np.c_[P @ u, P @ w]
        Qc = Q - Q.mean(0)
        _, sv, vt = np.linalg.svd(Qc, full_matrices=False)
        d2 = Qc @ vt.T
        Lr, Wr = float(np.ptp(d2[:, 0])), float(np.ptp(d2[:, 1]))
        along = vt[0, 0] * u + vt[0, 1] * w
        oblique = _axis_name(n, 0.5) is None
        cen = P.mean(0)
        if oblique and Wr <= chamfer_w and Lr >= 2.5 * Wr:
            nb = [j for ln, j in nbrs.get(r.id, []) if regions[j].kind == "plane"][:4]
            best = None
            for i in range(len(nb)):
                for j in range(i + 1, len(nb)):
                    n1, n2 = regions[nb[i]].prim.p["a"], regions[nb[j]].prim.p["a"]
                    if n1 @ n2 > math.cos(math.radians(30)):
                        continue
                    bis = n1 + n2
                    if np.linalg.norm(bis) < 1e-6:
                        continue
                    bis /= np.linalg.norm(bis)
                    if bis @ n > math.cos(math.radians(20)):
                        best = (n1, n2)
                        break
                if best:
                    break
            if best:
                a1 = math.degrees(math.acos(np.clip(n @ best[0], -1, 1)))
                a2 = math.degrees(math.acos(np.clip(n @ best[1], -1, 1)))
                add("chamfer", rows, r.tris, width=round(Wr, 3), angles_deg=[round(a1, 1), round(a2, 1)],
                    legs=[round(Wr * math.sin(math.radians(a2)) / max(math.sin(math.radians(a1 + a2)), 1e-9), 3),
                          round(Wr * math.sin(math.radians(a1)) / max(math.sin(math.radians(a1 + a2)), 1e-9), 3)],
                    length_mm=round(Lr, 3), along=_axis_name(along, 2) or _r(along, 4), at=_r(cen))
                continue
        tilt = math.degrees(math.acos(min(1.0, abs(float(n @ upv)))))
        if 1.0 <= tilt <= 75.0 and r.area > 0.002 * float(summ_area(regions)):
            P2 = P - cen
            rise = float(np.ptp(P2 @ upv))
            run_dir = np.cross(np.cross(upv, n), upv)
            run = float(np.ptp(P2 @ (run_dir / max(np.linalg.norm(run_dir), 1e-9)))) if np.linalg.norm(run_dir) > 1e-9 else 0.0
            add("ramp", rows, r.tris, angle_deg=round(tilt, 2), rise_mm=round(rise, 3), run_mm=round(run, 3),
                facing=_r(n, 4), at=_r(cen), area_mm2=round(r.area, 2), note="a plane leaning against the up axis")
        elif 75.0 < tilt < 89.9 and oblique:
            add("draft", rows, r.tris, draft_deg=round(90 - tilt, 2), facing=_r(n, 4), at=_r(cen), area_mm2=round(r.area, 2),
                note="a wall that leans off the up axis")
    # ---- walls and gaps between opposite parallel planes
    big = [r for r in planes if r.area > 0.5]
    info = []
    for r in big:
        n = r.prim.p["a"]
        P = V[np.unique(F[r.tris])]
        info.append((r, n, float(r.prim.p["o"] @ n), P))
    pairs = []
    for i in range(len(info)):
        ri, ni, oi, Pi = info[i]
        u, w = _plane_frame(ni)
        bi = np.c_[Pi @ u, Pi @ w]
        bilo, bihi = bi.min(0), bi.max(0)
        for j in range(i + 1, len(info)):
            rj, nj, oj, Pj = info[j]
            if ni @ nj > -0.9998:
                continue
            s = float((Pj.mean(0) - ri.prim.p["o"]) @ ni)
            if abs(s) < 0.05 or abs(s) > 0.45 * float(size.max()):
                continue
            bj = np.c_[Pj @ u, Pj @ w]
            olo, ohi = np.maximum(bilo, bj.min(0)), np.minimum(bihi, bj.max(0))
            ov = np.maximum(ohi - olo, 0)
            if ov.prod() <= 0.25 * min(np.prod(bihi - bilo), np.prod(bj.max(0) - bj.min(0))) or ov.min() < 0.3:
                continue
            pairs.append((abs(s), s < 0, ri, rj, ov, u, w, olo, ohi, ni))
    pairs.sort(key=lambda t: t[0])
    occ = occ0
    used = set()
    groups = {}
    for d, solid, ri, rj, ov, u, w, olo, ohi, ni in pairs:
        if ri.id in used and rj.id in used:
            continue
        if d < 1.5 * occ.h:                              # too thin to confirm on the grid: the sections show it
            continue
        on_i = float(ri.prim.p["o"] @ ni)
        # the space between the two faces must be material (a wall) or air (a gap) over the overlap
        g = np.linspace(0.15, 0.85, 4)
        uu, ww = np.meshgrid(olo[0] + g * (ohi[0] - olo[0]), olo[1] + g * (ohi[1] - olo[1]))
        base = uu.reshape(-1, 1) * u + ww.reshape(-1, 1) * w
        sgn = -1.0 if solid else 1.0
        probe = np.vstack([base + ni * (on_i + sgn * d * f) for f in (0.3, 0.5, 0.7)])
        ins = occ.inside(probe).mean()
        if (solid and ins < 0.85) or (not solid and ins > 0.15):
            continue
        used.update((ri.id, rj.id))
        k = int(np.argmax(ov))
        long_dir = (u, w)[k]
        L, H = float(ov.max()), float(ov.min())
        c2 = (olo + ohi) / 2
        at = c2[0] * u + c2[1] * w + ni * (on_i + sgn * d / 2)
        ax = _axis_name(long_dir, 2)
        if solid and _axis_name(ni, 1) == AXES[up] and H > 4 * d:
            kind = "plate"
        elif solid:
            kind = "rail" if (L > 8 * d and L > 0.3 * float(size.max()) and H < 5 * d) else ("rib" if H > 3 * d and d < 2.5 else "wall")
        else:
            kind = "groove" if (L > 8 * d and L > 0.3 * float(size.max())) else "slot or gap"
        across = _axis_name(ni, 1) or "oblique"
        key = (kind, round(d / 0.05), across, ax or "oblique")
        grp = groups.setdefault(key, [])
        for gr in grp:                                  # facets of one curved wall, or a run of equal ribs nearby
            if np.linalg.norm(np.asarray(gr["at"]) - at) < 12:
                gr["count"] = gr.get("count", 1) + 1
                gr["_tris"] = np.r_[gr["_tris"], ri.tris, rj.tris]
                break
        else:
            grp.append(add(kind, rows, np.r_[ri.tris, rj.tris], thickness=round(d, 3) if solid else None,
                           width=None if solid else round(d, 3), across=across if across != "oblique" else _r(ni, 4),
                           along=ax or _r(long_dir, 4), length_mm=round(L, 3), height_mm=round(H, 3), at=_r(at)))
    for f in rows:
        for k in [k for k, v in f.items() if v is None]:
            del f[k]
    # ---- steps: levels across the up axis
    lv = {}
    for r in planes:
        n = r.prim.p["a"]
        if _axis_name(n, 0.5) == AXES[up]:
            z = round(float(r.prim.p["o"] @ np.eye(3)[up] if abs(n[up]) > 0 else 0), 3)
            z = round(float(np.mean(V[np.unique(F[r.tris])][:, up])), 3)
            key = (z, "up" if n[up] > 0 else "down")
            lv[key] = lv.get(key, 0.0) + r.area
    levels = [{"at": z, "facing": f, "area_mm2": round(a, 2)} for (z, f), a in sorted(lv.items()) if a > 0.5]
    out["levels"] = {"axis": AXES[up], "faces": levels,
                     "note": f"Flat faces across {AXES[up]}: where steps, floors, ledges and tops are."}
    # ---- detail areas: facets and tiny faces in clusters
    tiny = np.zeros(len(F), dtype=bool)
    for r in regions:
        if r.kind in ("facet", "bspline") or r.area < 0.3:
            tiny[r.tris] = True
    details = []
    if tiny.any():
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        e = tiny[adj.t1] & tiny[adj.t2]
        g = coo_matrix((np.ones(int(e.sum())), (adj.t1[e], adj.t2[e])), shape=(len(F), len(F)))
        _, lab = connected_components(g, directed=False)
        ids, cnt = np.unique(lab[tiny], return_counts=True)
        for l, c in zip(ids, cnt):
            if c < 24:
                continue
            ts = np.flatnonzero(tiny & (lab == l))
            P = V[np.unique(F[ts])]
            details.append(add("detail area", rows, ts, triangles=int(c), area_mm2=round(float(TA[ts].sum()), 2),
                               box=[_r(P.min(0)), _r(P.max(0))], at=_r(P.mean(0)),
                               note="facets no simple surface explains: text or embossing, a knurl, a freeform blend or "
                                    "a fine fillet; model it as what it is, or leave it out and say so"))
    out["features"] = sorted(rows, key=lambda f: (FEATURE_ORDER.index(f["kind"]) if f["kind"] in FEATURE_ORDER else 99))
    counts = {}
    for f in rows:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    out["feature_counts"] = counts
    ws = [f["thickness"] for f in rows if "thickness" in f]
    out["wall_thickness"] = {"min_mm": min(ws) if ws else None, "values_mm": sorted(set(ws))[:20],
                             "note": "between opposite parallel flat faces with material between them"}
    dr = [f["draft_deg"] for f in rows if f["kind"] == "draft"]
    out["draft"] = {"tilted_walls": len(dr), "angles_deg": sorted(set(dr))[:12],
                    "note": ("Walls along the up axis are straight (no draft) within 1 degree." if not dr else
                             "Some walls lean off the up axis by these angles (draft or deliberate tapers).")}

    # ---- symmetry
    md = MeshDistance(V, F)
    rng = np.random.default_rng(1)
    S = V if len(V) <= 3000 else V[rng.choice(len(V), 3000, replace=False)]
    c = 0.5 * (lo + hi)
    sym = []
    for k in range(3):
        R = S.copy()
        R[:, k] = 2 * c[k] - R[:, k]
        dd = md.closest(R)[0]
        mx = float(dd.max())
        row = {"plane": f"{AXES[k]} = {c[k]:.4g}", "max_deviation_mm": round(mx, 4), "p95_mm": round(float(np.percentile(dd, 95)), 4)}
        if mx <= 2 * tol:
            row["verdict"] = "symmetric"
        elif row["p95_mm"] <= 2 * tol:
            row["verdict"] = "mostly symmetric"
            row["differs_at"] = where(R[int(np.argmax(dd))], lo, hi)
        else:
            row["verdict"] = "not symmetric"
        sym.append(row)
    out["symmetry"] = sym

    # ---- sections
    lv_up = sorted({f["at"] for f in levels})
    cuts = {}
    if section_levels:
        cuts = {AXES.index(k): list(v) for k, v in section_levels.items()}
    else:
        mids = [(a + b) / 2 for a, b in zip([float(lo[up])] + lv_up, lv_up + [float(hi[up])]) if b - a > 0.2]
        if len(mids) > 5:
            mids = [mids[int(round(i))] for i in np.linspace(0, len(mids) - 1, 5)]
        cuts[up] = mids or [float(c[up])]
        for k in range(3):
            if k != up:
                cuts[k] = [float(lo[k] + f * size[k]) for f in (0.25, 0.5, 0.75)]
    secs = {}
    for k, levels_k in cuts.items():
        secs[AXES[k]] = [secmod.analyse(V, F, k, float(L), tol=max(tol / 2, 0.01)) for L in levels_k]
    out["_sections"] = secs
    out["sections"] = {k: [secmod.public(s) for s in v] for k, v in secs.items()}
    # openings across the up axis: pockets, slots and cutouts
    seen_open = {}
    for s in secs.get(AXES[up], []):
        for r in s["loops"]:
            if r["role"] != "opening" or r["kind"] == "circle":
                continue
            key = (r["kind"], round(r["size"][0], 1), round(r["size"][1], 1))
            if key in seen_open:                        # a row of equal openings: one entry with count and pitch
                f = seen_open[key]
                if r["center"] not in f["_centers"]:
                    f["_centers"].append(r["center"])
                    f["count"] = len(f["_centers"])
                    C = np.array(f["_centers"])
                    k2 = int(np.argmax(np.ptp(C, axis=0)))
                    xs = np.sort(C[:, k2])
                    f["pitch_mm"] = round(float(np.median(np.diff(xs))), 3)
                    f["pattern_along"] = s["coords"][k2]
                continue
            f = add("opening", rows, None, shape=r["kind"], size=r["size"], at_level=s["level"], center=r["center"],
                    **({"corner_radius": r["corner_radius"]} if "corner_radius" in r else {}),
                    **({"width": r["width"], "length": r["length"]} if r["kind"] == "slot" else {}))
            f["_centers"] = [r["center"]]
            seen_open[key] = f
    out["features"] = sorted(rows, key=lambda f: (FEATURE_ORDER.index(f["kind"]) if f["kind"] in FEATURE_ORDER else 99))
    counts = {}
    for f in rows:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    out["feature_counts"] = counts
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


FEATURE_ORDER = ["plate", "hole", "boss", "opening", "slot or gap", "groove", "rail", "wall", "rib", "ramp", "draft", "arc wall",
                 "cone", "sphere", "chamfer", "fillet", "detail area"]


def summ_area(regions) -> float:
    return sum(r.area for r in regions)


def public(res: dict) -> dict:
    """The analysis without private keys (JSON)."""
    out = {k: v for k, v in res.items() if not k.startswith("_")}
    out["features"] = [{k: v for k, v in f.items() if not k.startswith("_")} for f in res["features"]]
    return out


def images(res: dict) -> list:
    """PNG bytes: one picture per principal plane, its sections stacked with dimensions."""
    import io
    out = []
    lo, hi = np.array(res["bbox"][0]), np.array(res["bbox"][1])
    for ax, secs in res["_sections"].items():
        k = AXES.index(ax)
        u, v = secmod.PLANE_UV[k]
        im = secmod.draw(secs, f"{res['name']}: sections across {ax}  (mm, computed on the mesh)",
                         bounds=([lo[u], lo[v]], [hi[u], hi[v]]))
        if im is None:
            continue
        b = io.BytesIO()
        im.save(b, "PNG")
        out.append((ax, b.getvalue()))
    return out


def brief(res: dict, limit: int = 60) -> dict:
    """The analysis as an agent reads it: everything but the long outlines, which stay in the saved JSON."""
    out = public(res)
    secs = {}
    for ax, rows in out["sections"].items():
        secs[ax] = [{"plane": s["plane"], "coords": s["coords"],
                     "loops": [{k: v for k, v in r.items() if k != "outline" or len(v) <= 40} for r in s["loops"][:12]]}
                    for s in rows]
    out["sections"] = secs
    if len(out["features"]) > limit:
        out["features_omitted"] = len(out["features"]) - limit
        out["features"] = out["features"][:limit]
    return out
