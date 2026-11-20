"""compare_to_reference: how far a design (or one part of it) is from the mesh it rebuilds, and where.

- Two-sided Hausdorff, mean and 99th percentile, from points sampled on both surfaces (exact point-to-triangle
  distances, form/recon/distance.py).
- The worst regions: samples further than the tolerance, grouped by place, each with its largest deviation, its area,
  where it is in words and coordinates, the nearest feature of the reference analysis, and which way it is off (the
  design has material the mesh lacks, or lacks material the mesh has).
- Per feature of the reference analysis (holes, bosses, fillets, slots, walls...): the largest deviation over its
  faces, and for round features the design's own diameter or radius fitted about the same axis.
- A picture: the design coloured by its distance to the mesh, and the mesh coloured by its distance to the design.

Evidence: computed on the design's tessellation and the mesh as given.
"""
from __future__ import annotations

import base64

import numpy as np

from .analyze import _r, where


def _arr(b64, dtype, cols):
    return np.frombuffer(base64.b64decode(b64), dtype=dtype).reshape(-1, cols)


def design_mesh(view: dict, part: str | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The design's triangles from a Studio view, in the assembled frame; only `part` when given."""
    asm = view.get("assembly") or {}
    place = {}
    for p in asm.get("parts", []) if not asm.get("error") else []:
        M = np.array(p["placement"]["m"], dtype=np.float64)
        place[p["id"]] = M
        place[p.get("label", p["id"])] = M
    Ps, Ts, off = [], [], 0
    known = sorted({m.get("part", "") for m in view["mesh"] if m.get("part")})
    labels = {p["id"]: p.get("label", "") for p in asm.get("parts", [])} if asm else {}
    if part and part not in known:
        by_label = [i for i, lab in labels.items() if lab.lower() == part.lower()]
        if by_label:
            part = by_label[0]
        else:
            raise ValueError(f"The design has no part “{part}”. Parts: "
                             + (", ".join(f"{i} ({labels.get(i, '')})" for i in known) or "none (it is one part)") + ".")
    for m in view["mesh"]:
        if part and m.get("part") != part:
            continue
        P = _arr(m["positions"], np.float32, 3).astype(np.float64)
        T = _arr(m["indices"], np.uint32, 3).astype(np.int64)
        M = place.get(m.get("part", ""))
        if M is not None:
            P = P @ M[:, :3].T + M[:, 3]
        Ps.append(P)
        Ts.append(T + off)
        off += len(P)
    if not Ps:
        raise ValueError("The design has no triangles to compare.")
    return np.concatenate(Ps), np.concatenate(Ts)


def compare(V, F, P, T, tol: float = 0.1, analysis: dict | None = None, name: str = "part") -> dict:
    from ..recon.distance import MeshDistance, sample_surface
    from .occupancy import Occupancy
    diag = float(np.linalg.norm(np.ptp(np.vstack([V, P]), axis=0)))
    spacing = max(diag / 400, 0.05)
    SA, tA, spa = sample_surface(V, F, spacing)           # on the mesh
    SB, tB, spb = sample_surface(P, T, spacing)           # on the design
    mdB, mdA = MeshDistance(P, T, spacing), MeshDistance(V, F, spacing)
    dA = mdB.closest(SA)[0]
    dB = mdA.closest(SB)[0]
    lo = np.minimum(V.min(0), P.min(0))
    hi = np.maximum(V.max(0), P.max(0))
    hd = float(max(dA.max(), dB.max()))
    out = {"evidence": "computed (design tessellation against the mesh as given)", "name": name, "tolerance_mm": tol,
           "hausdorff_mm": round(hd, 4), "mesh_to_design_max_mm": round(float(dA.max()), 4),
           "design_to_mesh_max_mm": round(float(dB.max()), 4), "mean_mm": round(float(np.r_[dA, dB].mean()), 4),
           "p99_mm": round(float(np.percentile(np.r_[dA, dB], 99)), 4),
           "within_tolerance": bool(hd <= tol),
           "over_tolerance_area_pct": round(100 * float(np.r_[dA > tol, dB > tol].mean()), 3),
           "sample_spacing_mm": round(float(max(spa, spb)), 4), "samples": int(len(SA) + len(SB))}
    # which way is it off: inside or outside the other solid
    occ_design = Occupancy(P, T, h=max(diag / 500, 0.05))
    occ_mesh = Occupancy(V, F, h=max(diag / 500, 0.05))
    bad_pts, bad_dev, bad_kind = [], [], []
    mA = dA > tol
    if mA.any():
        ins = occ_design.inside(SA[mA])
        bad_pts.append(SA[mA]); bad_dev.append(dA[mA])
        bad_kind.append(np.where(ins, "extra", "missing"))   # mesh surface inside the design: the design has extra
    mB = dB > tol
    if mB.any():
        ins = occ_mesh.inside(SB[mB])
        bad_pts.append(SB[mB]); bad_dev.append(dB[mB])
        bad_kind.append(np.where(ins, "missing", "extra"))   # design surface inside the mesh: it lacks material
    feats = [f for f in (analysis or {}).get("features", []) if f.get("at")]
    regions = []
    if bad_pts:
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree
        Q, D, K = np.vstack(bad_pts), np.concatenate(bad_dev), np.concatenate(bad_kind)
        if len(Q) > 60000:
            sel = np.random.default_rng(0).choice(len(Q), 60000, replace=False)
            Q, D, K = Q[sel], D[sel], K[sel]
        tree = cKDTree(Q)
        g = tree.sparse_distance_matrix(tree, max(2.5 * spacing, 1.0), output_type="coo_matrix")
        _, lab = connected_components(g, directed=False)
        for l in np.unique(lab):
            s = lab == l
            c = Q[s][np.argmax(D[s])]
            kinds, cnt = np.unique(K[s], return_counts=True)
            row = {"max_mm": round(float(D[s].max()), 3), "area_mm2": round(float(s.sum()) * spacing * spacing / 2, 2),
                   "at": _r(c), "where": where(c, lo, hi), "box": [_r(Q[s].min(0)), _r(Q[s].max(0))],
                   "design_has": {"extra": "material the mesh does not have", "missing": "less material than the mesh"}[
                       str(kinds[np.argmax(cnt)])]}
            if feats:
                dd = [float(np.linalg.norm(np.asarray(f["at"]) - c)) for f in feats]
                j = int(np.argmin(dd))
                if dd[j] < 8:
                    row["near_feature"] = _feature_name(feats[j])
            regions.append(row)
        regions.sort(key=lambda r: -(r["max_mm"] * max(r["area_mm2"], 0.01) ** 0.5))
    out["worst_regions"] = regions[:12]
    out["regions_over_tolerance"] = len(regions)
    # per feature of the reference
    rows = []
    if analysis is not None:
        tri_dev = np.zeros(len(F))
        np.maximum.at(tri_dev, tA, dA)
        from ..recon import fit as fitmod
        for f in analysis.get("features", []):
            tr = f.get("_tris")
            if tr is None or not len(tr):
                continue
            dev = float(tri_dev[tr].max())
            row = {"feature": _feature_name(f), "max_deviation_mm": round(dev, 3), "ok": bool(dev <= tol)}
            if f["kind"] in ("hole", "boss", "fillet") and isinstance(f.get("axis"), str) and ("diameter" in f or "radius" in f):
                # the design's own radius about the same axis, from its surface points near the feature
                ref_pts = V[np.unique(F[tr])]
                k = "xyz".index(f["axis"])
                a = np.eye(3)[k]
                try:
                    from scipy.spatial import cKDTree
                    tree_r = cKDTree(ref_pts)
                    dd, _ = tree_r.query(SB, k=1)
                    pts = SB[dd < max(4 * tol, 0.6)]
                    if len(pts) >= 12:
                        pr = fitmod.fit_on_axis("cylinder", pts, np.asarray(f["at"], dtype=np.float64), a)
                        if pr is not None and pr.max < max(tol, 0.05) * 3:
                            if "diameter" in f:
                                row["reference_diameter"] = f["diameter"]
                                row["design_diameter"] = round(2 * float(pr.p["r"]), 3)
                            else:
                                row["reference_radius"] = f["radius"]
                                row["design_radius"] = round(float(pr.p["r"]), 3)
                except Exception:                       # noqa: BLE001
                    pass
            rows.append(row)
        rows.sort(key=lambda r: -r["max_deviation_mm"])
    out["features"] = rows[:40]
    out["features_over_tolerance"] = sum(1 for r in rows if not r["ok"])
    out["_P"], out["_T"], out["_V"], out["_F"] = P, T, V, F
    out["_rec_dev"] = mdA.closest(P)[0]
    out["_mesh_dev"] = mdB.closest(V)[0]
    return out


def _feature_name(f) -> str:
    bits = [f["id"]]
    if "diameter" in f:
        bits.append(f"dia {f['diameter']:g}")
    elif "radius" in f:
        bits.append(f"R{f['radius']:g}")
    elif "thickness" in f:
        bits.append(f"{f['thickness']:g} thick")
    elif "width" in f and isinstance(f["width"], (int, float)):
        bits.append(f"{f['width']:g} wide")
    if f.get("where"):
        bits.append(f"({f['where']})")
    return " ".join(bits)


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def picture(res: dict, title: str) -> bytes:
    """The design coloured by its distance to the mesh (left) and the mesh by its distance to the design (right)."""
    from .. import render
    from ..analysis import render_map_png
    from ..recon.verify import deviation_map
    tol = res["tolerance_mm"]
    pngs = []
    for P, T, dev, lab in ((res["_P"], res["_T"], res["_rec_dev"], "design, by distance to the mesh"),
                           (res["_V"], res["_F"], res["_mesh_dev"], "mesh, by distance to the design")):
        m = deviation_map(P, T, dev, tol)
        m["tessellation_mm"] = res["sample_spacing_mm"]
        m["label"] = f"Deviation: {lab}"
        pngs.append(render_map_png(m, f"{title}: {lab}", "iso", size=(900, 640)))
    return render.contact_sheet(pngs, cols=2)
