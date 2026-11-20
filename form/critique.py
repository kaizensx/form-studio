"""Design critique: look at the design closely, measure what makes it good or crude, and keep a record.

critique(st, project) returns
  * a close-up render of each feature (the feature picked out, the camera framed on it),
  * metrics computed from the B-rep and its tessellation:
      smallest_fillet_mm     smallest radius among blend faces (partial cylinders and tori: fillets and rounds)
      sharp_edge_fraction    share of edge length where faces meet at a crease of more than 25 deg
      symmetry               share of the volume shared with its mirror image in X and in Y (exact booleans; a
                             surface-sample estimate when they fail)
      proportions            bounding-box ratios and the nearest classic ratio (1, sqrt 2, golden, 2, ...)
      surface_mix            area share of planar, cylindrical/conical and free-form surfaces
      sliver_faces           faces under 0.5 mm2 (often a sign of a boolean that nearly missed)
      planned_missing        planned features (plan_design) that have no faces in the solid
  * a checklist the agent answers by looking at the pictures, and
  * one recorded critique pass for the head revision (a staged design cannot be released without it).

All of it is evidence class "heuristic": the numbers are computed, but what counts as good is judgement. A metric is a
prompt to look, never a verdict. The kernel part (KERNEL_OPS) runs in the worker; the rest needs no OCCT.

design_views(st, project) renders the six-view sheet and a section (the design cut in half through its centre, the
cut face picked out), the pictures create_design and update_design return.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

EVIDENCE = "heuristic"
RATIOS = {"1:1": 1.0, "4:5": 1.25, "sqrt2": math.sqrt(2), "3:2": 1.5, "golden": (1 + 5 ** 0.5) / 2, "2:1": 2.0,
          "3:1": 3.0}
SECTION_ID, CUT_BODY = "_section", "_cut"
VERSION = 1


# ---- kernel side ---------------------------------------------------------------------------------------------------

def _surface_kind(face) -> tuple[str, float | None, bool]:
    """(kind, radius, partial) of a face: plane | cylinder | cone | torus | sphere | free."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import (GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus)
    s = BRepAdaptor_Surface(face.wrapped)
    t = s.GetType()
    if t == GeomAbs_Plane:
        return "plane", None, False
    span = abs(s.LastUParameter() - s.FirstUParameter())
    partial = span < 2 * math.pi - 1e-3
    if t == GeomAbs_Cylinder:
        return "cylinder", s.Cylinder().Radius(), partial
    if t == GeomAbs_Cone:
        return "cone", None, partial
    if t == GeomAbs_Torus:
        return "torus", s.Torus().MinorRadius(), True
    if t == GeomAbs_Sphere:
        return "sphere", s.Sphere().Radius(), partial
    return "free", None, False


