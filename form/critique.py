"""Design critique: look at the design closely, measure what makes it good or crude, and keep a record.

critique(st, project) returns
  * a close-up render of each feature (the feature picked out, the camera framed on it),
  * metrics computed from the B-rep and its tessellation:
      smallest_fillet_mm     smallest radius among blend faces (partial cylinders and tori: fillets and rounds)
      sharp_edge_fraction    share of edge length where faces meet at a crease of more than 25 deg
      symmetry               share of the surface that lands on the surface again when mirrored in X and in Y
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

import json
import math
from pathlib import Path

import numpy as np

EVIDENCE = "heuristic"
RATIOS = {"1:1": 1.0, "4:5": 1.25, "sqrt2": math.sqrt(2), "3:2": 1.5, "golden": (1 + 5 ** 0.5) / 2, "2:1": 2.0,
          "3:1": 3.0}
SECTION_ID, CUT_BODY = "_section", "_cut"
VERSION = 4


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


def _edge_angles(shape, max_edges=1500, skip=frozenset()):
    """[(length, crease angle deg)] for edges shared by two faces (sampled when there are many). Edges whose faces
    are both in skip (hashes of TopoDS faces: a texture's facets) are left out."""
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
        if skip and all(hash(f) in skip for f in uniq):
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


def symmetry(P, T, lo, hi) -> dict:
    """Share of the surface that lands on the surface again when mirrored in the YZ plane (mirror_x) and the XZ plane
    (mirror_y) through the bounding-box centre. Dense area-weighted samples and a k-d tree (scipy, which build123d
    depends on); the tolerance is 1 % of the diagonal or 2.5 sample spacings, whichever is larger. Never a boolean,
    so it cannot stall on a heavy free-form solid."""
    from scipy.spatial import cKDTree
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    area = float((np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2).sum())
    diag = float(np.linalg.norm(np.asarray(hi) - np.asarray(lo)))
    n = int(min(200_000, max(20_000, area / max(diag * 0.004, 0.05) ** 2)))
    S = _samples(P, T, n)
    spacing = (area / n) ** 0.5
    tol = max(0.01 * diag, 2.5 * spacing, 0.2)
    tree = cKDTree(S)
    probe = S[:: max(1, n // 8000)]
    ctr = (np.asarray(lo) + np.asarray(hi)) / 2
    out = {}
    for ax, name in ((0, "mirror_x"), (1, "mirror_y")):
        M = probe.copy()
        M[:, ax] = 2 * ctr[ax] - M[:, ax]
        d, _ = tree.query(M, k=1)
        out[name] = round(float((d <= tol).mean()), 3)
    return out


def walls(shape, P, T, n: int = 500, seed: int = 5, skip=None) -> dict:
    """Wall thickness by rays: from n area-weighted points on the surface, along the inward normal, the distance to
    the next surface of the solid (OCCT IntCurvesFace_ShapeIntersector on the B-rep). Reports min, 2nd and 5th
    percentile, median, and the points thinner than 35 % of the median: on a shell those are break-through (the inner
    surface crossing the outer) or paper-thin spots. Rays that leave the solid without hitting are ignored.
    skip: a boolean per triangle to leave out (texture facets)."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    nrm = np.cross(b - a, c - a)
    area = np.linalg.norm(nrm, axis=1) / 2
    w = area.copy()
    if skip is not None:
        w[np.asarray(skip, bool)] = 0
    if w.sum() <= 0:
        return {"samples": 0}
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(T), size=n, p=w / w.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    S = (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]
    N = nrm[idx] / np.maximum(np.linalg.norm(nrm[idx], axis=1, keepdims=True), 1e-12)
    it = IntCurvesFace_ShapeIntersector()
    it.Load(shape.wrapped, 1e-4)
    th, where = [], []
    back = 0.5                                 # start outside the surface: the tessellation is off the B-rep by up to tol
    for p, nv in zip(S, N):
        d = -nv
        start = p - d * back
        try:
            it.Perform(gp_Lin(gp_Pnt(*map(float, start)), gp_Dir(*map(float, d))), 0.0, 1e5)
        except Exception:
            continue
        if not it.IsDone() or it.NbPnt() < 2:
            continue
        ws = sorted(it.WParameter(i) for i in range(1, it.NbPnt() + 1))
        entry = next((w for w in ws if abs(w - back) < 0.4), None)     # the surface the point lies on
        if entry is None:
            continue
        nxt = [w for w in ws if w > entry + 0.02]           # the same point twice (an edge between faces) is not a wall
        if not nxt:
            continue
        th.append(nxt[0] - entry)
        where.append(p)
    if not th:
        return {"samples": 0}
    th = np.array(th)
    where = np.array(where)
    med = float(np.median(th))
    # a ray that starts beside a sharp edge (a cut rim, a slot, the open edge of a shell) grazes the next face and
    # reads thin; samples within 1.2 x the median wall of a sharp edge are left out (a real break-through thins the
    # wall well before its rim, so it is still found)
    near = _near_sharp_edges(P, T, where, 1.2 * med)
    keep = ~near if (~near).sum() >= 50 else np.ones(len(th), bool)
    th, where = th[keep], where[keep]
    thin = th < 0.35 * med
    pts = [tuple(round(float(x), 1) for x in where[i]) for i in np.nonzero(thin)[0][:6]]
    return {"samples": int(len(th)), "near_edges_skipped": int((~keep).sum()), "min_mm": round(float(th.min()), 2),
            "p2_mm": round(float(np.percentile(th, 2)), 2), "p5_mm": round(float(np.percentile(th, 5)), 2),
            "median_mm": round(med, 2), "thin_fraction": round(float(thin.mean()), 3), "thin_at": pts}


def _near_sharp_edges(P, T, S, radius, deg=50.0, ignore=None):
    """For each point of S: is it within radius of a sharp edge of the mesh (adjacent triangles turn > deg)?
    ignore: a bool per triangle; edges of those triangles never count (a grip texture's ridges are meant to be felt)."""
    from scipy.spatial import cKDTree
    _, ids = np.unique(np.round(P / 1e-4).astype(np.int64), axis=0, return_inverse=True)
    ids = ids.reshape(-1)
    F = ids[T]
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    tri = np.tile(np.arange(len(F)), 3)
    E = np.sort(E, axis=1)
    order = np.lexsort((E[:, 1], E[:, 0]))
    E, tri = E[order], tri[order]
    same = np.all(E[1:] == E[:-1], axis=1)
    i = np.nonzero(same)[0]
    cosang = np.einsum("ij,ij->i", n[tri[i]], n[tri[i + 1]])
    sharp = i[cosang < np.cos(np.radians(deg))]
    # edges with one triangle only (open boundaries) are sharp too
    single = np.ones(len(E), bool)
    single[i] = False
    single[i + 1] = False
    if ignore is not None:
        ig = np.asarray(ignore, bool)
        sharp = sharp[~(ig[tri[sharp]] | ig[tri[sharp + 1]])]
        single &= ~ig[tri]
    pos = np.zeros((ids.max() + 1, 3))
    pos[ids] = P
    sel = np.concatenate([sharp, np.nonzero(single)[0]])
    if not len(sel):
        return np.zeros(len(S), bool)
    p0, p1 = pos[E[sel, 0]], pos[E[sel, 1]]
    k = np.maximum(1, np.ceil(np.linalg.norm(p1 - p0, axis=1) / max(radius / 2, 1e-3)).astype(int))
    k = np.minimum(k, 200)
    rep = np.repeat(np.arange(len(sel)), k + 1)
    t = np.concatenate([np.linspace(0, 1, m + 1) for m in k])
    mids = p0[rep] + (p1 - p0)[rep] * t[:, None]
    d, _ = cKDTree(mids).query(S, k=1)
    return d < radius


def form_views(model, P, T, product_class: str | None) -> dict:
    """Silhouettes and depth maps (form.product_classes.views) of the design, the class assessment when the brief
    names a product class, and the silhouette's curvature kinks and front-view mirror match in any case."""
    from . import product_classes as pc
    tri_feat = np.concatenate([np.full(len(f["T"]), i) for i, f in enumerate(model["faces"])])
    names = [f["feature"].lower() for f in model["faces"]]
    trans = pc.CLASSES.get(product_class or "", {}).get("transparent", ["visor", "lens", "glass", "shield"])
    keep_face = np.array([not any(w in n for w in trans) for n in names])
    V = pc.views(P, T, keep=keep_face[tri_feat])
    out = {"front_mirror": pc.mirror_match(V["front"]["mask"]),
           "kinks": {vn: pc.kinks(pc.profiles(V[vn]["mask"]))[:6] for vn in ("side", "front", "top")}}
    if product_class in pc.CLASSES:
        areas = {}
        for f in model["faces"]:
            areas[f["feature"]] = areas.get(f["feature"], 0.0) + f["area"]
        out["class"] = pc.assess(product_class, V, areas)
    return out


def radius_tiers(radii) -> int:
    """How many distinct tiers the blend radii fall into: sorted radii start a new tier when one is at least 1.8x the
    tier's smallest (0.6 / 0.8 / 1.2 mm is one tier; 0.8 / 2 / 6 mm are three)."""
    tiers, base = 0, None
    for r in sorted(x for x in radii if x and x > 0.05):
        if base is None or r >= base * 1.8:
            tiers, base = tiers + 1, r
    return tiers


def op_critique_metrics(key, recipe_id, values, tol=0.05, product_class=None):
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
    # texture features (a knurl, emboss cells: many small facets) are sharp on purpose; measure the form without them
    texture = sorted(k for k, b in feats.items() if b["faces"] >= 150 and b["area"] / b["faces"] < 6.0)
    skip = frozenset(hash(f["face"].wrapped) for f in model["faces"] if f["feature"] in texture)
    edges = [] if mesh_design else _edge_angles(shape, skip=skip)
    elen = sum(L for L, _ in edges) or 1.0
    sharp = sum(L for L, a in edges if a > 25.0) / elen if edges else None
    tangent = sum(L for L, a in edges if a < 3.0) / elen if edges else None
    P, T = kernel._mesh_arrays(model)
    lo, hi = model["bbox"]
    dims = sorted([b - a for a, b in zip(lo, hi)], reverse=True)
    ratios = []
    for big, small, label in ((dims[0], dims[1], "long:mid"), (dims[1], dims[2], "mid:short")):
        if small > 1e-6:
            r = big / small
            name, val = min(RATIOS.items(), key=lambda kv: abs(math.log(r / kv[1])))
            ratios.append({"pair": label, "ratio": round(r, 3), "nearest": name, "off_pct": round(100 * abs(r / val - 1), 1)})
    folds, wall, form = None, None, None
    if not mesh_design:
        from .craft.organic import loft_report
        try:
            folds = loft_report(shape, grid=22)
        except Exception as e:                                   # a surface OCCT cannot evaluate is reported, not hidden
            folds = {"error": f"{type(e).__name__}: {e}"[:160]}
        try:
            tex_tri = np.concatenate([np.full(len(f["T"]), f["feature"] in texture) for f in model["faces"]])
            wall = walls(shape, P, T, skip=tex_tri)
        except Exception as e:
            wall = {"error": f"{type(e).__name__}: {e}"[:160]}
    try:
        form = form_views(model, P, T, product_class)
    except Exception as e:
        form = {"error": f"{type(e).__name__}: {e}"[:160]}
    return {
        "folds": folds, "walls": wall, "form": form, "product_class": product_class,
        "smallest_fillet_mm": round(min(radii), 3) if radii else None,
        "fillet_faces": len(radii),
        "fillet_radii": sorted({round(r, 1) for r in radii})[:24],
        "radius_tiers": radius_tiers(radii),
        "sharp_edge_fraction": None if sharp is None else round(sharp, 3),
        "tangent_edge_fraction": None if tangent is None else round(tangent, 3),
        "texture_features_excluded": texture,
        "edges_sampled": len(edges),
        "symmetry": symmetry(P, T, lo, hi),
        "proportions": {"bbox_mm": [round(b - a, 2) for a, b in zip(lo, hi)], "ratios": ratios},
        "surface_mix": {k: round(v / total, 3) for k, v in kinds.items() if v} if not mesh_design else None,
        "sliver_faces": slivers,
        "features": {k: {"area": round(v["area"], 2), "faces": v["faces"], "lo": v["lo"], "hi": v["hi"]} for k, v in feats.items()},
        "volume_mm3": round(model["volume"], 2),
        "solids": len(shape.solids()),
        "craft_notes": model.get("craft_notes", []),
        "unchanged_stages": model.get("unchanged_stages", []),
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


def op_texture_patch(key, recipe_id, values, center, half, tol=0.05, budget=700_000):
    """The design's mesh textures applied at full resolution to a small patch of its surface (the triangles within
    a box of half-size 1.15 x half round center): the whole part at view resolution is too coarse to carry a weave,
    a patch is not. Returns {"mesh": [{feature, positions, indices}], "edges": None}."""
    from . import kernel
    from .craft import meshtex
    model = kernel._get_near(key, recipe_id, values, tol)
    specs = meshtex.declared(model["recipe"], model["values"])
    c, h = np.asarray(center, float), float(half) * 1.15
    P, T, tags, off = [], [], [], 0
    for f in kernel._fine_faces(model):                          # export resolution: the patch is small
        tri = f["P"][f["T"]]
        sel = np.all(np.abs(tri - c) <= h, axis=(1, 2))           # whole triangles inside the box: a tight frame
        if not sel.any():
            continue
        P.append(f["P"])
        T.append(f["T"][sel] + off)
        tags += [f["feature"]] * int(sel.sum())
        off += len(f["P"])
    if not T:
        raise ValueError("No surface near the texture patch.")
    V, F, tg, _info = meshtex.apply(np.concatenate(P), np.concatenate(T), tags, specs, budget) if specs else \
        (np.concatenate(P), np.concatenate(T), np.asarray(tags), {})
    mesh = []
    for feat in dict.fromkeys(np.asarray(tg).tolist()):
        sel = F[np.asarray(tg) == feat]
        used, inv = np.unique(sel, return_inverse=True)
        mesh.append({"feature": feat, "positions": kernel._b64(V[used].astype(np.float32)),
                     "indices": kernel._b64(inv.reshape(-1, 3).astype(np.uint32))})
    return {"mesh": mesh, "edges": None}


KERNEL_OPS = {"critique_metrics": op_critique_metrics, "section_view": op_section_view,
              "texture_patch": op_texture_patch}


# ---- engine side ---------------------------------------------------------------------------------------------------

def _renders_dir(st, p) -> Path:
    d = st.dir(p["id"]) / "artifacts" / "renders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def texture_tile_box(st, p, v, half: float = 18.0, camera=(-30.0, 20.0)):
    """Where to zoom so a mesh texture reads: the point of a textured feature that faces the camera most squarely,
    and a box `half` mm round it. (centre, half, camera) or None."""
    from . import render as rendering
    from .craft import meshtex
    try:
        r = st.recipe(p)
        specs = meshtex.declared(r, r.validate(st.rev(p)["values"]))
    except Exception:
        return None
    if not specs:
        return None
    want = set()
    for s in specs:
        want |= set(s.features if hasattr(s, "features") else s.get("features", ()))
    _r, _u, fwd = rendering._camera_ae(*camera)
    best = None
    for m in v["mesh"]:
        if want and m["feature"] not in want:
            continue
        P = rendering._arr(m["positions"], np.float32, 3).astype(np.float64)
        T = rendering._arr(m["indices"], np.uint32, 3)
        if not len(T):
            continue
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        n = np.cross(b - a, c - a)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        facing = -(n @ fwd)                                   # 1 = faces the camera
        toward = -((a + b + c) / 3 @ fwd)                     # nearer the camera
        score = facing + 0.002 * toward
        i = int(np.argmax(score))
        if best is None or score[i] > best[0]:
            best = (score[i], (a[i] + b[i] + c[i]) / 3)
    if best is None:
        return None
    return best[1], np.array([half, half, half]), camera


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
    v = st.view(p, timeout=300)             # a heavy design is still building in the pipeline: wait for it
    title = f"{p['name']} - r{p['head']:02d}"
    views = ["iso", "iso_back", "front", "right", "top", "bottom"]
    exploded = None
    if (v.get("assembly") or {}).get("parts") and not (v.get("assembly") or {}).get("error"):
        try:                                     # a multi-part design: the outside hides the parts, so show them apart
            exploded = rendering.posed(v, "exploded")
            views[-1] = "exploded"
        except ValueError:
            exploded = None
    tile = texture_tile_box(st, p, v) if v.get("mesh_texture") else None
    if tile is not None:                         # a texture is invisible at sheet scale: show a zoomed tile of it
        views[views.index("bottom") if "bottom" in views else views.index("iso_back")] = "texture"
    if not sheet.exists():
        pngs = []
        for vw in views:
            if vw == "texture":
                c, half, cam = tile
                try:                                             # the texture at full resolution on a patch
                    patch = st._k("texture_patch", key=key, recipe_id=st.rid(p), values=st.rev(p)["values"],
                                  center=[float(x) for x in c], half=float(half[0]), p=p, timeout=300)
                except Exception:
                    patch = v
                pngs.append(rendering.render_png(patch, feats, "iso", None, size=(560, 420), camera=cam,
                                                 frame_box=(c - half, c + half),
                                                 title=f"{title}: texture close-up, {2 * float(half[0]):.0f} mm across"))
            else:
                pngs.append(rendering.render_png(exploded if vw == "exploded" else v, feats,
                                                 "iso" if vw == "exploded" else vw, None, size=(560, 420),
                                                 title=title + (" (exploded)" if vw == "exploded" else "")))
        sheet.write_bytes(rendering.contact_sheet(pngs, cols=3))
    out = {"sheet": sheet, "section": None, "section_error": "",
           "caption": f"{title}: six views ({', '.join(x.replace('_', ' ') for x in views)}), bounding box "
                      + " x ".join(f"{b - a:.1f}" for a, b in zip(*v["bbox"])) + " mm"
                      + (f"; {v['mesh_texture']['label']}" if v.get("mesh_texture") else "") + "."}
    sec = d / f"{key}-section-y-v{rendering.VERSION}.{VERSION}.png"
    if not sec.exists():
        try:
            sv = st._k("section_view", key=key, recipe_id=st.rid(p), values=st.rev(p)["values"], axis="y", p=p, timeout=300)
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


def _missing_why(m: dict) -> str:
    miss, same = m.get("planned_missing") or [], m.get("unchanged_stages") or []
    if not miss and not same:
        return "All planned features have faces."
    out = []
    if miss:
        out.append("Planned but no faces in the solid: " + ", ".join(miss))
    if same:
        out.append("Stages that left the solid unchanged (a fillet that did not fit, a cut that missed): " + ", ".join(same))
    return "; ".join(out) + "."


def checklist(metrics: dict, plan: dict | None, purpose: str, reads_as: str = "") -> list[dict]:
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
             f"{(sharp or 0) * 100:.0f} % of edge length is a sharp crease"
             + (f" (texture features {', '.join(m['texture_features_excluded'])} left out)" if m.get("texture_features_excluded") else "")
             + "; smallest fillet " + (f"{fil:g} mm" if fil is not None else "none")
             + (f"; {m['tangent_edge_fraction'] * 100:.0f} % of edge length is tangent (smooth spline or loft transitions "
                "count as rounded even without fillet faces)" if m.get("tangent_edge_fraction") else "") + "."),
        item("Is every planned feature visible in the close-ups, where the plan put it?",
             bool(m.get("planned_missing") or m.get("unchanged_stages")), _missing_why(m)),
        item("Did every form.craft helper build what was asked?", bool(m.get("craft_notes")),
             ("Fallbacks taken: " + "; ".join(m["craft_notes"])) if m.get("craft_notes") else "No fallbacks."),
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
    fo = m.get("folds") or {}
    if fo and "folds" in fo:
        items.append(item("Is every lofted skin smooth (no folds, no creases inside a face)?", fo["folds"] > 0,
                          f"{fo['faces_checked']} free-form faces sampled; {fo['folds']} neighbouring normals turn more "
                          f"than 135 deg (worst {fo['worst_deg']} deg)" + (f" near {fo['where'][:3]}" if fo.get("where") else "")
                          + ". A fold is sections crossing or a guide curve overshooting: ease it or add sections."))
    wl = m.get("walls") or {}
    if wl.get("samples"):
        thin = wl["thin_fraction"] > 0.01 or wl["p2_mm"] < 0.35 * wl["median_mm"]
        items.append(item("Are the walls whole and even (no break-through, no paper-thin spots)?", thin,
                          f"Ray thickness over {wl['samples']} points: min {wl['min_mm']}, 2 % {wl['p2_mm']}, median "
                          f"{wl['median_mm']} mm; {wl['thin_fraction'] * 100:.1f} % under 35 % of the median"
                          + (f" at {wl['thin_at'][:3]}" if wl.get("thin_at") else "") + ". Thin spots on a shell are the "
                          "inner surface crossing the outer (break-through): inset less there or ease the form."))
    fm = m.get("form") or {}
    cl = fm.get("class")
    if cl:
        bad_sig = [s["id"] for s in cl["signature"] if not s["ok"]]
        bad_rat = [f"{r['ratio']} {r['value']} (range {r['range'][0]}-{r['range'][1]})" for r in cl["ratios"] if not r["ok"]]
        items.append(item(f"Silhouette: does it have the outline of a {cl['label']} in the side, front and top views?",
                          cl["score"] < 0.8,
                          f"Class score {cl['score']:.2f} (outline {cl['parts']['outline']:.2f}, proportions "
                          f"{cl['parts']['ratios']:.2f}, signature {cl['parts']['signature']:.2f}); outline deviation "
                          + ", ".join(f"{k} {v['profile_dev'] * 100:.1f} %" for k, v in cl["views"].items())
                          + " of the size from the class outline"
                          + (f"; proportions off: {'; '.join(bad_rat)}" if bad_rat else "")
                          + (f"; missing: {', '.join(bad_sig)}" if bad_sig else "") + f". Ranges: {cl['ratios_source']}."))
        items.append(item(f"Reads as a {cl['label']}: look at the six views and the photo. Would a buyer recognise it at a "
                          "glance? Name the three things that make it read as one and the one that most gives it away "
                          "as a model. Answer with critique(..., reads_as=...).", not reads_as,
                          f"Your answer: {reads_as}" if reads_as else "Not answered yet: this question has no computed "
                          "answer; only looking does."))
    kk = {k: v for k, v in (fm.get("kinks") or {}).items() if v}
    if kk:
        items.append(item("Are the silhouette's sharp turns intended (a crease line), not a loft kink?", False,
                          "; ".join(f"{vn}: " + ", ".join(f"{e} at {u:.2f} turns {a:g} deg" for e, u, a in v[:3])
                                    for vn, v in kk.items())))
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


# ---- the aesthetic rubric ------------------------------------------------------------------------------------------
#
# Eight items an industrial designer would judge, scored 0-5 by the agent after looking at render_photo from three
# angles. The geometry cannot score beauty, but it can refuse a score the solid does not support: a design with no
# blend radii cannot have a radius hierarchy of 5, one material cannot score 5 on material. Each item's final score
# is min(agent's score, cap). The gate: every item scored, mean >= 4, none under 3.

AESTHETIC = (
    ("silhouette", "Silhouette", "Is the outline distinctive and intentional in three views (not a box, a puck, an egg or "
                                 "a slab)?"),
    ("proportion", "Proportion", "Do the main masses relate on a proportion system (1:1, 1:1.414, golden, 1:2), with no "
                                 "almost-equal ratios?"),
    ("continuity", "Continuity", "Do surfaces flow (G1 at least, G2 on the main form) with breaks only where intended?"),
    ("radius_hierarchy", "Radius hierarchy", "Three tiers of radii (form, secondary, detail), each about a third of the "
                                             "one above, and no raw edge where a hand goes?"),
    ("break_up", "Break-up", "Is there a considered surface break: a shadow gap, a split line, an inset panel, a stepped "
                             "tier, a material change?"),
    ("detail_rhythm", "Detail rhythm", "Are repeated details on one pitch, aligned to the form, concentrated where the "
                                       "hand works?"),
    ("material", "Material and colour", "Two or three materials by function (calm body, soft contact, one precise "
                                        "accent) in a pairing that belongs together?"),
    ("would_sell", "Would sell", "Next to a real premium product on a shelf, would a buyer pick this one up?"),
)
AESTHETIC_GATE = {"mean": 4.0, "min": 3}


def _aesthetic_caps(metrics: dict, zones: list) -> dict:
    """{item: (cap or None, why)} from what the geometry and the appearance zones can support."""
    m = metrics or {}
    mix = m.get("surface_mix") or {}
    sharp, tangent = m.get("sharp_edge_fraction"), m.get("tangent_edge_fraction") or 0.0
    tiers = m.get("radius_tiers")
    if tiers is None:
        tiers = radius_tiers(m.get("fillet_radii") or ([m["smallest_fillet_mm"]] if m.get("smallest_fillet_mm") else []))
    rounded_by_form = sharp is not None and sharp < 0.15
    primitive = mix.get("plane", 0) > 0.85 and not m.get("fillet_faces") and tangent < 0.2
    caps = {}
    cl = ((m.get("form") or {}).get("class")) or {}
    if primitive:
        caps["silhouette"] = (1, "Mostly flat faces and no rounds: the views read as a primitive.")
    elif cl and cl.get("score", 1) < 0.6:
        caps["silhouette"] = (3, f"Class outline score {cl['score']:.2f} (under 0.6).")
    else:
        caps["silhouette"] = (None, "")
    off = [r for r in (m.get("proportions") or {}).get("ratios", []) if r.get("off_pct", 0) > 12]
    caps["proportion"] = (4, "Bounding ratios are not near a classic ratio: " + ", ".join(
        f"{r['pair']} {r['ratio']}" for r in off) + ".") if off else (None, "")
    if sharp is None:
        caps["continuity"] = (None, "")
    elif sharp > 0.6:
        caps["continuity"] = (2, f"{sharp * 100:.0f} % of edge length is a sharp crease.")
    elif sharp > 0.4:
        caps["continuity"] = (3, f"{sharp * 100:.0f} % of edge length is a sharp crease.")
    elif sharp > 0.25:
        caps["continuity"] = (4, f"{sharp * 100:.0f} % of edge length is a sharp crease.")
    else:
        caps["continuity"] = (None, "")
    if tiers >= 3:
        caps["radius_hierarchy"] = (None, "")
    elif tiers == 2:
        caps["radius_hierarchy"] = (4, "Two radius tiers among the blends; a third (detail or form) is missing.")
    elif tiers == 1:
        caps["radius_hierarchy"] = (3, "One radius tier: every blend is about the same size.")
    elif rounded_by_form:
        caps["radius_hierarchy"] = (3, "No blend faces, but the edges are soft by construction (sections or "
                                       "profiles): add a tier of real radii where parts meet.")
    else:
        caps["radius_hierarchy"] = (1, "No blend radii and sharp edges: rounding was dropped. Use craft.safe_fillet "
                                       "with smaller radii; never ship without them.")
    looks = {(z.get("finish"), str(z.get("color", "")).lower()) for z in zones or []}
    covered = {f for z in zones or [] for f in z.get("features", [])}
    feats = set((m.get("features") or {}).keys())
    n_mat = len(looks) + (1 if feats - covered else 0)
    if n_mat <= 1:
        caps["material"] = (1 if not zones else 2, "One material over everything: declare appearance() zones (two or "
                                                   "three, by function).")
    elif n_mat == 2:
        caps["material"] = (4, "Two materials; a third (a soft contact or a precise accent) would complete it.")
    else:
        caps["material"] = (None, "")
    nf = len(feats)
    if nf <= 1 and n_mat <= 1:
        caps["break_up"] = (2, "One feature in one material: no surface break.")
    elif nf <= 2 and n_mat <= 1:
        caps["break_up"] = (3, "Few features and one material.")
    else:
        caps["break_up"] = (None, "")
    caps["detail_rhythm"] = (None, "")
    return caps


# ---- the game critic: caps from the built game asset ---------------------------------------------------------------
#
# A game asset is judged on what a game shows: its LOD0 mesh, its baked maps and its materials, not on CAD blend
# faces (a subdivision cage has none) or appearance() zones (a game asset has materials() instead). game_evidence()
# measures the asset Blender built (form/game, <data>/.cache/game/<key>/); _game_caps() turns that into caps. Every
# number is computed; every threshold is a proposal (heuristic), stated with the cap it sets.

GAME_HARD_DEG = 50.0          # an edge of LOD0 sharper than this is a hard edge: bevelled in the mesh or baked, or raw
GAME_FEATURE_DEG = 25.0       # an edge sharper than this turns the form (a bevel's own edges count here)
GAME_BAKED_DEG = 12.0         # a hard edge is baked when the normal map leans at least this much just inside it
GAME_VIEWS = {"front": (0.0, 0.0), "side": (90.0, 0.0), "top": (0.0, 90.0), "three_quarter": (35.0, 25.0)}
WEAR_BAND = (0.02, 0.12)      # worn share of the surface that reads as use: under it no wear shows, over it damage
                              # (the same band as form/refine/analyze.WEAR_BAND)


def _score(raw):
    try:
        return None if raw is None else max(0.0, min(5.0, float(raw)))
    except (TypeError, ValueError):
        return None


def _passes(scores) -> list[dict]:
    """The scoring passes: one dict of item scores, {"passes": [dict, ...]} or a list of dicts."""
    if isinstance(scores, dict) and isinstance(scores.get("passes"), list):
        scores = scores["passes"]
    if isinstance(scores, list):
        return [{str(k): v for k, v in p.items()} for p in scores if isinstance(p, dict)]
    return [{str(k): v for k, v in (scores or {}).items()}]


def _game_files(d: Path) -> dict:
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    tex = d / "textures"
    a = rep.get("asset", "")
    return {"report": rep, **{k: tex / f"{a}_{k}.png" for k in ("base_color", "normal", "curvature")}}


def _image(path: Path):
    if not path.is_file():
        return None
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0


def _lookup(img, uv):
    h, w = img.shape[:2]
    x = np.clip((uv[:, 0] * w).astype(int), 0, w - 1)
    y = np.clip(((1 - uv[:, 1]) * h).astype(int), 0, h - 1)
    return img[y, x]


def _area_samples(P, T, n, seed=0):
    """(barycentric (n, 3), triangle index (n,)) spread over the mesh by 3D area."""
    e1, e2 = P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]
    area = np.linalg.norm(np.cross(e1, e2), axis=1) / 2
    rng = np.random.default_rng(seed)
    k = rng.choice(len(T), size=n, p=area / area.sum())
    a, b = rng.random(n), rng.random(n)
    flip = a + b > 1
    a[flip], b[flip] = 1 - a[flip], 1 - b[flip]
    return np.c_[1 - a - b, a, b], k


def _rotation(az: float, el: float) -> np.ndarray:
    """World (Z up) to a view frame whose x is screen right, y screen up: looking from azimuth az (0 = from -Y, the
    front), elevation el (degrees)."""
    a, e = math.radians(az), math.radians(el)
    right = np.array([math.cos(a), math.sin(a), 0.0])
    fwd = np.array([-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), -math.sin(e)])   # into the screen
    up = np.cross(right, fwd)
    return np.array([right, up])


def silhouettes(P, T, px: int = 256, views=None) -> dict:
    """{view: boolean mask (px, px)} of a mesh seen orthographically from each view, all at one scale."""
    from PIL import Image, ImageDraw
    views = views or GAME_VIEWS
    P = np.asarray(P, float)
    c = (P.max(0) + P.min(0)) / 2
    r = float(np.linalg.norm(P - c, axis=1).max()) or 1.0
    out = {}
    for name, (az, el) in views.items():
        q = (P - c) @ _rotation(az, el).T
        s = (q / (2.1 * r) + 0.5) * px
        img = Image.new("L", (px, px), 0)
        dr = ImageDraw.Draw(img)
        for t in np.asarray(T):
            dr.polygon([(s[i, 0], px - s[i, 1]) for i in t], fill=255)
        out[name] = np.asarray(img) > 127
    return out


def solidity(mask) -> float:
    """Mask area over its convex hull's area (1 for a convex outline; holes and notches lower it)."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 4:
        return 1.0
    from scipy.spatial import ConvexHull
    pts = np.c_[np.r_[xs, xs + 1, xs, xs + 1], np.r_[ys, ys, ys + 1, ys + 1]]
    try:
        hull = ConvexHull(pts)
    except Exception:                                    # noqa: BLE001 - a degenerate (flat) outline
        return 1.0
    return float(min(1.0, len(xs) / hull.volume))


def _weld(P, T, tol=1e-3):
    key = np.round(np.asarray(P) / tol).astype(np.int64)
    _u, inv = np.unique(key, axis=0, return_inverse=True)
    return inv.reshape(-1)[T]


def _point_to_mesh(Q, P, T, k=8):
    """Distance from each point of Q to a triangle mesh: exact to the triangles that own the k surface samples
    nearest each point (dense samples by area, so a large triangle is found however far its centroid is)."""
    from scipy.spatial import cKDTree
    A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    bary, own = _area_samples(P, T, 120_000, seed=7)
    S = (P[T[own]] * bary[:, :, None]).sum(1)
    S, own = np.r_[S, (A + B + C) / 3], np.r_[own, np.arange(len(T))]
    _d, nn = cKDTree(S).query(Q, k=k)
    idx = own[nn.reshape(len(Q), k)]
    best = np.full(len(Q), np.inf)
    for j in range(k):
        a, b, c = A[idx[:, j]], B[idx[:, j]], C[idx[:, j]]
        best = np.minimum(best, np.linalg.norm(Q - _closest_on_tri(Q, a, b, c), axis=1))
    return best


def _closest_on_tri(p, a, b, c):
    """Closest points on triangles (a, b, c) to points p, vectorised (Ericson, Real-Time Collision Detection)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) < 1e-30, 1e-30, va + vb + vc)
    v, w = vb / den, vc / den
    out = a + ab * v[:, None] + ac * w[:, None]
    m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
    t = np.clip((d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1e-30, (d4 - d3) + (d5 - d6)), 0, 1)
    out[m] = (b + (c - b) * t[:, None])[m]
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = np.clip(d2 / np.where(d2 - d6 == 0, 1e-30, d2 - d6), 0, 1)
    out[m] = (a + ac * t[:, None])[m]
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = np.clip(d1 / np.where(d1 - d3 == 0, 1e-30, d1 - d3), 0, 1)
    out[m] = (a + ab * t[:, None])[m]
    out[(d3 >= 0) & (d4 <= d3)] = b[(d3 >= 0) & (d4 <= d3)]
    out[(d6 >= 0) & (d5 <= d6)] = c[(d6 >= 0) & (d5 <= d6)]
    out[(d1 <= 0) & (d2 <= 0)] = a[(d1 <= 0) & (d2 <= 0)]
    return out


