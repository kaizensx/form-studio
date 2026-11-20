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


class _Skin:
    """The faces of one build stage, for asking "is this point on that stage's surface?" quickly.

    Measuring a point against the whole stage at once costs time in proportion to its faces, for every face of the
    result: a design made of imported meshes (thousands of triangle faces) then took longer than the kernel's time
    limit. A face carried over unchanged is recognised by identity; otherwise only faces whose box holds the point
    are measured."""

    def __init__(self, shape):
        self.faces = shape.faces()
        self.ids = {hash(f) for f in self.faces}
        boxes = []
        for f in self.faces:
            bb = f.bounding_box()
            boxes.append((bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z))
        self.lo = np.array([b[:3] for b in boxes], dtype=np.float64).reshape(-1, 3)
        self.hi = np.array([b[3:] for b in boxes], dtype=np.float64).reshape(-1, 3)

    def holds(self, face, probe, pt, d: float) -> bool:
        if hash(face) in self.ids:
            return True
        near = np.nonzero(np.all((self.lo - d <= probe) & (probe <= self.hi + d), axis=1))[0]
        return any(pt.distance_to(self.faces[i]) <= d for i in near)


def _where(e: BaseException, recipe) -> str:
    """The exception and, for a design written as code, the line of that code it came from: an agent fixes the
    source from this, so the type alone ("TypeError") is not enough."""
    import os
    import traceback
    msg = f"{type(e).__name__}: {e}".strip().rstrip(":")
    srcs = {os.path.realpath(f.__code__.co_filename) for c in type(recipe).__mro__ if c.__module__ not in ("builtins",)
            and not c.__module__.startswith("form.") for f in vars(c).values() if hasattr(f, "__code__")}
    if srcs:                                          # a design written as code: point at its line
        frames = [f for f in traceback.extract_tb(e.__traceback__) if os.path.realpath(f.filename) in srcs]
        if frames:
            f = frames[-1]
            msg += f" (line {f.lineno}" + (f": {f.line.strip()[:120]}" if f.line else "") + ")"
    return msg[:600]


def _build(recipe_id: str, values: dict, tol: float):
    """Build, attribute every face to a feature, and tessellate."""
    from build123d import CenterOf, Vertex
    recipe = resolve(recipe_id)
    v = recipe.validate(values)
    t0 = time.perf_counter()
    craft_notes = _craft_notes()                   # clear what an earlier build left
    try:
        stages = recipe.build(v)
    except RecipeError:
        raise
    except Exception as e:
        raise RecipeError(f"The kernel could not build this shape: {_where(e, recipe)}", "",
                          "Step back toward the last value that built, then change one parameter at a time.") from e
    final = stages[-1].shape
    t_build = time.perf_counter() - t0
    craft_notes = _craft_notes()                   # fallbacks form.craft took (a smaller fillet, a ruled loft)
    empty = [s.feature for i, s in enumerate(stages) if i and s.shape is stages[i - 1].shape]
    if not getattr(recipe, "mesh", False):
        for s in stages[:-1]:                      # a broken boolean early on can hide behind a valid-looking result
            try:
                bad = not s.shape.is_valid
            except Exception:
                bad = False
            if bad:
                craft_notes.append(f"stage {s.feature}: not a valid solid (a boolean failed; often a loft that "
                                   "folds over itself or two faces that just touch); later stages may hide it")
    solids = final.solids()
    want = getattr(recipe, "solids", 1)
    mesh = getattr(recipe, "mesh", False)          # a sewn triangle mesh: OCCT validity is not meaningful for it
    if not mesh and len(solids) != want:
        _stage_report(stages, want)                # name the stage where the solid count first went wrong
    if (not mesh and not final.is_valid) or len(solids) != want:
        raise RecipeError(
            f"The result is {len(solids)} solid(s) (valid={final.is_valid}); this design declares {want}", stages[-1].feature,
            "A cut has split the body, or parts touch and fused. Separate parts by a gap, or reduce the last change.")

    skins = [_Skin(s.shape) for s in stages[:-1]]
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
        if face.geom_type.name not in ("PLANE", "CYLINDER", "CONE"):
            # on a large free-form face a coarse triangle's centre can sit tenths of a mm off the surface: use the
            # nearest point on the face's own surface, so the feature test below compares surfaces, not the mesh
            try:
                from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
                from OCP.gp import gp_Pnt
                pj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, probe)), BRep_Tool.Surface_s(face.wrapped))
                if pj.NbPoints():
                    q = pj.NearestPoint()
                    probe = np.array([q.X(), q.Y(), q.Z()])
            except Exception:
                pass
        feature = stages[0].feature
        pt = Vertex(*probe)
        for i in range(len(skins) - 1, -1, -1):
            if not skins[i].holds(face, probe, pt, max(1.5 * tol, 0.01)):
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
        "t_build": t_build, "t_total": time.perf_counter() - t0, "tol": tol, "craft_notes": craft_notes,
        "unchanged_stages": empty,
    }
    return model