def _edge_angles(shape, max_edges=5000):
    """[(length, crease angle deg)] for edges shared by two faces (sampled when there are many)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED  # noqa: F401
    from OCP.TopExp import TopExp
    try:
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as EdgeFaceMap
    except ImportError:                                   # newer OCP names the template instance
        from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EdgeFaceMap
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    m = EdgeFaceMap()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    n = m.Extent()
    step = max(1, n // max_edges)
    out = []
    for i in range(1, n + 1, step):
        e = TopoDS.Edge(m.FindKey(i))
        faces = list(m.FindFromIndex(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        try:
            c = BRepAdaptor_Curve(e)
            L = GCPnts_AbscissaPoint.Length_s(c)
            p = c.Value((c.FirstParameter() + c.LastParameter()) / 2)
        except Exception:
            continue
        uniq = []
        for f in faces:
            if not any(f.IsSame(g) for g in uniq):
                uniq.append(f)
        if len(uniq) != 2:
            continue
        ns = []
        for f in uniq:
            f = TopoDS.Face(f)
            try:
                surf = BRep_Tool.Surface_s(f)
                pr = GeomAPI_ProjectPointOnSurf(p, surf)
                u, v = pr.LowerDistanceParameters()
                props = BRepLProp_SLProps(BRepAdaptor_Surface(f), u, v, 1, 1e-6)
                if not props.IsNormalDefined():
                    raise ValueError
                nn = props.Normal()
                vec = np.array([nn.X(), nn.Y(), nn.Z()])
                if f.Orientation() == TopAbs_REVERSED:
                    vec = -vec
                ns.append(vec)
            except Exception:
                break
        if len(ns) == 2:
            cosang = float(np.clip(np.dot(ns[0], ns[1]), -1, 1))
            out.append((L * step, math.degrees(math.acos(cosang))))
    return out


def _samples(P, T, n=4000, seed=1):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    if area.sum() <= 0:
        return P[:n]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(T), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]


def symmetry_brep(shape, lo, hi) -> dict | None:
    """Volume shared by the solid and its mirror image (in the YZ plane, then the XZ plane, through the bounding-box
    centre), as a share of its volume: 1.0 = perfectly symmetric. Exact booleans; None when they fail."""
    from build123d import Plane, mirror
    ctr = [(a + b) / 2 for a, b in zip(lo, hi)]
    out = {}
    try:
        for name, normal in (("mirror_x", (1, 0, 0)), ("mirror_y", (0, 1, 0))):
            m = mirror(shape, about=Plane(origin=tuple(ctr), z_dir=normal))
            inter = shape & m
            v = float(inter.volume) if inter is not None else 0.0
            out[name] = round(min(1.0, v / shape.volume), 3)
        return out
    except Exception:
        return None


def symmetry(P, T, lo, hi) -> dict:
    """Share of surface samples that land within 1 % of the diagonal of the surface when mirrored in X (YZ plane
    through the bounding-box centre) and in Y."""
    S = _samples(P, T, 3000)
    diag = float(np.linalg.norm(np.asarray(hi) - np.asarray(lo)))
    tol = max(0.01 * diag, 0.2)
    ctr = (np.asarray(lo) + np.asarray(hi)) / 2
    out = {}
    for ax, name in ((0, "mirror_x"), (1, "mirror_y")):
        M = S.copy()
        M[:, ax] = 2 * ctr[ax] - M[:, ax]
        d = np.full(len(M), np.inf)
        for i in range(0, len(M), 500):                          # nearest sample, in blocks
            blk = M[i:i + 500]
            d[i:i + 500] = np.sqrt(((blk[:, None, :] - S[None, :, :]) ** 2).sum(-1)).min(1)
        out[name] = round(float((d <= tol).mean()), 3)
    return out


def op_critique_metrics(key, recipe_id, values, tol=0.05):
    from . import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    shape = model["shape"]
    mesh_design = getattr(model["recipe"], "mesh", False)
    kinds, radii, slivers = {"plane": 0.0, "cylinder": 0.0, "cone": 0.0, "torus": 0.0, "sphere": 0.0, "free": 0.0}, [], 0
    feats = {}
    for f in model["faces"]:
        fb = feats.setdefault(f["feature"], {"area": 0.0, "lo": [1e9] * 3, "hi": [-1e9] * 3, "faces": 0})
        fb["area"] += f["area"]
        fb["faces"] += 1
        fb["lo"] = np.minimum(fb["lo"], f["P"].min(0)).tolist()
        fb["hi"] = np.maximum(fb["hi"], f["P"].max(0)).tolist()
        if f["area"] < 0.5:
            slivers += 1
        if mesh_design:
            continue
        try:
            k, r, partial = _surface_kind(f["face"])
        except Exception:
            k, r, partial = "free", None, False
        kinds[k] += f["area"]
        if r is not None and (k == "torus" or (k == "cylinder" and partial)) and r < 50:
            radii.append(r)
    total = sum(kinds.values()) or 1.0
    edges = [] if mesh_design else _edge_angles(shape)
    elen = sum(L for L, _ in edges) or 1.0
    sharp = sum(L for L, a in edges if a > 25.0) / elen if edges else None
    P, T = kernel._mesh_arrays(model)
    lo, hi = model["bbox"]
    dims = sorted([b - a for a, b in zip(lo, hi)], reverse=True)
    ratios = []
    for big, small, label in ((dims[0], dims[1], "long:mid"), (dims[1], dims[2], "mid:short")):
        if small > 1e-6:
            r = big / small
            name, val = min(RATIOS.items(), key=lambda kv: abs(math.log(r / kv[1])))
            ratios.append({"pair": label, "ratio": round(r, 3), "nearest": name, "off_pct": round(100 * abs(r / val - 1), 1)})
    return {
        "smallest_fillet_mm": round(min(radii), 3) if radii else None,
        "fillet_faces": len(radii),
        "sharp_edge_fraction": None if sharp is None else round(sharp, 3),
        "edges_sampled": len(edges),
        "symmetry": (None if mesh_design else symmetry_brep(shape, lo, hi)) or symmetry(P, T, lo, hi),
        "proportions": {"bbox_mm": [round(b - a, 2) for a, b in zip(lo, hi)], "ratios": ratios},
        "surface_mix": {k: round(v / total, 3) for k, v in kinds.items() if v} if not mesh_design else None,
        "sliver_faces": slivers,
        "features": {k: {"area": round(v["area"], 2), "faces": v["faces"], "lo": v["lo"], "hi": v["hi"]} for k, v in feats.items()},
        "volume_mm3": round(model["volume"], 2),
        "solids": len(shape.solids()),
        "evidence": EVIDENCE,
    }


def op_section_view(key, recipe_id, values, axis="y", tol=0.05):
    """The solid cut through its bounding-box centre normal to axis, the +side kept; cut faces tagged _section."""
    from build123d import Align, Box, Pos
    from . import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    shape = model["shape"]
    lo, hi = np.array(model["bbox"][0]), np.array(model["bbox"][1])
    c, size = (lo + hi) / 2, (hi - lo) + 10
    ax = "xyz".index(axis)
    off = np.zeros(3)
    off[ax] = size[ax] / 2
    half = shape & (Pos(*(c + off)) * Box(*size))
    if half is None or not half.faces():
        raise ValueError("The section is empty.")
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    BRepMesh_IncrementalMesh(half.wrapped, tol, False, 0.25, True)
    groups = {SECTION_ID: ([], []), CUT_BODY: ([], [])}
    for f in half.faces():
        vs, ts = f.tessellate(tol, 0.25)
        if not ts:
            continue
        P = np.array([(p.X, p.Y, p.Z) for p in vs], dtype=np.float32)
        on_cut = f.geom_type.name == "PLANE" and abs(float(P[:, ax].min()) - c[ax]) < 1e-3 and abs(float(P[:, ax].max()) - c[ax]) < 1e-3
        g = groups[SECTION_ID if on_cut else CUT_BODY]
        g[1].append(np.array(ts, dtype=np.uint32) + sum(len(x) for x in g[0]))
        g[0].append(P)
    mesh = [{"feature": k, "positions": kernel._b64(np.concatenate(P)), "indices": kernel._b64(np.concatenate(T))}
            for k, (P, T) in groups.items() if P]
    return {"mesh": mesh, "edges": kernel._b64(kernel._edges(half)), "bbox": [lo.tolist(), hi.tolist()],
            "cut_at": float(c[ax]), "axis": axis}


KERNEL_OPS = {"critique_metrics": op_critique_metrics, "section_view": op_section_view}


# ---- engine side ---------------------------------------------------------------------------------------------------

def _renders_dir(st, p) -> Path:
    d = st.dir(p["id"]) / "artifacts" / "renders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def design_views(st, pid: str) -> dict:
    """Six-view sheet and a section of the head revision, as PNG files (cached by geometry). Returns
    {"sheet": path, "section": path or None, "section_error": str, "caption": str}."""
    from . import render as rendering
    p = st.load(pid)
    recipe = st.recipe(p)
    feats = [{"id": f.id, "label": f.label} for f in recipe.features]
    key = st.keys(p)["geometry"]
    d = _renders_dir(st, p)
    sheet = d / f"{key}-sheet6-v{rendering.VERSION}.{VERSION}.png"
    v = st.view(p)
    title = f"{p['name']} - r{p['head']:02d}"
    if not sheet.exists():
        pngs = [rendering.render_png(v, feats, vw, None, size=(560, 420), title=title)
                for vw in ("iso", "iso_back", "front", "right", "top", "bottom")]
        sheet.write_bytes(rendering.contact_sheet(pngs, cols=3))
    out = {"sheet": sheet, "section": None, "section_error": "",
           "caption": f"{title}: six views (iso, iso back, front, right, top, bottom), bounding box "
                      + " x ".join(f"{b - a:.1f}" for a, b in zip(*v["bbox"])) + " mm"
                      + (f"; {v['mesh_texture']['label']}" if v.get("mesh_texture") else "") + "."}
    sec = d / f"{key}-section-y-v{rendering.VERSION}.{VERSION}.png"
    if not sec.exists():
        try:
            sv = st._k("section_view", key=key, recipe_id=st.rid(p), values=st.rev(p)["values"], axis="y", p=p, timeout=120)
            sf = [{"id": CUT_BODY, "label": "Body (cut in half)"}, {"id": SECTION_ID, "label": "Section through the centre"}]
            sec.write_bytes(rendering.render_png(sv, sf, "front", SECTION_ID, size=(900, 640),
                                                 title=f"{title} - section at y = {sv['cut_at']:.1f} mm"))
        except Exception as e:                                   # a section that will not cut is reported, not faked
            out["section_error"] = f"No section: {e}"
            return out
    out["section"] = sec
    return out


def _closeups(st, p, v, metrics, limit=6) -> bytes | None:
    from . import render as rendering
    recipe = st.recipe(p)
    feats = [{"id": f.id, "label": f.label} for f in recipe.features]
    present = metrics.get("features", {})
    order = [f["id"] for f in feats if f["id"] in present]
    order = sorted(order, key=lambda k: -present[k]["area"])[:limit] if len(order) > limit else order
    pngs = []
    for fid in order:
        b = present[fid]
        lo, hi = np.array(b["lo"]), np.array(b["hi"])
        c, ext = (lo + hi) / 2, np.maximum((hi - lo) * 0.65, 4.0)
        try:
            pngs.append(rendering.render_png(v, feats, "iso", fid, size=(520, 400), title=f"Close-up: {fid}",
                                             frame_box=(c - ext, c + ext), camera=(-55.0, 28.0)))
        except Exception:
            continue
    return rendering.contact_sheet(pngs, cols=3 if len(pngs) > 4 else 2) if len(pngs) > 1 else (pngs[0] if pngs else None)


def checklist(metrics: dict, plan: dict | None, purpose: str) -> list[dict]:
    def item(q, flag, why):
        return {"question": q, "attention": bool(flag), "why": why}
    m = metrics
    fil, sharp = m.get("smallest_fillet_mm"), m.get("sharp_edge_fraction")
    sym = m.get("symmetry", {})
    mix = m.get("surface_mix") or {}
    items = [
        item("Does every view read as the object asked for (silhouette front and side), not as a primitive?",
             (mix.get("plane", 0) > 0.85 and m.get("fillet_faces", 0) == 0), "Mostly flat faces and no rounds: check it is "
             "not a box standing in for a designed object."),
        item("Are edges where hands, faces or other parts touch softened?", sharp is not None and sharp > 0.5,
             f"{(sharp or 0) * 100:.0f} % of edge length is a sharp crease; smallest fillet "
             + (f"{fil:g} mm." if fil is not None else "none.")),
        item("Is every planned feature visible in the close-ups, where the plan put it?", bool(m.get("planned_missing")),
             "Missing: " + ", ".join(m.get("planned_missing") or []) if m.get("planned_missing") else "All planned features have faces."),
        item("Is the symmetry intended (and is any asymmetry deliberate)?",
             min(sym.values()) < 0.6 if sym else False, f"Mirror match X {sym.get('mirror_x', 0):.0%}, Y {sym.get('mirror_y', 0):.0%}."),
        item("Do the proportions look intentional (the main masses relate, nothing looks stretched by accident)?",
             any(r["off_pct"] > 12 for r in m.get("proportions", {}).get("ratios", [])),
             "; ".join(f"{r['pair']} {r['ratio']} (near {r['nearest']}, {r['off_pct']} % off)" for r in m.get("proportions", {}).get("ratios", []))),
        item("Are there sliver faces or boolean artefacts in the close-ups?", m.get("sliver_faces", 0) > 0,
             f"{m.get('sliver_faces', 0)} faces under 0.5 mm2."),
        item("Is the section sound: even walls, no voids, no paper-thin spots, mechanisms clear of each other?", False,
             "Look at the section picture create_design/update_design returned."),
    ]
    if plan and plan.get("mechanisms"):
        items.append(item("Do the mechanisms have their clearances and are they declared (assembly joints, Mate)?", False,
                          "Planned: " + ", ".join(str(x) for x in plan["mechanisms"])[:200]))
    if plan and plan.get("textures"):
        items.append(item("Is each texture in the right tier (B-rep vs mesh texture) and labelled?", False,
                          "Planned: " + ", ".join(str(x) for x in plan["textures"])[:200]))
    if purpose != "model":
        items.append(item("Will it print: flat base on the bed, overhangs under 45 deg or supported, walls >= 1.2 mm?", False,
                          "get_project checks walls and overhangs (computed)."))
    return items


def run(st, pid: str, notes: str = "") -> dict:
    """Compute metrics, render close-ups, build the checklist and record one critique pass for the head revision."""
    from . import purpose as purpose_mod
    from . import staged
    p = st.load(pid)
    key = st.keys(p)["geometry"]
    metrics = st._k("critique_metrics", key=key, recipe_id=st.rid(p), values=st.rev(p)["values"], p=p, timeout=240)
    plan = (p.get("design") or {}).get("plan")
    recipe_feats = {f.id for f in st.recipe(p).features}
    if plan:
        planned = [f["id"] for f in plan.get("features", [])]
        metrics["planned_missing"] = [f for f in planned if f not in metrics.get("features", {})]
        metrics["planned_not_declared"] = [f for f in planned if f not in recipe_feats]
    else:
        metrics["planned_missing"] = []
    v = st.view(p)
    png = _closeups(st, p, v, metrics)
    f = None
    if png:
        f = _renders_dir(st, p) / f"{key}-closeups-v{VERSION}.png"
        f.write_bytes(png)
    purpose = purpose_mod.of(p)
    items = checklist(metrics, plan, purpose)
    summary = {"metrics": {k: metrics[k] for k in ("smallest_fillet_mm", "sharp_edge_fraction", "symmetry", "sliver_faces",
                                                    "planned_missing") if k in metrics},
               "attention": [i["question"] for i in items if i["attention"]], "evidence": EVIDENCE}
    rec = staged.record_critique(st, pid, p["head"], summary, notes)
    return {"project": pid, "rev": p["head"], "metrics": metrics, "checklist": items, "closeups": str(f) if f else None,
            "recorded": {"rev": rec["rev"], "ts": rec["ts"]}, "evidence": EVIDENCE,
            "next": "Look at the close-ups and the section. Fix what the checklist flags with update_design, then "
                    "critique again; release needs a recorded critique of the revision you release."}