def edge_treatment(P, UV, T, normal_map=None, px: int = 1024) -> dict:
    """Bevel coverage of a LOD0 mesh: of its feature edges (> GAME_FEATURE_DEG), the length share that is not a raw
    hard edge. A hard edge (> GAME_HARD_DEG) counts as treated when the baked normal map leans by GAME_BAKED_DEG or
    more just inside it on both sides (a bevel baked from the high poly); edges a bevel split into gentler ones count
    as treated by the mesh itself. 1.0 when the mesh has no feature edges at all."""
    P, UV, T = np.asarray(P, float), np.asarray(UV, float), np.asarray(T, np.int64)
    W = _weld(P, T)
    n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    n = n / np.where(ln > 1e-12, ln, 1.0)[:, None]
    edges: dict = {}
    for ti in np.nonzero(ok)[0]:
        for k in range(3):
            a, b = int(W[ti, k]), int(W[ti, (k + 1) % 3])
            edges.setdefault((min(a, b), max(a, b)), []).append((int(ti), k))
    feat = hard = baked = 0.0
    lean_vals = []
    for (_a, _b), fs in edges.items():
        if len(fs) != 2:
            continue
        (t0, k0), (t1, _k1) = fs
        ang = math.degrees(math.acos(float(np.clip(np.dot(n[t0], n[t1]), -1, 1))))
        if ang < GAME_FEATURE_DEG:
            continue
        L = float(np.linalg.norm(P[T[t0, k0]] - P[T[t0, (k0 + 1) % 3]]))
        feat += L
        if ang < GAME_HARD_DEG:
            continue
        hard += L
        if normal_map is None:
            continue
        leans = []
        for ti, k in fs:
            u0, u1, u2 = UV[T[ti, k]], UV[T[ti, (k + 1) % 3]], UV[T[ti, (k + 2) % 3]]
            mid = (u0 + u1) / 2
            span = float(np.linalg.norm((u2 - mid) * px))
            s = min(0.25, 2.5 / span) if span > 1e-9 else 0.0
            nm = _lookup(normal_map, (mid + (u2 - mid) * s)[None, :])[0] * 2 - 1
            leans.append(math.degrees(math.acos(float(np.clip(nm[2] / (np.linalg.norm(nm) or 1), -1, 1)))))
        lean_vals.append(min(leans))
        if min(leans) >= GAME_BAKED_DEG:
            baked += L
    raw = hard - baked
    return {"coverage": round(1.0 - raw / feat, 3) if feat > 0 else 1.0, "feature_edges_mm": round(feat, 1),
            "hard_edges_mm": round(hard, 1), "hard_baked_mm": round(baked, 1),
            "raw_share": round(raw / feat, 3) if feat > 0 else 0.0,
            "median_lean_deg": round(float(np.median(lean_vals)), 1) if lean_vals else None}


