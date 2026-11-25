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
    from . import build_diag, featureprog
    from .recipes.base import recording
    featureprog.begin()
    _LAST["stages"] = []
    _LAST["features"] = [(getattr(f, "id", ""), getattr(f, "label", "") or "") for f in getattr(recipe, "features", None) or []]
    try:
        with recording(on_stage=_stage_out if PROGRESS is not None else None) as made:
            _LAST["stages"] = made                 # what was built before a failure (op_try_build keeps it)
            stages = recipe.build(v)
    except RecipeError as e:                       # the design's, form.craft's or parts.checked's own words + the line
        try:
            err = build_diag.wrap(e, recipe)
        except Exception:
            raise e
        raise err from e
    except Exception as e:                         # the kernel's text, read into a cause, the feature and fixes
        try:
            err = build_diag.error(e, recipe)
        except Exception:
            err = RecipeError(f"The kernel could not build this shape: {_where(e, recipe)}", "",
                              "Step back toward the last value that built, then change one parameter at a time.")
        raise err from e
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
    if (not mesh and not final.is_valid and not getattr(recipe, "allow_invalid", False)) or len(solids) != want:  # allow_invalid: a partial build kept as it is (form/featureprog.py)
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
        "unchanged_stages": empty, **featureprog.report(),
    }
    return model


_LAST: dict = {"stages": []}     # the stages the last build made, in order (a failed build's are kept here)


def _stage_mesh(shape):
    """A coarse mesh of one stage, for showing the build as it grows (positions, indices, box)."""
    from OCP.BRepTools import BRepTools
    bb = shape.bounding_box()
    tol = max(0.1, float(bb.diagonal) / 400)
    try:
        P, T = _tessellate(shape, tol)
    finally:
        try:
            BRepTools.Clean_s(shape.wrapped)       # the final build meshes the solid at its own tolerance
        except Exception:
            pass
    return {"positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32)),
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]], "triangles": int(len(T))}


def _stage_out(stage) -> None:
    """Send each stage over PROGRESS as it is made, so the last valid solid is on screen while later features build."""
    if PROGRESS is None:
        return
    if not PROGRESS_MESH:                          # by name: what was made before a hang or a crash
        try:
            n = len(stage.shape.solids()) if hasattr(stage.shape, "solids") else 0
            PROGRESS({"kind": "stage_made", "feature": stage.feature, "index": len(_LAST["stages"]), "solids": n})
        except Exception:
            pass
        return
    try:
        if not hasattr(stage.shape, "solids") or not stage.shape.solids():
            return
        m = _stage_mesh(stage.shape)
        if not m["triangles"]:
            return
        feats = _LAST.get("features") or []
        ids = [f for f, _ in feats]
        at = ids.index(stage.feature) + 1 if stage.feature in ids else len(_LAST["stages"])
        PROGRESS({"kind": "stage", "feature": stage.feature, "index": len(_LAST["stages"]), "at": at,
                  "of": max(len(feats), at), "label": dict(feats).get(stage.feature) or "", **m})
    except Exception:
        pass


def _stage_quality(s, mesh: bool) -> tuple[bool, bool]:
    """(shows, valid) for one stage. shows: a non-empty solid whose triangle mesh encloses the volume the B-rep states
    (within 10 %): a boolean that half-failed can leave a "valid" solid that meshes to nothing or to a sliver.
    valid: OCCT's own check (always True for a mesh design)."""
    from OCP.BRepTools import BRepTools
    sh = s.shape
    try:
        if not hasattr(sh, "solids") or not sh.solids():
            return False, False
        vol = float(sh.volume)
        if vol <= 1e-9:
            return False, False
        if mesh:
            return True, True
        bb = sh.bounding_box()
        try:
            P, T = _tessellate(sh, max(0.05, float(bb.diagonal) / 1000))
        finally:
            BRepTools.Clean_s(sh.wrapped)
        if not len(T):
            return False, False
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        mv = abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
        shows = abs(mv - vol) <= 0.10 * vol
        return shows, bool(sh.is_valid)
    except Exception:
        return False, False