def _stage_report(stages, want: int) -> None:
    """A design whose result has the wrong number of solids: raise a RecipeError naming the first stage that left the
    solid empty (a failed boolean returns nothing) or that changed the count to something the next stages never
    repair, with each stage's count, so the agent fixes that feature instead of guessing."""
    counts = []
    for s in stages:
        try:
            n, vol = len(s.shape.solids()), float(s.shape.volume)
        except Exception:
            n, vol = 0, 0.0
        counts.append((s.feature, n, vol))
    trail = ", ".join(f"{f} {n}" for f, n, _ in counts)
    for i, (f, n, vol) in enumerate(counts):
        if n == 0 or vol <= 1e-9:
            raise RecipeError(f"The {f} step left no solid (a boolean failed and returned nothing). Solids per stage: "
                              f"{trail}", f, "Overlap the shapes by 0.2 mm instead of touching, move the cut off a loft "
                              "seam or a tangent face, or simplify the shape added in this step.")
    changed = [counts[i][0] for i in range(1, len(counts)) if counts[i][1] != counts[i - 1][1]]
    f = changed[-1] if changed else counts[0][0]
    raise RecipeError(f"The result is {counts[-1][1]} solid(s); this design declares {want}. Solids per stage: {trail} "
                      f"(read it to find the step that split or fused a part; the count last changed at {f}).", f,
                      "Parts that should stay separate touch or overlap (leave a gap), a cut split a body in two, or a "
                      "piece added does not reach the body it should join.")


def _craft_notes() -> list:
    try:
        from .craft import notes
        return notes()
    except Exception:                              # craft is optional for a design; never fail a build over its notes
        return []


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
        "craft_notes": model.get("craft_notes", []),
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
    if not getattr(model["recipe"], "mesh", False):                  # mesh textures show in the viewer and renders
        from .craft import meshtex
        tex = _textured(model, meshtex.VIEW_BUDGET)
        if tex is not None:
            V, F, tags, info = tex
            V32 = V.astype(np.float32)
            out["mesh"] = []
            for feat in dict.fromkeys(tags.tolist()):
                sel = F[tags == feat]
                used, inv = np.unique(sel, return_inverse=True)
                out["mesh"].append({"feature": feat, "positions": _b64(V32[used]),
                                    "indices": _b64(inv.reshape(-1, 3).astype(np.uint32))})
            out["mesh_texture"] = {"label": meshtex.LABEL, "triangles": info["triangles_out"]}
            out["triangles"] = info["triangles_out"]
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


def _rotated(shape, orientation):
    """The shape turned as the print orientation says (before it is dropped onto the plate)."""
    from build123d import Axis, Rot
    from . import analysis
    if orientation in ORIENTATIONS:
        rx, ry = ORIENTATIONS[orientation]
        return Rot(rx, ry, 0) * shape if (rx or ry) else shape
    aa = analysis.axis_angle(orientation)              # "down:x,y,z": the design direction that faces the plate (form/analysis.py)
    if aa is None:
        raise RecipeError(f"Unknown print orientation “{orientation}”.", "", "Pick one from the orientation table.")
    return shape.rotate(Axis((0, 0, 0), aa[0]), aa[1]) if abs(aa[1]) > 1e-9 else shape