def game_evidence(asset_dir) -> dict:
    """What a built game asset shows, measured from its folder (report.json, lods/*.npz, textures/*.png):

      edges            edge_treatment() of LOD0 with its baked normal map: bevel coverage
      materials        distinct materials (kind and tint) the asset declares, and their tints
      value_contrast   luminance spread of the base colour over LOD0's surface (95th minus 5th percentile, 0..1)
      scales           primary (LOD3 alone shows more than one mass: several parts or a concave outline), secondary
                       (forms smaller than the masses: LOD0 has feature edges, bevels, panels, trims, of at least 3
                       diagonals in all, or 3 or more parts), tertiary (the normal map carries surface detail: blue std >=
                       0.006 or red/green std >= 0.03)
      silhouette       solidity (area over convex hull) of LOD0 in four views; complexity = 1 - their mean; and the
                       read at a glance (form/refine/analyze.py): convexity_64, the convexity deficit of the outline
                       at 64 px in six views, and interior_regions, value regions of >= 12 px in a 64 px lit render
      wear             worn_share: the share of LOD0's surface the baked wear mask covers (measured in the bake,
                       report bake.wear), with worn_on_convex and convex_of_worn; present when it is >= 2 %, in_band
                       when it is 2-12 %. An older bake without the mask falls back to a worn material and a lit
                       curvature mask (worn_share None)
    All computed (no judgement); the thresholds are proposals."""
    d = Path(asset_dir)
    f = _game_files(d)
    rep = f["report"]
    z0 = np.load(d / "lods" / "lod0.npz")
    lods = sorted((d / "lods").glob("lod*.npz"))
    zl = np.load(lods[-1])
    P, UV, T = z0["P"].astype(float), z0["UV"].astype(float), z0["T"].astype(np.int64)
    px = int(rep.get("texture_px") or 1024)
    diag = float(np.linalg.norm(P.max(0) - P.min(0))) or 1.0
    nmap, base, curv = (_image(f[k]) for k in ("normal", "base_color", "curvature"))
    edges = edge_treatment(P, UV, T, nmap, px)
    mats = rep.get("materials") or []
    used = [m for m in mats if not (m.get("name") == "default" and str(m.get("hex", "")).lower() == "#b8b2a7"
                                    and len(mats) > 1)]
    kinds = sorted({(m.get("kind"), str(m.get("hex", "")).lower()) for m in used})
    bary, k = _area_samples(P, T, 40_000, seed=3)
    uv = (UV[T[k]] * bary[:, :, None]).sum(1)
    contrast = None
    if base is not None:
        lum = _lookup(base, uv) @ np.array([0.2126, 0.7152, 0.0722])
        contrast = round(float(np.percentile(lum, 95) - np.percentile(lum, 5)), 3)
    # detail scales
    Pl, Tl = zl["P"].astype(float), zl["T"].astype(np.int64)
    comps = _components(_weld(Pl, Tl), len(Pl))
    sil3 = silhouettes(Pl, Tl, 160)
    sol3 = min(solidity(m) for m in sil3.values())
    primary = comps >= 2 or sol3 < 0.93
    q = (P[T[k[:6000]]] * bary[:6000, :, None]).sum(1)
    far = float((_point_to_mesh(q, Pl, Tl) > 0.004 * diag).mean())
    comps0 = _components(_weld(P, T), len(P))
    secondary = edges["feature_edges_mm"] >= 3 * diag or comps0 >= 3
    nd = ((rep.get("bake") or {}).get("normal_detail")) or {}
    tertiary = (nd.get("blue_std") or 0) >= 0.006 or (nd.get("rg_std") or 0) >= 0.03
    sil = silhouettes(P, T, 256)
    sols = {v: round(solidity(m), 4) for v, m in sil.items()}
    wear_max = max([float(m.get("wear") or 0) for m in used] or [0.0])
    edge_lit = round(float((_lookup(curv, uv)[:, 0] > 0.5).mean()), 4) if curv is not None else 0.0
    wear = {"max_wear": wear_max, "edge_mask_share": edge_lit}
    wm = ((rep.get("bake") or {}).get("wear")) or {}
    if wm.get("worn_share") is not None:          # measured on the baked wear mask (runner 4 and later)
        s = float(wm["worn_share"])
        lo, hi = WEAR_BAND
        wear.update(worn_share=s, worn_on_convex=wm.get("worn_on_convex"), convex_of_worn=wm.get("convex_of_worn"),
                    present=bool(s >= lo), in_band=bool(lo <= s <= hi), measured="baked wear mask over LOD0")
    else:                                          # an older bake: no wear mask, only the material and edge mask
        wear.update(worn_share=None, present=bool(wear_max >= 0.15 and edge_lit >= 0.005), in_band=None,
                    measured="not measured (an older bake has no wear mask): a worn material and a lit edge mask")
    from .refine import analyze as ra
    s64 = ra.silhouette(P, T)
    s64.pop("masks", None)
    read = ra.interior_read(P, T)
    lit = None
    if base is not None:                           # the same render with the baked base colour: what the eye reads
        w = np.array([0.2126, 0.7152, 0.0722])
        lit = ra.interior_read(P, T, albedo=lambda kk, bb: _lookup(base, (UV[T[kk]] * bb[:, :, None]).sum(1)) @ w)
    return {"asset": rep.get("asset"), "dir": str(d), "diagonal_mm": round(diag, 2),
            "lod0_triangles": int(len(T)), "edges": edges,
            "materials": {"count": len(kinds), "list": [f"{a} {b}" for a, b in kinds]},
            "value_contrast": contrast,
            "scales": {"primary": bool(primary), "secondary": bool(secondary), "tertiary": bool(tertiary),
                       "count": int(primary) + int(secondary) + int(tertiary), "lod3_parts": comps,
                       "lod0_parts": comps0, "feature_edge_diagonals": round(edges["feature_edges_mm"] / diag, 2),
                       "lod3_min_solidity": round(sol3, 4), "lod0_far_from_lod3": round(far, 4),
                       "normal_blue_std": nd.get("blue_std"), "normal_rg_std": nd.get("rg_std")},
            "silhouette": {"solidity": sols, "complexity": round(1 - float(np.mean(list(sols.values()))), 4),
                           "convexity_64": s64["convexity_deficit"], "solidity_64": s64["solidity"],
                           "interior_regions": read["regions"],
                           "interior_regions_lit": None if lit is None else lit["regions"]},
            "wear": wear,
            "evidence": "computed (thresholds proposed)"}