def op_try_build(key, recipe_id, values, tol=0.1, dock_mass_g=None):
    """Build like op_summary. When it fails: the error, and how many of the stages made before the failure can be
    kept (they are saved as checkpoints for the partial design, form/featureprog.py): the longest run of valid
    stages that show, else (when the first stage is already not valid by OCCT's check) the longest run that shows,
    with valid=False."""
    try:
        return {"ok": True, "summary": _summary(_get(key, recipe_id, values, tol), dock_mass_g)}
    except RecipeError as e:
        made = list(_LAST["stages"])
        recipe = resolve(recipe_id)
        mesh = bool(getattr(recipe, "mesh", False))
        q = []
        for st in made:
            q.append(_stage_quality(st, mesh))
            if not q[-1][0]:
                break
        keep = next((i for i, (shows, ok) in enumerate(q) if not (shows and ok)), len(q))
        valid = True
        if keep == 0:
            keep = next((i for i, (shows, _ok) in enumerate(q) if not shows), len(q))
            valid = False
        out = {"ok": False, "error": e.public(), "keep": keep, "valid": valid, "stages": [st.feature for st in made],
               "stage_checks": [{"feature": st.feature, "shows": a, "valid": b} for st, (a, b) in zip(made, q)]}
        if keep:
            from . import featureprog
            kept = made[:keep]
            featureprog.save_prefix(recipe_id, recipe.validate(values), kept)
            out["solids"] = len(kept[-1].shape.solids())
        return out


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
            raise _CountError(stages, want, f"The {f} step left no solid (a boolean failed and returned nothing). Solids per stage: "
                              f"{trail}", f, "Overlap the shapes by 0.2 mm instead of touching, move the cut off a loft "
                              "seam or a tangent face, or simplify the shape added in this step.")
    changed = [counts[i][0] for i in range(1, len(counts)) if counts[i][1] != counts[i - 1][1]]
    f = changed[-1] if changed else counts[0][0]
    raise _CountError(stages, want, f"The result is {counts[-1][1]} solid(s); this design declares {want}. Solids per stage: {trail} "
                      f"(read it to find the step that split or fused a part; the count last changed at {f}).", f,
                      "Parts that should stay separate touch or overlap (leave a gap), a cut split a body in two, or a "
                      "piece added does not reach the body it should join.")


def _CountError(stages, want, message, feature, hint):
    """A solid-count failure as a BuildError whose diagnosis lists each stage's solids, volume and validity."""
    from . import build_diag
    try:
        d = build_diag.stage_counts(stages, want)
        d["summary"] = message
    except Exception:
        d = {}
    return build_diag.BuildError(message, feature, hint, [], d)


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


FEATURE_EDGE_DEG = 25.0     # between two facets, an edge is drawn only where the surface turns more than this