def _rotation_matrix(orientation) -> np.ndarray:
    """3x3 matrix of _rotated(), read off by turning the unit points (for meshes made outside the B-rep)."""
    from build123d import Vertex
    o = _rotated(Vertex(0, 0, 0), orientation)
    o = np.array([o.X, o.Y, o.Z])
    cols = []
    for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
        v = _rotated(Vertex(*e), orientation)
        cols.append(np.array([v.X, v.Y, v.Z]) - o)
    return np.stack(cols, axis=1)


def _oriented(shape, orientation):
    from build123d import Pos
    s = _rotated(shape, orientation)
    bb = s.bounding_box()
    return Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * s


def _open_edges(path) -> int:
    """Edges of a binary STL used by one triangle only (vertices welded at 1e-6 mm): 0 for a closed mesh."""
    raw = np.fromfile(str(path), dtype=np.uint8)
    n = int(raw[80:84].view(np.uint32)[0]) if raw.size >= 84 else 0
    if n == 0:
        return 0
    rec = raw[84:84 + 50 * n].reshape(n, 50)
    V = np.ascontiguousarray(rec[:, 12:48]).view(np.float32).reshape(n, 3, 3).astype(np.float64)
    _, ids = np.unique(np.round(V.reshape(-1, 3) / 1e-6).astype(np.int64), axis=0, return_inverse=True)
    ids = ids.reshape(n, 3)
    E = np.sort(np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]]), axis=1)
    _, counts = np.unique(E, axis=0, return_counts=True)
    return int((counts == 1).sum())