def _components(T, n) -> int:
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for t in np.asarray(T):
        r0 = find(int(t[0]))
        for v in t[1:]:
            r = find(int(v))
            if r != r0:
                parent[max(r, r0)] = min(r, r0)
                r0 = min(r, r0)
    return len({find(int(v)) for v in np.unique(np.asarray(T))})


def find_game_asset(st, p: dict) -> Path | None:
    """The newest game asset built from this design's cage (its report's source hash is the merged cage's)."""
    try:
        from .game import pipeline
        cages = pipeline.cages_in_source(st.source_text(p) or "")
        if not cages:
            return None
        h = pipeline.merge_cages(cages).hash()
    except Exception:                                    # noqa: BLE001 - no cage, no asset to find
        return None
    best = None
    for r in (Path(st.root) / ".cache" / "game").glob("*/report.json"):
        try:
            if json.loads(r.read_text(encoding="utf-8")).get("source", {}).get("hash") == h:
                if best is None or r.stat().st_mtime > best.stat().st_mtime:
                    best = r
        except (OSError, ValueError):
            continue
    return best.parent if best else None


def _game_caps(metrics: dict, ev: dict | None) -> dict:
    """{item: (cap or None, why)} for a game asset, from game_evidence(). Proportion keeps the solid's bounding-ratio
    cap; continuity, radius hierarchy (edge treatment), break-up, detail rhythm, material and silhouette read the
    asset. Without a built asset, the items it would decide are held at 2."""
    caps = {k: (None, "") for k, _, _ in AESTHETIC}
    off = [r for r in (metrics or {}).get("proportions", {}).get("ratios", []) if r.get("off_pct", 0) > 12]
    if off:
        caps["proportion"] = (4, "Bounding ratios are not near a classic ratio: " + ", ".join(
            f"{r['pair']} {r['ratio']}" for r in off) + ".")
    if not ev:
        why = "No game asset built yet: build it (game_asset), then critique reads its LOD0 and baked maps."
        for k in ("radius_hierarchy", "break_up", "detail_rhythm", "material"):
            caps[k] = (2, why)
        return caps
    e = ev["edges"]
    cov = e["coverage"]
    lvl = next((c for t, c in ((0.75, None), (0.5, 4), (0.3, 3), (0.15, 2)) if cov >= t), 1)
    caps["radius_hierarchy"] = (lvl, "" if lvl is None else
                                f"Bevel coverage {cov:.0%}: {e['hard_edges_mm'] - e['hard_baked_mm']:.0f} mm of raw hard "
                                f"edge in LOD0 of {e['feature_edges_mm']:.0f} mm of feature edge (bevel it, or bevel it "
                                "high_only so the bake rounds it).")
    if e["raw_share"] > 0.7:
        caps["continuity"] = (3, f"{e['raw_share']:.0%} of the feature edge length is a raw hard edge.")
    sc = ev["scales"]
    names = [n for n in ("primary", "secondary", "tertiary") if sc[n]]
    miss = [n for n in ("primary", "secondary", "tertiary") if not sc[n]]
    if sc["count"] <= 1:
        caps["detail_rhythm"] = (2, f"One detail scale or none ({', '.join(names) or 'none'}): missing "
                                    f"{', '.join(miss)}.")
    elif sc["count"] == 2:
        caps["detail_rhythm"] = (4, f"Two detail scales; {miss[0]} is missing.")
    if not sc["secondary"]:
        caps["break_up"] = (3, "No secondary forms: LOD0 has no panel, bevel, trim or part that LOD3 drops.")
    n = ev["materials"]["count"]
    vc = ev.get("value_contrast")
    mcap, mwhy = None, []
    if n <= 1:
        mcap, mwhy = 1, ["one material over everything"]
    elif n == 2:
        mcap, mwhy = 4, ["two materials"]
    if vc is not None and vc < 0.08:
        mcap, mwhy = min(mcap or 5, 2), mwhy + [f"value contrast {vc:.2f} (under 0.08: it reads as one flat tone)"]
    elif vc is not None and vc < 0.15:
        mcap, mwhy = min(mcap or 5, 3), mwhy + [f"value contrast {vc:.2f} (under 0.15)"]
    w = ev["wear"]
    ws = w.get("worn_share")
    if ws is not None and ws > WEAR_BAND[1]:
        mcap, mwhy = min(mcap or 5, 4), mwhy + [f"wear covers {ws:.1%} of the surface (over {WEAR_BAND[1]:.0%}: it "
                                                 "reads as damage, not use)"]
    elif not w.get("present"):
        mcap, mwhy = min(mcap or 5, 4), mwhy + ["no edge wear" + (f" ({ws:.1%} of the surface worn, under "
                                                                   f"{WEAR_BAND[0]:.0%})" if ws is not None else "")]
    caps["material"] = (mcap, ("; ".join(mwhy).capitalize() + ".") if mcap is not None else "")
    caps["silhouette"] = _silhouette_cap(ev["silhouette"], sc["count"])
    return caps