def _facet_normals(shape) -> dict:
    """Faces of a solid that are mesh facets (a planar triangle: three straight edges): {face hash: outward normal}.
    A mesh brought in as a solid (Layer 0, frozen facets of Layer 1, a design that reads an STL) is made of them."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    out = {}
    for f in shape.faces():
        w = f.wrapped
        s = BRepAdaptor_Surface(w)
        if s.GetType() != GeomAbs_Plane:
            continue
        ex, k = TopExp_Explorer(w, TopAbs_EDGE), 0
        while ex.More() and k < 4:
            k += 1
            ex.Next()
        if k != 3:
            continue
        d = s.Plane().Axis().Direction()
        n = np.array([d.X(), d.Y(), d.Z()])
        if w.Orientation() == TopAbs_REVERSED:
            n = -n
        out[w.__hash__()] = n
    return out


def _edges(shape, facets: dict | None = None) -> np.ndarray:
    """The solid's edges as line segments, for drawing. Between two mesh facets an edge is drawn only where the
    surface turns by more than FEATURE_EDGE_DEG (a crease or a boundary), so a faceted solid reads like a part,
    not like a wireframe of triangles; every edge of a real CAD face is drawn."""
    if facets is None:
        facets = _facet_normals(shape)
    if len(facets) <= 3:
        segs = []
        for e in shape.edges():
            n = 2 if e.geom_type.name == "LINE" else max(8, min(48, int(e.length / 1.2)))
            pts = [e.position_at(i / (n - 1)) for i in range(n)]
            for p, q in zip(pts, pts[1:]):
                segs.append((p.X, p.Y, p.Z, q.X, q.Y, q.Z))
        return np.array(segs, dtype=np.float32).reshape(-1, 6)
    # a faceted solid: walk each edge once with its faces, straight edges by their two ends (fast on 10,000s of edges)
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    cos = np.cos(np.radians(FEATURE_EDGE_DEG))
    seen = {}                                             # edge (orientation ignored) -> [edge, normals of its facets]
    for f in shape.faces():
        n = facets.get(f.wrapped.__hash__())
        ex = TopExp_Explorer(f.wrapped, TopAbs_EDGE)
        while ex.More():
            e = ex.Current()
            seen.setdefault(e.__hash__(), [e]).append(n)
            ex.Next()
    segs = []
    for row in seen.values():
        ns = row[1:]
        if len(ns) == 2 and ns[0] is not None and ns[1] is not None and float(ns[0] @ ns[1]) > cos:
            continue                                      # two facets meeting at a gentle angle: no line
        e = TopoDS.Edge(row[0])
        if BRep_Tool.Degenerated_s(e):
            continue
        c = BRepAdaptor_Curve(e)
        a, b = c.FirstParameter(), c.LastParameter()
        if c.GetType() == GeomAbs_Line:
            n = 2
        else:
            n = max(8, min(48, int(GCPnts_AbscissaPoint.Length_s(c) / 1.2)))
        pts = [c.Value(a + (b - a) * k / (n - 1)) for k in range(n)]
        for p, q in zip(pts, pts[1:]):
            segs.append((p.X(), p.Y(), p.Z(), q.X(), q.Y(), q.Z()))
    return np.array(segs, dtype=np.float32).reshape(-1, 6)


def smooth_facets(P: np.ndarray, T: np.ndarray, crease_deg: float = FEATURE_EDGE_DEG) -> tuple[np.ndarray, np.ndarray]:
    """Share vertices between triangles that meet at the same point across an edge bending less than crease_deg, so
    a viewer's vertex normals shade a faceted surface smooth and keep creases sharp. Positions are not moved; only
    the indexing changes (vertices already shared stay shared)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    if len(T) < 2:
        return P, T
    T = np.asarray(T, dtype=np.int64)
    q = np.round(np.asarray(P, dtype=np.float64) / 1e-5).astype(np.int64)
    _, wid = np.unique(q, axis=0, return_inverse=True)
    wid = wid.reshape(-1)
    W = wid[T]
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a).astype(np.float64)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    # every triangle edge as (welded a, welded b) -> (triangle, corner of a, corner of b)
    ka = np.concatenate([W[:, 0], W[:, 1], W[:, 2]])
    kb = np.concatenate([W[:, 1], W[:, 2], W[:, 0]])
    va = np.concatenate([T[:, 0], T[:, 1], T[:, 2]])
    vb = np.concatenate([T[:, 1], T[:, 2], T[:, 0]])
    tri = np.tile(np.arange(len(T)), 3)
    lo, hi = np.minimum(ka, kb), np.maximum(ka, kb)
    swap = ka > kb
    va2, vb2 = np.where(swap, vb, va), np.where(swap, va, vb)     # va2 at the lower welded id
    o = np.lexsort((hi, lo))
    lo, hi, va2, vb2, tri = lo[o], hi[o], va2[o], vb2[o], tri[o]
    pair = np.flatnonzero((lo[1:] == lo[:-1]) & (hi[1:] == hi[:-1]))
    t1, t2 = tri[pair], tri[pair + 1]
    smooth = np.einsum("ij,ij->i", n[t1], n[t2]) > np.cos(np.radians(crease_deg))
    i0 = np.r_[va2[pair][smooth], vb2[pair][smooth]]
    i1 = np.r_[va2[pair + 1][smooth], vb2[pair + 1][smooth]]
    g = coo_matrix((np.ones(len(i0)), (i0, i1)), shape=(len(P), len(P)))
    k, lab = connected_components(g, directed=False)
    rep = np.zeros(k, dtype=np.int64)
    rep[lab] = np.arange(len(P))
    return np.asarray(P)[rep], lab[T]


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
    # features whose faces must not move (fit, access, mechanism, interface): their B-rep faces too, so a comparison
    # does not depend on how the tessellation of a neighbouring face changed (form/refine/engine.gate)
    roles = {f.id: getattr(f, "role", "") for f in getattr(model["recipe"], "features", None) or []}
    for fid, s in out.items():
        if roles.get(fid) in FROZEN_ROLES:
            s["brep"] = _brep_faces([f["face"] for f in model["faces"] if f["feature"] == fid and f.get("face") is not None])
    return out