def write_stl(shape, path, tol: float = 0.01, ang: float = 0.1) -> dict:
    """An STL of a valid solid with no holes. OCCT's mesher can fail on a face at one setting (a small face between
    tangent surfaces) and still return: that face gets no triangles, or its edges get a different polygon from its
    neighbour's, and the STL has an open boundary although the CAD solid is fine. The written mesh is checked
    edge by edge; when it is open the solid is meshed again with nearby settings and the first closed mesh is kept.
    A mesh that no setting closes is written with the asked-for settings, and the mesh check reports it."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.StlAPI import StlAPI_Writer

    def write(t, a):
        BRepTools.Clean_s(shape.wrapped)
        BRepMesh_IncrementalMesh(shape.wrapped, t, True, a, True).Perform()
        w = StlAPI_Writer()
        w.ASCIIMode = False                                    # binary, as build123d's export_stl writes
        w.Write(shape.wrapped, str(path))
        return _open_edges(path)

    tries = [(tol, ang), (tol, ang * 2), (tol / 2, ang * 2), (tol * 2, ang * 2), (tol / 10, ang), (tol * 5, max(ang * 2, 0.25))]
    first = None
    for t, a in tries:
        open_ = write(t, a)
        first = open_ if first is None else first
        if not open_:
            return {"tolerance": t, "angular_tolerance": a, "remeshed": (t, a) != (tol, ang), "open_edges": 0,
                    "open_edges_first": first}
    open_ = write(tol, ang)
    return {"tolerance": tol, "angular_tolerance": ang, "remeshed": False, "open_edges": open_, "open_edges_first": first}


def _textured(model, budget):
    """The design's mesh textures applied to its tessellation (form/craft/meshtex.py), or None when it declares none.
    Cached on the model per triangle budget: (V, F, feature per triangle, info)."""
    from .craft import meshtex
    cache = model.setdefault("_textured", {})
    if budget in cache:
        return cache[budget]
    try:
        specs = meshtex.declared(model["recipe"], model["values"])
    except RecipeError:
        raise
    except Exception as e:
        raise RecipeError(f"mesh_texture() raised {type(e).__name__}: {e}", "", "Fix mesh_texture() in the design source.")
    cache[budget] = meshtex.apply_to_faces(model["faces"], specs, budget) if specs else None
    return cache[budget]


def op_export(key, recipe_id, values, out_dir, name, orientation="as_modelled", tol=0.01, ang=0.1):
    """Write STEP (design frame) and STL (print frame). Returns paths and sizes.
    A design with mesh textures gets the textured mesh in its STL (and so its OBJ and GLB); the STEP stays smooth."""
    from build123d import export_step
    from .craft import meshtex
    model = _get(key, recipe_id, values, 0.05)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    step, stl = out / f"{name}.step", out / f"{name}.stl"
    t = time.perf_counter()
    mesh = getattr(model["recipe"], "mesh", False)
    if not mesh:
        export_step(model["shape"], str(step))
    tex = None if mesh else _textured(model, meshtex.EXPORT_BUDGET)
    if tex is not None:
        V, F, _tags, info = tex
        V = V @ _rotation_matrix(orientation).T
        lo, hi = V.min(axis=0), V.max(axis=0)
        V = V - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        meshtex.write_stl(stl, V, F)
        size = hi - lo
        out = {"step": str(step), "stl": str(stl), "orientation": orientation, "stl_tolerance_mm": tol,
               "print_bbox": [float(size[0]), float(size[1]), float(size[2])], "brep_volume_mm3": model["volume"],
               "seconds": round(time.perf_counter() - t, 3),
               "mesh_texture": {"label": meshtex.LABEL, "triangles": info["triangles_out"],
                                "textures": [{k: x[k] for k in ("kind", "amplitude", "scale", "features")} for x in info["textures"]],
                                **({"coarser": info["coarser"]} if info.get("coarser") else {})}}
        return out
    oriented = _oriented(model["shape"], orientation)
    used = write_stl(oriented, stl, tol, ang)
    bb = oriented.bounding_box()
    out = {"step": None if mesh else str(step), "stl": str(stl), "orientation": orientation,
           "stl_tolerance_mm": used["tolerance"], "print_bbox": [bb.size.X, bb.size.Y, bb.size.Z],
           "brep_volume_mm3": model["volume"], "seconds": round(time.perf_counter() - t, 3)}
    if mesh:
        out["unavailable"] = {"step": "Not available for mesh designs: OpenSCAD produces triangles, not a CAD solid."}
    return out


def _printed_parts(model, orientation="as_modelled", orient=None, envelope=(180, 180, 180), margin=2.0):
    """The design's printed parts, each laid on the plate by itself: [(id, label, material, oriented solid, orientation)].
    orient: {part id: orientation | "auto"}; a part without one lies as the design's `orientation` says.
    [] for a design of one solid."""
    from . import assembly as asm
    a = asm.get(model)
    if a is None or a.get("error") or len(a["printed"]) < 2:
        return []
    out = []
    for p, solid in zip(a["spec"].parts, a["printed"]):
        o = (orient or {}).get(p.id) or orientation
        if o == "auto":                                # the best-ranked way for this part alone (form/analysis.py)
            from . import analysis
            P, T = _tessellate(solid, 0.1)
            ranked = analysis.rank_orientations(P, T, [None] * len(T), set(), list(envelope), margin)
            o = ranked["candidates"][0]["id"] if ranked["candidates"] else orientation
        out.append((p.id, p.label, p.material, _oriented(solid, o), o))
    return out


def op_plate_parts(key, recipe_id, values, out_dir, name, orientation="as_modelled", orient=None, envelope=(180, 180, 180),
                   margin=2.0, tol=0.01, ang=0.1):
    """Each printed part as its own STL, centred and standing on z = 0, for the plate plan (form/plates.py)."""
    model = _get(key, recipe_id, values, 0.05)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    parts = []
    for pid, label, material, solid, o in _printed_parts(model, orientation, orient, envelope, margin):
        stl = out / f"{name}_{pid}.stl"
        write_stl(solid, stl, tol, ang)
        bb = solid.bounding_box()
        parts.append({"id": pid, "label": label, "material": material, "orientation": o, "stl": str(stl),
                      "size": [bb.size.X, bb.size.Y, bb.size.Z], "volume_mm3": float(solid.volume)})
    return {"parts": parts}


def op_test_piece(key, recipe_id, values, out_dir, name, tol=0.01):
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
    write_stl(Pos0(piece, bb), path, tol, 0.1)
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


def op_analyse(key, recipe_id, values, stl_path=None, nozzle=0.4, envelope=(180, 180, 180), orientation="as_modelled",
               orient=None, margin=2.0, assembly=False):
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
    parts = _printed_parts(model, orientation, orient, envelope, margin)   # each part as it lies on a plate by itself
    if parts:
        out["parts"] = [{"id": pid, "label": label, "material": material, "orientation": o,
                         "size": [round(b.size.X, 3), round(b.size.Y, 3), round(b.size.Z, 3)]}
                        for pid, label, material, solid, o in parts for b in [solid.bounding_box()]]
    if assembly:                                       # normally its own op (op_assembly), with its own time budget
        from . import assembly as asm
        assembly_checks = asm.analyse(model)           # [] for a single part
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
    elif fmt in (".stl", ".obj", ".3mf"):
        if fmt == ".stl":
            tris, _f, _sha = mesh_audit.read_stl(p)
        else:
            from .recon.mesh import read_triangles
            tris = read_triangles(p, fmt)[0].tolist()
        if not tris:
            raise RecipeError("The mesh has no triangles.", "", "Export the part again.")
        P = np.array(tris, dtype=np.float64).reshape(-1, 3)
        T = np.arange(len(P), dtype=np.int64).reshape(-1, 3)
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        lo, hi = P.min(axis=0), P.max(axis=0)
        E = _mesh_edges(P, T)
        info = {"format": fmt[1:], "bbox": [lo.tolist(), hi.tolist()], "volume_mm3": abs(vol), "solids": None}
    else:
        raise RecipeError(f"Unsupported format {fmt}", "", "Import a STEP (.step/.stp) or STL file.")
    if len(T) > 400_000:
        raise RecipeError(f"The part has {len(T):,} triangles to draw; Form Studio draws up to 400,000.", "",
                          "Export a simplified version of the part.")
    info["triangles"] = int(len(T))
    view = {"positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32)), "edges": _b64(E)}
    Path(out).write_text(json.dumps(view), encoding="utf-8")
    return info


PROGRESS = None        # set by the worker: sends ("progress", {...}) to the caller while an op runs


def op_assembly(key, recipe_id, values, budget_s=45.0):
    """Assembly checks (interference, fits, joint sweeps, tool access) within budget_s seconds of work.

    Separate from op_analyse so a long sweep has its own time limit and never holds up the other checks.
    Reports progress through PROGRESS while it runs."""
    from . import assembly as asm
    model = _get(key, recipe_id, values, 0.05)
    t0 = time.perf_counter()
    rows = asm.analyse(model, budget_s=budget_s, progress=PROGRESS)
    return {"checks": rows, "seconds": round(time.perf_counter() - t0, 2)}


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
from .geomdiff import KERNEL_OPS as _DIFF_OPS  # noqa: E402  (what changed between revisions)
OPS.update(_DIFF_OPS)
from .instructions import KERNEL_OPS as _INSTR_OPS  # noqa: E402  (assembly instructions)
OPS.update(_INSTR_OPS)
from .recon import KERNEL_OPS as _RECON_OPS  # noqa: E402  (mesh to editable CAD)
OPS.update(_RECON_OPS)
from .critique import KERNEL_OPS as _CRITIQUE_OPS  # noqa: E402  (design critique metrics and section views)
OPS.update(_CRITIQUE_OPS)