def _silhouette_cap(s: dict, scales: int) -> tuple:
    """The silhouette cap. With the 64 px read (convexity_64, interior_regions from form/refine/analyze.py): an
    outline whose convexity deficit at 64 px is under SIL_BLOB reads as a blob at game distance: cap 2 with one
    detail scale or none, 3 when the lit render shows fewer than READ_REGIONS value regions inside it, else 4; an
    outline over SIL_SHRED is shredded: cap 4. Without it (older evidence), the four-view complexity: under 0.005
    cap 2 with no detail, else 4."""
    from .refine import analyze as ra
    cx64, reg = s.get("convexity_64"), s.get("interior_regions")
    if cx64 is not None:
        if cx64 < ra.SIL_BLOB:
            head = f"The outline at 64 px is nearly convex (convexity deficit {cx64:.3f}, under {ra.SIL_BLOB:g})"
            if scales <= 1:
                return 2, head + " and there is no detail: a blob."
            if reg is not None and reg < ra.READ_REGIONS:
                return 3, head + f" and only {reg} value region(s) read inside it (of {ra.READ_REGIONS})."
            return 4, head + f"; {reg} value regions inside it carry the read."
        if cx64 > ra.SIL_SHRED:
            return 4, f"The outline at 64 px is shredded (convexity deficit {cx64:.3f}, over {ra.SIL_SHRED:g})."
        return None, ""
    cx = s["complexity"]
    if cx < 0.005 and scales <= 1:
        return 2, f"A convex outline in every view (complexity {cx:.3f}) and no detail: a blob."
    if cx < 0.005:
        return 4, f"A convex outline in every view (complexity {cx:.3f})."
    return None, ""