FROZEN_ROLES = ("fit", "access", "mechanism", "interface")    # form.refine.FROZEN_ROLES (no import: kernel side)
BREP_FACES_MAX = 400


def _brep_faces(faces) -> list | None:
    """[[surface type, area mm2, centre x, y, z], ...] of B-rep faces, sorted; exact (GProp), not tessellated. None
    for more than BREP_FACES_MAX faces (a texture: the tessellation signature is used)."""
    if len(faces) > BREP_FACES_MAX:
        return None
    rows = []
    try:
        for f in faces:
            c = f.center()
            rows.append([f.geom_type.name, round(float(f.area), 4), round(float(c.X), 4), round(float(c.Y), 4),
                         round(float(c.Z), 4)])
    except Exception:                                  # a face OCCT cannot measure: no exact signature
        return None
    return sorted(rows)


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
        **({"build_log": model["log"]} if model.get("log") else {}),
        **({"skipped": model["skipped"]} if model.get("skipped") else {}),
        **({"parts_built": model["parts"]} if model.get("parts") else {}),
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
    facets = _model_facets(model)
    mesh = []
    for k, g in groups.items():
        P, T = np.concatenate(g["P"]), np.concatenate(g["T"])
        if facets:                                   # a faceted solid shades smooth, creases stay sharp
            P, T = smooth_facets(P, T)
        mesh.append({"feature": k, "positions": _b64(P.astype(np.float32)), "indices": _b64(T.astype(np.uint32))})
    out = _summary(model, dock_mass_g)
    out["mesh"] = mesh
    tex = None
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
            a = asm.get(model)
            tm = _textured_parts(model, a["face_part"], [p.id for p in a["spec"].parts]) if tex is not None else None
            # per-part meshes; the parts that carry a mesh texture keep it (the viewer and the render sheets)
            out["mesh"] = tm or asm.mesh(model, _b64, smooth_facets if facets else None)
    if edges:
        out["edges"] = _b64(_mesh_edges(*_mesh_arrays(model)) if getattr(model["recipe"], "mesh", False)
                            else _edges(model["shape"], facets))
    return out


def _model_facets(model) -> dict:
    """The model's mesh facets (see _facet_normals), found once per built model."""
    if "_facets" not in model:
        model["_facets"] = _facet_normals(model["shape"])
    return model["_facets"]


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


def _stl_ids(path):
    """(records (n, 50) uint8, welded vertex ids (n, 3)) of a binary STL; vertices welded at 1e-6 mm."""
    raw = np.fromfile(str(path), dtype=np.uint8)
    n = int(raw[80:84].view(np.uint32)[0]) if raw.size >= 84 else 0
    if n == 0:
        return raw[:0].reshape(0, 50), np.zeros((0, 3), np.int64)
    rec = raw[84:84 + 50 * n].reshape(n, 50)
    V = np.ascontiguousarray(rec[:, 12:48]).view(np.float32).reshape(n, 3, 3).astype(np.float64)
    _, ids = np.unique(np.round(V.reshape(-1, 3) / 1e-6).astype(np.int64), axis=0, return_inverse=True)
    return rec, ids.reshape(n, 3)


def drop_degenerate(path) -> int:
    """Remove the triangles of a binary STL whose corners weld to fewer than three points (zero-area slivers) and
    return how many went. OCCT's mesher leaves them where a fillet's vertex blend has a collapsed edge (three or more
    fillets meeting at a corner): the triangle (a, a, b) has no area, but its edge (a, a) is used once and a-b three
    times, so the mesh audit reads a closed solid as open and non-manifold. Dropping them changes no surface."""
    rec, ids = _stl_ids(path)
    if not len(ids):
        return 0
    bad = (ids[:, 0] == ids[:, 1]) | (ids[:, 1] == ids[:, 2]) | (ids[:, 2] == ids[:, 0])
    k = int(bad.sum())
    if k:
        raw = np.fromfile(str(path), dtype=np.uint8)
        keep = rec[~bad]
        head = raw[:80].copy()
        with open(path, "wb") as fh:
            fh.write(head.tobytes())
            fh.write(np.uint32(len(keep)).tobytes())
            fh.write(np.ascontiguousarray(keep).tobytes())
    return k


