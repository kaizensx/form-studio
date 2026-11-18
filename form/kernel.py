"""Geometry kernel operations. Runs inside the worker process only.

Everything that touches OCCT lives here so the server stays responsive and a
kernel crash or runaway boolean can be killed without losing project state.
"""
from __future__ import annotations

import base64
import math
import time
from pathlib import Path

import numpy as np

from .recipes import RecipeError, registry, resolve

KERNEL_ID = None
_cache: dict = {}     # geometry key -> built model (kept small)
ORIENTATIONS = {      # name -> (rot_x, rot_y) applied before dropping to the plate
    "as_modelled": (0, 0), "on_back": (90, 0), "on_front": (-90, 0),
    "on_left": (0, 90), "on_right": (0, -90), "inverted": (180, 0),
}
ORIENT_LABEL = {"as_modelled": "Base down", "on_back": "On its back", "on_front": "On its front",
                "on_left": "On left side", "on_right": "On right side", "inverted": "Upside down"}


def kernel_id() -> str:
    global KERNEL_ID
    if KERNEL_ID is None:
        import build123d
        import OCP
        KERNEL_ID = f"build123d {build123d.__version__} / OCP {getattr(OCP, '__version__', '?')}"
    return KERNEL_ID


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _skin(shape):
    from build123d import Compound
    return Compound(shape.faces())


def _build(recipe_id: str, values: dict, tol: float):
    """Build, attribute every face to a feature, and tessellate."""
    from build123d import CenterOf, Vertex
    recipe = resolve(recipe_id)
    v = recipe.validate(values)
    t0 = time.perf_counter()
    try:
        stages = recipe.build(v)
    except RecipeError:
        raise
    except Exception as e:
        raise RecipeError(f"The kernel could not build this shape ({type(e).__name__})", "",
                          "Step back toward the last value that built, then change one parameter at a time.") from e
    final = stages[-1].shape
    t_build = time.perf_counter() - t0
    solids = final.solids()
    want = getattr(recipe, "solids", 1)
    mesh = getattr(recipe, "mesh", False)          # a sewn triangle mesh: OCCT validity is not meaningful for it
    if (not mesh and not final.is_valid) or len(solids) != want:
        raise RecipeError(
            f"The result is {len(solids)} solid(s) (valid={final.is_valid}); this design declares {want}", stages[-1].feature,
            "A cut has split the body, or parts touch and fused. Separate parts by a gap, or reduce the last change.")

    skins = [_skin(s.shape) for s in stages[:-1]]
    faces, by_feature = [], {}
    # mesh the whole solid once (shared edge discretisation, parallel), then read each face's triangles
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    BRepMesh_IncrementalMesh(final.wrapped, tol, False, 0.25, True)
    for face in final.faces():
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face.wrapped, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        P = np.empty((tri.NbNodes(), 3), dtype=np.float64)
        for i in range(1, tri.NbNodes() + 1):
            q = tri.Node(i).Transformed(trsf)
            P[i - 1] = (q.X(), q.Y(), q.Z())
        T = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.uint32) - 1
        if face.wrapped.Orientation() == TopAbs_REVERSED:
            T = T[:, [0, 2, 1]]
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
        k = int(np.argmax(areas))
        probe = (a[k] + b[k] + c[k]) / 3
        feature = stages[0].feature
        pt = Vertex(*probe)
        for i in range(len(skins) - 1, -1, -1):
            if pt.distance_to(skins[i]) > max(1.5 * tol, 0.01):
                feature = stages[i + 1].feature
                break
        faces.append({"feature": feature, "P": P, "T": T, "face": face, "area": float(areas.sum())})
        by_feature.setdefault(feature, []).append(face)

    bb = final.bounding_box()
    com = final.center(CenterOf.MASS)
    model = {
        "recipe": recipe, "values": v, "shape": final, "faces": faces, "by_feature": by_feature,
        "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]],
        "volume": float(final.volume), "area": float(final.area), "com": (com.X, com.Y, com.Z),
        "t_build": t_build, "t_total": time.perf_counter() - t0, "tol": tol,
    }
    return model


