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


def _near_sharp_edges(P, T, S, radius, deg=50.0):
    """For each point of S: is it within radius of a sharp edge of the mesh (adjacent triangles turn > deg)?"""
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


def aesthetic_rubric(metrics: dict, zones: list | None = None, scores: dict | None = None) -> dict:
    """The rubric for this design: each item with the agent's score (0-5, from looking at the photos), the cap the
    geometry allows and why, and the final score; the mean, whether it passes the gate, and what to fix first."""
    caps = _aesthetic_caps(metrics, zones or [])
    scores = {str(k): v for k, v in (scores or {}).items()}
    unknown = sorted(set(scores) - {i for i, _, _ in AESTHETIC})
    items = []
    for iid, label, q in AESTHETIC:
        raw = scores.get(iid)
        try:
            sc = None if raw is None else max(0.0, min(5.0, float(raw)))
        except (TypeError, ValueError):
            sc = None
        cap, why = caps.get(iid, (None, ""))
        items.append({"id": iid, "label": label, "question": q, "score": sc, "cap": cap, "why": why,
                      "final": None if sc is None else (min(sc, cap) if cap is not None else sc)})
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
           "scored_by": "the agent from render_photo (three angles), capped by what the geometry supports",
           "evidence": EVIDENCE}
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
        aesthetic: dict | None = None) -> dict:
    """Compute metrics, render close-ups, build the checklist and record one critique pass for the head revision.
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
    rubric = aesthetic_rubric(metrics, zones, aesthetic)
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