def _open_edges(path) -> int:
    """Edges of a binary STL used by one triangle only (vertices welded at 1e-6 mm, zero-area triangles left out):
    0 for a closed mesh."""
    _rec, ids = _stl_ids(path)
    if not len(ids):
        return 0
    ok = (ids[:, 0] != ids[:, 1]) & (ids[:, 1] != ids[:, 2]) & (ids[:, 2] != ids[:, 0])
    ids = ids[ok]
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
        dropped[0] = drop_degenerate(path)
        return _open_edges(path)

    dropped = [0]

    tries = [(tol, ang), (tol, ang * 2), (tol / 2, ang * 2), (tol * 2, ang * 2), (tol / 10, ang), (tol * 5, max(ang * 2, 0.25))]
    first = None
    for t, a in tries:
        open_ = write(t, a)
        first = open_ if first is None else first
        if not open_:
            return {"tolerance": t, "angular_tolerance": a, "remeshed": (t, a) != (tol, ang), "open_edges": 0,
                    "open_edges_first": first, "degenerate_dropped": dropped[0]}
    open_ = write(tol, ang)
    return {"tolerance": tol, "angular_tolerance": ang, "remeshed": False, "open_edges": open_, "open_edges_first": first,
            "degenerate_dropped": dropped[0]}


def _textured_parts(model, face_part: list, ids: list, budget: int | None = None) -> list | None:
    """The view mesh split by part, with the design's mesh textures applied part by part (each part gets a share of
    the triangle budget by its area), so a design with an assembly keeps its texture in the view. None when the
    design declares no texture."""
    from .craft import meshtex
    budget = budget or meshtex.VIEW_BUDGET
    specs = meshtex.declared(model["recipe"], model["values"])
    if not specs:
        return None
    by: dict = {}
    for f, k in zip(model["faces"], face_part):
        by.setdefault(k, []).append(f)
    total = sum(f["area"] for f in model["faces"]) or 1.0
    out = []
    for k, fs in by.items():
        share = sum(f["area"] for f in fs) / total
        V, F, tags, _info = meshtex.apply_to_faces(fs, specs, max(4000, int(budget * share)))
        V32 = V.astype(np.float32)
        for feat in dict.fromkeys(tags.tolist()):
            sel = F[tags == feat]
            used, inv = np.unique(sel, return_inverse=True)
            out.append({"feature": feat, "part": ids[k] if 0 <= k < len(ids) else "", "positions": _b64(V32[used]),
                        "indices": _b64(inv.reshape(-1, 3).astype(np.uint32))})
    return out


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
    # an export carries the texture on a finer tessellation than the view: smooth surfaces between the texture's
    # features must not show the view mesh's facets in a photo or a print
    faces = _fine_faces(model) if (specs and budget >= meshtex.EXPORT_BUDGET) else model["faces"]
    cache[budget] = meshtex.apply_to_faces(faces, specs, budget) if specs else None
    return cache[budget]


def _fine_faces(model, tol: float = 0.02, ang: float = 0.12):
    """The model's faces re-tessellated at an export tolerance, each keeping its feature (cached on the model)."""
    if "_fine_faces" in model:
        return model["_fine_faces"]
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    BRepMesh_IncrementalMesh(model["shape"].wrapped, tol, False, ang, True)
    out = []
    for f in model["faces"]:
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f["face"].wrapped, loc)
        if tri is None or tri.NbTriangles() == 0:
            out.append(f)
            continue
        trsf = loc.Transformation()
        P = np.empty((tri.NbNodes(), 3), dtype=np.float64)
        for i in range(1, tri.NbNodes() + 1):
            q = tri.Node(i).Transformed(trsf)
            P[i - 1] = (q.X(), q.Y(), q.Z())
        T = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.uint32) - 1
        if f["face"].wrapped.Orientation() == TopAbs_REVERSED:
            T = T[:, [0, 2, 1]]
        out.append({**f, "P": P, "T": T})
    model["_fine_faces"] = out
    return out


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
        E = _mesh_edges(P, T, FEATURE_EDGE_DEG)
        P, T = smooth_facets(P, T)                   # drawn smooth: no triangle edges, creases stay sharp
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
PROGRESS_MESH = True   # False: report stages by name only (the caller watches the build, it does not draw it)


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
from .appearance import KERNEL_OPS as _APPEARANCE_OPS  # noqa: E402  (material zones for photos)
OPS.update(_APPEARANCE_OPS)
from .candidates import KERNEL_OPS as _CANDIDATE_OPS  # noqa: E402  (several candidates built and scored)
OPS.update(_CANDIDATE_OPS)