def _get(key: str, recipe_id: str, values: dict, tol: float):
    m = _cache.get((key, tol))
    if m is None:
        m = _build(recipe_id, values, tol)
        if len(_cache) > 12:
            _cache.pop(next(iter(_cache)))
        _cache[(key, tol)] = m
    return m


def _get_near(key: str, recipe_id: str, values: dict, tol: float):
    """The built model for `key` at any tessellation already in the cache, else built at `tol`.

    For questions answered on the B-rep (what face is here, how thick is the wall): the viewer's model is
    tessellated at 0.03 mm, and building the same solid again at another tolerance can take as long as the first
    build (a threaded part takes tens of seconds), so a click would seem to do nothing."""
    for (k, t), m in _cache.items():
        if k == key:
            return m
    return _get(key, recipe_id, values, tol)


def _edges(shape) -> np.ndarray:
    segs = []
    for e in shape.edges():
        n = 2 if e.geom_type.name == "LINE" else max(8, min(48, int(e.length / 1.2)))
        pts = [e.position_at(i / (n - 1)) for i in range(n)]
        for p, q in zip(pts, pts[1:]):
            segs.append((p.X, p.Y, p.Z, q.X, q.Y, q.Z))
    return np.array(segs, dtype=np.float32)


def _mesh_edges(P, T, angle_deg=30.0) -> np.ndarray:
    """Crease and boundary edges of a triangle mesh (drawing every triangle edge of a mesh design is noise)."""
    if not len(T):
        return np.zeros((0, 6), dtype=np.float32)
    q = np.round(P / 1e-4).astype(np.int64)                    # weld coincident vertices
    _, inv = np.unique(q, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    V = inv[T]
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    e = np.concatenate([V[:, [0, 1]], V[:, [1, 2]], V[:, [2, 0]]])
    src = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    tri = np.tile(np.arange(len(T)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, src, tri = key[order], src[order], tri[order]
    start = np.ones(len(key), dtype=bool)
    start[1:] = np.any(key[1:] != key[:-1], axis=1)
    first = np.flatnonzero(start)                           # one entry per distinct edge, in sorted order
    count = np.diff(np.append(first, len(key)))
    shared = count >= 2
    nxt = np.minimum(first + 1, len(key) - 1)
    crease = np.einsum("ij,ij->i", n[tri[first]], n[tri[nxt]]) < np.cos(np.radians(angle_deg))
    keep = first[~shared | crease]                          # boundary edges, and creases between two triangles
    if not len(keep):
        return np.zeros((0, 6), dtype=np.float32)
    s0 = src[keep]
    return np.hstack([P[s0[:, 0]], P[s0[:, 1]]]).astype(np.float32)


def _mesh_arrays(model):
    P = np.concatenate([f["P"] for f in model["faces"]])
    off, T = 0, []
    for f in model["faces"]:
        T.append(f["T"] + off)
        off += len(f["P"])
    return P, np.concatenate(T)


def _signature(model) -> dict:
    """Per-feature fingerprint used to tell which features a change touched."""
    out = {}
    for f in model["faces"]:
        s = out.setdefault(f["feature"], {"area": 0.0, "faces": 0, "lo": [1e9] * 3, "hi": [-1e9] * 3})
        s["area"] += f["area"]
        s["faces"] += 1
        lo, hi = f["P"].min(axis=0), f["P"].max(axis=0)
        s["lo"] = [min(a, float(b)) for a, b in zip(s["lo"], lo)]
        s["hi"] = [max(a, float(b)) for a, b in zip(s["hi"], hi)]
    for s in out.values():
        s["area"] = round(s["area"], 3)
        s["lo"] = [round(x, 3) for x in s["lo"]]
        s["hi"] = [round(x, 3) for x in s["hi"]]
    return out


def _summary(model, extra_mass=None) -> dict:
    r, v = model["recipe"], model["values"]
    statics = None
    try:
        statics = r.statics(v, model["volume"], model["com"], extra_mass) if extra_mass is not None \
            else r.statics(v, model["volume"], model["com"])
    except TypeError:
        statics = r.statics(v, model["volume"], model["com"])
    return {
        "values": v, "bbox": model["bbox"], "volume_mm3": model["volume"], "area_mm2": model["area"],
        "com": model["com"], "derived": r.derived(v), "interface_audit": r.measure(v, model["by_feature"]),
        "statics": statics, "signature": _signature(model), "companions": r.companions(v),
        "faces": len(model["faces"]), "triangles": int(sum(len(f["T"]) for f in model["faces"])),
        "timing": {"build_s": round(model["t_build"], 4), "total_s": round(model["t_total"], 4)},
        "kernel": kernel_id(),
    }


# --- operations -----------------------------------------------------------

def op_view(key, recipe_id, values, tol=0.05, edges=True, dock_mass_g=None):
    """Tessellated, feature-attributed view for the browser."""
    model = _get(key, recipe_id, values, tol)
    groups = {}
    for f in model["faces"]:
        g = groups.setdefault(f["feature"], {"P": [], "T": [], "n": 0})
        g["T"].append(f["T"] + g["n"])
        g["P"].append(f["P"])
        g["n"] += len(f["P"])
    mesh = [{"feature": k, "positions": _b64(np.concatenate(g["P"]).astype(np.float32)),
             "indices": _b64(np.concatenate(g["T"]).astype(np.uint32))} for k, g in groups.items()]
    out = _summary(model, dock_mass_g)
    out["mesh"] = mesh
    from . import assembly as asm                      # parts, placements and per-part meshes when the design declares an assembly
    if asm.get(model) is not None:
        out["assembly"] = asm.view(model, _b64, _edges)
        if not out["assembly"]["error"]:
            out["mesh"] = asm.mesh(model, _b64)
    if edges:
        out["edges"] = _b64(_mesh_edges(*_mesh_arrays(model)) if getattr(model["recipe"], "mesh", False) else _edges(model["shape"]))
    return out


def op_summary(key, recipe_id, values, tol=0.05, dock_mass_g=None):
    return _summary(_get(key, recipe_id, values, tol), dock_mass_g)


def _oriented(shape, orientation):
    from build123d import Axis, Pos, Rot
    from . import analysis
    if orientation in ORIENTATIONS:
        rx, ry = ORIENTATIONS[orientation]
        s = Rot(rx, ry, 0) * shape if (rx or ry) else shape
    else:                                              # "down:x,y,z": the design direction that faces the plate (form/analysis.py)
        aa = analysis.axis_angle(orientation)
        if aa is None:
            raise RecipeError(f"Unknown print orientation “{orientation}”.", "", "Pick one from the orientation table.")
        s = shape.rotate(Axis((0, 0, 0), aa[0]), aa[1]) if abs(aa[1]) > 1e-9 else shape
    bb = s.bounding_box()
    return Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * s


def op_export(key, recipe_id, values, out_dir, name, orientation="as_modelled", tol=0.01, ang=0.1):
    """Write STEP (design frame) and STL (print frame). Returns paths and sizes."""
    from build123d import export_step, export_stl
    model = _get(key, recipe_id, values, 0.05)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    step, stl = out / f"{name}.step", out / f"{name}.stl"
    t = time.perf_counter()
    mesh = getattr(model["recipe"], "mesh", False)
    if not mesh:
        export_step(model["shape"], str(step))
    oriented = _oriented(model["shape"], orientation)
    export_stl(oriented, str(stl), tolerance=tol, angular_tolerance=ang)
    bb = oriented.bounding_box()
    out = {"step": None if mesh else str(step), "stl": str(stl), "orientation": orientation,
           "stl_tolerance_mm": tol, "print_bbox": [bb.size.X, bb.size.Y, bb.size.Z],
           "brep_volume_mm3": model["volume"], "seconds": round(time.perf_counter() - t, 3)}
    if mesh:
        out["unavailable"] = {"step": "Not available for mesh designs: OpenSCAD produces triangles, not a CAD solid."}
    return out


def op_test_piece(key, recipe_id, values, out_dir, name, tol=0.01):
    from build123d import export_stl
    model = _get(key, recipe_id, values, 0.05)
    res = model["recipe"].test_piece(model["values"], model["shape"])
    if res is None:
        raise RecipeError("This recipe does not define a test piece", "", "Print the fit coupon instead.")
    piece, info = res
    if not piece.is_valid or len(piece.solids()) != 1:
        raise RecipeError("The test piece did not come out as one solid", "", "Adjust the pocket so its walls are continuous.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.stl"
    bb = piece.bounding_box()
    export_stl(Pos0(piece, bb), str(path), tolerance=tol, angular_tolerance=0.1)
    return {"stl": str(path), "bbox": [bb.size.X, bb.size.Y, bb.size.Z], "volume_mm3": float(piece.volume), **info}


def Pos0(shape, bb):
    from build123d import Pos
    return Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * shape


def _orientation_table(P, T, extra=()):
    """One row per named orientation, plus any "down:x,y,z" orientation in `extra` (the project's, when it is not a named one)."""
    from . import analysis
    names = list(ORIENTATIONS) + [o for o in extra if o not in ORIENTATIONS and analysis.valid_orientation(o)]
    return [analysis.orientation_row(P, T, name) for name in names]


def _thickness(model, max_rays=1500):
    """Opposing-wall thickness by casting rays inward from surface samples."""
    from build123d import Vector
    from . import analysis
    inter_for = analysis.wall_intersectors(model)     # each part measured on its own: parts touching are not walls
    total = sum(f["area"] for f in model["faces"]) or 1
    kmin = 3 if len(model["faces"]) * 3 <= max_rays * 2 else 0      # a mesh has thousands of faces: sample by area only
    best = {"t": float("inf")}
    hist = []
    rng = np.random.default_rng(0)   # fixed seed: the same solid always gets the same samples
    exempt = set(getattr(model["recipe"], "wall_exempt", ()))     # lettering: its sharp corners are not walls (form/marks.py checks strokes)
    for f in model["faces"]:
        if f["feature"] in exempt:
            continue
        P, T = f["P"], f["T"]
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
        k = max(kmin, int(round(max_rays * f["area"] / total)))
        if k == 0:
            continue
        pick = rng.choice(len(T), size=k, p=areas / areas.sum())
        u, w_ = rng.random(k), rng.random(k)
        flip = u + w_ > 1
        u[flip], w_[flip] = 1 - u[flip], 1 - w_[flip]
        pts = a[pick] + (b[pick] - a[pick]) * u[:, None] + (c[pick] - a[pick]) * w_[:, None]
        for p in pts:
            try:
                n = f["face"].normal_at(Vector(*p))
            except Exception:
                continue
            hit = analysis.wall_hit(inter_for(f["face"]), p, (n.X, n.Y, n.Z))   # the same ray the thickness map casts
            if hit is None:                                      # nothing opposite, or a wedge at an edge or chamfer, not a wall
                continue
            w, qq = hit
            hist.append(w)
            if w < best["t"]:
                best = {"t": float(w), "at": [float(x) for x in p], "to": [float(x) for x in qq], "feature": f["feature"]}
    return best, hist


def op_analyse(key, recipe_id, values, stl_path=None, nozzle=0.4, envelope=(180, 180, 180), orientation="as_modelled"):
    """Computed checks on the solid and on the exported mesh. No heuristics dressed as facts."""
    from . import mesh_audit
    model = _get(key, recipe_id, values, 0.05)
    P, T = _mesh_arrays(model)
    table = _orientation_table(P, T, extra=(orientation,))
    thin, hist = _thickness(model)
    out = {"orientation_table": table, "thin": thin if thin["t"] < float("inf") else None,
           "thickness_samples": len(hist),
           "brep": {"valid": bool(model["shape"].is_valid), "solids": len(model["shape"].solids()),
                    "expected_solids": getattr(model["recipe"], "solids", 1),
                    "volume_mm3": model["volume"], "mesh_design": bool(getattr(model["recipe"], "mesh", False))},
           "interface_audit": model["recipe"].measure(model["values"], model["by_feature"])}
    from . import assembly as asm
    assembly_checks = asm.analyse(model)               # [] for a single part
    if assembly_checks:
        out["assembly"] = assembly_checks
    if stl_path:
        tris, stl_format, stl_sha = mesh_audit.read_stl(Path(stl_path))
        row = next(r for r in table if r["id"] == orientation)
        size = [row["footprint_mm"][0], row["footprint_mm"][1], row["height_mm"]]
        try:
            a = mesh_audit.audit(tris, bed=tuple(envelope), margin=2.0, expected_size=size, dimension_tolerance=0.05,
                                 expected_components=getattr(model["recipe"], "solids", 1))
        except ValueError as e:
            a = {"status": "ERROR", "failures": [str(e)]}
        a.pop("limitations", None)
        vols = a.get("signed_component_volumes_mm3") or [0]
        a["volume_mm3"] = float(sum(vols))
        a["format"], a["sha256"] = stl_format, stl_sha
        out["mesh"] = a
    return out


def op_variants(recipe_id, base, grid, tol=0.15):
    """Build every candidate for real. Infeasible ones report why."""
    import hashlib
    import json
    rows = []
    for changes in grid:
        vals = {**base, **changes}
        key = hashlib.sha1(json.dumps(vals, sort_keys=True).encode()).hexdigest()
        try:
            m = _get("var-" + key, recipe_id, vals, tol)
            s = _summary(m)
            P, T = _mesh_arrays(m)
            row0 = _orientation_table(P, T)[0]
            rows.append({"changes": changes, "ok": True, "volume_mm3": s["volume_mm3"], "bbox": s["bbox"],
                         "statics": s["statics"], "overhang_mm2": row0["steep_mm2"], "contact_mm2": row0["contact_mm2"],
                         "derived": s["derived"],
                         "mesh": {"positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32))}})
        except RecipeError as e:
            rows.append({"changes": changes, "ok": False, "error": e.public()})
    return rows


def op_evaluate(recipe_id, base, candidates, need_wall=False, tol=0.2):
    """Metrics for a batch of candidates, built for real. Used by the optimizer; no meshes returned."""
    import hashlib
    import json
    rows = []
    for changes in candidates:
        vals = {**base, **changes}
        key = hashlib.sha1(json.dumps(vals, sort_keys=True).encode()).hexdigest()
        t0 = time.perf_counter()
        try:
            m = _get("opt-" + key, recipe_id, vals, tol)
            s = _summary(m)
            P, T = _mesh_arrays(m)
            row0 = _orientation_table(P, T)[0]
            size = [b - a for a, b in zip(*s["bbox"])]
            met = {"volume_cm3": s["volume_mm3"] / 1000, "solid_mass_g": s["volume_mm3"] * 1.24e-3,
                   "width": size[0], "depth": size[1], "height": size[2],
                   "overhang_mm2": row0["steep_mm2"], "contact_mm2": row0["contact_mm2"]}
            for d in s["derived"]:
                met["derived." + d["key"]] = d["value"]
            for k, v in (s["statics"] or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    met["statics." + k] = v
            if need_wall:
                thin, _ = _thickness(m, max_rays=600)
                met["min_wall_mm"] = thin["t"] if thin["t"] < float("inf") else None
            rows.append({"changes": changes, "ok": True, "metrics": met, "s": round(time.perf_counter() - t0, 3)})
        except RecipeError as e:
            rows.append({"changes": changes, "ok": False, "error": e.public()})
    return rows


def _tessellate(shape, tol):
    """All faces of a shape as one triangle mesh (for drawing a reference part)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    BRepMesh_IncrementalMesh(shape.wrapped, tol, False, 0.35, True)
    Ps, Ts, off = [], [], 0
    for face in shape.faces():
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face.wrapped, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        P = np.empty((tri.NbNodes(), 3), dtype=np.float64)
        for i in range(1, tri.NbNodes() + 1):
            q = tri.Node(i).Transformed(trsf)
            P[i - 1] = (q.X(), q.Y(), q.Z())
        T = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.int64) - 1
        if face.wrapped.Orientation() == TopAbs_REVERSED:
            T = T[:, [0, 2, 1]]
        Ps.append(P)
        Ts.append(T + off)
        off += len(P)
    if not Ps:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    return np.concatenate(Ps), np.concatenate(Ts)


def op_reference(path, fmt, out):
    """Read an imported STEP or STL: measure it and write a display mesh (positions, indices, edges) to `out`.

    STEP: volume and box from the B-rep. STL: signed mesh volume and box from the triangles (not sewn: drawing only).
    """
    import json
    from . import mesh_audit
    p = Path(path)
    fmt = fmt.lower()
    if fmt in (".step", ".stp"):
        from build123d import import_step
        shape = import_step(str(p))
        bb = shape.bounding_box()
        diag = max(bb.diagonal, 1.0)
        P, T = _tessellate(shape, min(0.5, max(0.02, diag / 600)))
        edges = shape.edges()
        segs = []
        if len(edges) <= 20000:
            for e in edges:                          # draw curves coarsely: a reference is context, not the design
                n = 2 if e.geom_type.name == "LINE" else max(4, min(24, int(e.length / 2.5)))
                pts = [e.position_at(i / (n - 1)) for i in range(n)]
                segs += [(a.X, a.Y, a.Z, b.X, b.Y, b.Z) for a, b in zip(pts, pts[1:])]
        E = np.array(segs, dtype=np.float32) if segs else _mesh_edges(P, T)
        info = {"format": "step", "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]],
                "volume_mm3": float(shape.volume), "solids": len(shape.solids()), "faces": len(shape.faces())}
    elif fmt == ".stl":
        tris, _f, _sha = mesh_audit.read_stl(p)
        if not tris:
            raise RecipeError("The STL has no triangles.", "", "Export the part again.")
        P = np.array(tris, dtype=np.float64).reshape(-1, 3)
        T = np.arange(len(P), dtype=np.int64).reshape(-1, 3)
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        lo, hi = P.min(axis=0), P.max(axis=0)
        E = _mesh_edges(P, T)
        info = {"format": "stl", "bbox": [lo.tolist(), hi.tolist()], "volume_mm3": abs(vol), "solids": None}
    else:
        raise RecipeError(f"Unsupported format {fmt}", "", "Import a STEP (.step/.stp) or STL file.")
    if len(T) > 400_000:
        raise RecipeError(f"The part has {len(T):,} triangles to draw; Form Studio draws up to 400,000.", "",
                          "Export a simplified version of the part.")
    info["triangles"] = int(len(T))
    view = {"positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32)), "edges": _b64(E)}
    Path(out).write_text(json.dumps(view), encoding="utf-8")
    return info


def op_ping():
    return {"kernel": kernel_id()}


OPS = {k[3:]: v for k, v in list(globals().items()) if k.startswith("op_")}

# analysis maps, measuring and print orientations (form/analysis.py)
from .analysis import KERNEL_OPS as _ANALYSIS_OPS  # noqa: E402
OPS.update(_ANALYSIS_OPS)

# selections and annotations (form/selection.py)
from .selection import KERNEL_OPS as _SELECTION_OPS  # noqa: E402
OPS.update(_SELECTION_OPS)
from .materials import KERNEL_OPS as _MATERIAL_OPS  # noqa: E402  (3MF with colours)
OPS.update(_MATERIAL_OPS)