def aesthetic_rubric(metrics: dict, zones: list | None = None, scores=None, purpose: str | None = None,
                     game: dict | None = None) -> dict:
    """The rubric for this design: each item with the agent's score (0-5, from looking at the photos), the cap the
    geometry allows and why, and the final score; the mean, whether it passes the gate, and what to fix first.

    scores: one pass {item: 0-5}, or several blind passes ({"passes": [...]} or a list of dicts): each item then
    takes the median of the passes that scored it, and the passes are kept with it.
    purpose "game": the caps come from the built game asset (game: game_evidence()), not from CAD blend faces and
    appearance() zones. Print and model designs are judged exactly as before."""
    caps = _game_caps(metrics, game) if purpose == "game" else _aesthetic_caps(metrics, zones or [])
    passes = _passes(scores)
    unknown = sorted({k for p in passes for k in p} - {i for i, _, _ in AESTHETIC})
    items = []
    for iid, label, q in AESTHETIC:
        got = [s for s in (_score(p.get(iid)) for p in passes) if s is not None]
        sc = float(np.median(got)) if got else None
        cap, why = caps.get(iid, (None, ""))
        it = {"id": iid, "label": label, "question": q, "score": sc, "cap": cap, "why": why,
              "final": None if sc is None else (min(sc, cap) if cap is not None else sc)}
        if len(passes) > 1:
            it["passes"] = [_score(p.get(iid)) for p in passes]
        items.append(it)
    others = [i["final"] for i in items if i["id"] != "would_sell" and i["final"] is not None]
    ws = items[-1]
    if ws["final"] is not None and others and ws["final"] > min(others) + 1:
        ws["cap"], ws["why"] = min(others) + 1, "Nothing sells better than its weakest item allows."
        ws["final"] = ws["cap"]
    done = [i["final"] for i in items if i["final"] is not None]
    mean = round(sum(done) / len(done), 2) if len(done) == len(items) else None
    missing = [i["id"] for i in items if i["final"] is None]
    passed = bool(mean is not None and mean >= AESTHETIC_GATE["mean"] and min(done) >= AESTHETIC_GATE["min"]
                  and (caps.get("silhouette", (None,))[0] or 5) > 1)
    low = sorted((i for i in items if i["final"] is not None), key=lambda i: i["final"])
    out = {"items": items, "mean": mean, "passed": passed,
           "gate": f"every item scored, mean >= {AESTHETIC_GATE['mean']:g}, none under {AESTHETIC_GATE['min']}, no "
                   "primitive view",
           "scored_by": ("blind passes from 4-view lit renders and a 64 px silhouette (the median), capped by what "
                         "the built game asset measures" if purpose == "game" else
                         "the agent from render_photo (three angles), capped by what the geometry supports"),
           "evidence": EVIDENCE}
    if len(passes) > 1:
        out["passes"] = len(passes)
    if purpose == "game":
        out["game"] = game
    if missing:
        out["next"] = ("Score every item: render_photo from three angles (three_quarter, front, three_quarter_back), "
                       "look, then critique(project, aesthetic={" + ", ".join(f"{m}: 0-5" for m in missing) + "}).")
    elif not passed:
        out["next"] = ("Fix the lowest first: " + ", ".join(f"{i['label']} {i['final']:g}" + (f" ({i['why']})" if i["why"] else "")
                                                         for i in low[:2]) + ". Then render_photo and critique again.")
    else:
        out["next"] = "Passes the aesthetic gate. Say which item is weakest and why when you present it."
    if unknown:
        out["ignored"] = unknown
    return out


def product_class(p: dict, given: str | None = None) -> str | None:
    """The product class critique compares the design with: given, the plan's product_class, or the class the brief
    (goal, name, requirements) or the project name names (form.product_classes.detect)."""
    from . import product_classes as pc
    if given:
        if given not in pc.CLASSES:
            from .studio import StudioError
            raise StudioError(f"Unknown product class “{given}”.", "Classes: " + ", ".join(pc.CLASSES) + ".")
        return given
    d = p.get("design") or {}
    if (d.get("plan") or {}).get("product_class") in pc.CLASSES:
        return d["plan"]["product_class"]
    b = d.get("brief") or {}
    text = " ".join(str(x) for x in [b.get("goal", ""), b.get("name", ""), " ".join(b.get("requirements") or []),
                                     p.get("name", ""), p.get("brief", "") if isinstance(p.get("brief"), str) else ""])
    return pc.detect(text)


def run(st, pid: str, notes: str = "", reads_as: str = "", product_class_id: str | None = None,
        aesthetic=None, game_dir: str | None = None) -> dict:
    """Compute metrics, render close-ups, build the checklist and record one critique pass for the head revision.
    A game design (purpose "game") is capped by its built game asset: game_dir, else the newest asset built from its
    cage (find_game_asset); aesthetic may then hold several blind passes ({"passes": [...]}), whose median counts.
    reads_as: the agent's answer to "does it read as <class>?" after looking at the views (recorded with the pass).
    aesthetic: the agent's 0-5 scores for the AESTHETIC items after looking at render_photo; the rubric caps them by
    what the geometry and the appearance zones support and reports the gate."""
    from . import purpose as purpose_mod
    from . import staged
    p = st.load(pid)
    key = st.keys(p)["geometry"]
    cls = product_class(p, product_class_id)
    metrics = st._k("critique_metrics", key=key, recipe_id=st.rid(p), values=st.rev(p)["values"], product_class=cls,
                    p=p, timeout=300)
    plan = (p.get("design") or {}).get("plan")
    recipe_feats = {f.id for f in st.recipe(p).features}
    if plan:
        planned = [f["id"] for f in plan.get("features", [])]
        metrics["planned_missing"] = [f for f in planned if f not in metrics.get("features", {})]
        metrics["planned_not_declared"] = [f for f in planned if f not in recipe_feats]
    else:
        metrics["planned_missing"] = []
    v = st.view(p, timeout=300)
    png = _closeups(st, p, v, metrics)
    f = None
    if png:
        f = _renders_dir(st, p) / f"{key}-closeups-v{VERSION}.png"
        f.write_bytes(png)
    purpose = purpose_mod.of(p)
    items = checklist(metrics, plan, purpose, reads_as)
    try:
        from . import appearance
        zones = appearance.declared(st.recipe(p), st.rev(p)["values"])
    except Exception:                                  # a broken appearance() counts as no zones here
        zones = []
    game = None
    if purpose == "game":
        gd = Path(game_dir) if game_dir else find_game_asset(st, p)
        if gd is not None and (gd / "report.json").is_file():
            game = game_evidence(gd)
    rubric = aesthetic_rubric(metrics, zones, aesthetic, purpose=purpose, game=game)
    cl = (metrics.get("form") or {}).get("class") or {}
    summary = {"metrics": {k: metrics[k] for k in ("smallest_fillet_mm", "sharp_edge_fraction", "symmetry", "sliver_faces",
                                                    "planned_missing", "craft_notes") if k in metrics},
               "product_class": cls, "class_score": cl.get("score"), "reads_as": reads_as or None,
               "folds": (metrics.get("folds") or {}).get("folds"),
               "wall_p2_mm": (metrics.get("walls") or {}).get("p2_mm"),
               "attention": [i["question"] for i in items if i["attention"]], "evidence": EVIDENCE,
               "aesthetic": {"mean": rubric["mean"], "passed": rubric["passed"],
                             "scores": {i["id"]: i["final"] for i in rubric["items"]}}}
    rec = staged.record_critique(st, pid, p["head"], summary, notes)
    passes = sum(1 for c in (st.load(pid).get("design") or {}).get("critiques", []) if c.get("aesthetic", {}).get("mean")
                 is not None)
    return {"project": pid, "rev": p["head"], "metrics": metrics, "checklist": items, "aesthetic": rubric,
            "aesthetic_passes": passes, "closeups": str(f) if f else None,
            "recorded": {"rev": rec["rev"], "ts": rec["ts"]}, "evidence": EVIDENCE,
            "next": "Look at the close-ups and the section. Fix what the checklist flags with update_design, then "
                    "critique again; release needs a recorded critique of the revision you release."}
