"""The boolean engine: one path for every fuse, cut and intersect in form.craft.

craft.fuse / craft.cut / craft.safe_union / craft.safe_cut / craft.safe_intersect all call run(). It does what a
person debugging a failed boolean would do, in order, and stops as soon as a result is right:

1. **Plain operation.** The kernel's own boolean, after pristine copies of the operands are taken (new topology, same
   geometry): a failed OCCT boolean raises its operands' tolerances in place, which left the body broken for every
   later try (the old ladder's "fuse: invalid result; fuzzy fuse 1e-4: invalid result; ..." was largely that), so the
   pre-flight and every rewrite run on copies of the pristine ones. A result is accepted when it is a valid solid,
   has the solid count the caller allows, its volume is inside what the operation can give, and, when it looks like a
   silent failure (a cut that removed or a fuse that added under 1 % of the smaller operand, a free-form volume
   outside the bounds), the mesh oracle agrees with it.
2. **Pre-flight, only when that fails.** Measured, not guessed: is each operand a valid solid (BRepCheck, free edges,
   and whether ShapeFix repairs it); the mesh oracle (manifold3d on a tessellation of each operand: the volume and the
   number of solids the result should have, and how much the operands overlap); the gap between them when they do
   not overlap; and coincident-face sampling (points spread over each operand's faces projected onto the other's: the
   area that lies on its surface, and within how many mm).
3. **Classification.** One cause from those measurements: empty_operand, invalid_operand, apart, small_gap,
   touching, parts_touch / parts_overlap (two parts that must stay separate), coincident_faces (fuse), grazing (cut),
   silent_wrong (a valid result the oracle refuses), not_joined, kernel.
4. **Class rewrites.** Only the ones for that cause, each on fresh copies: repaired operands (ShapeFix); for a fuse,
   only the part of the tool outside the body, a 0.01 mm fuzzy fuse, the tool grown or shrunk by a measured amount
   (it overshoots, or sits under, the coincident face); for a cut, a fuzzy cut at the measured deviation, the tool
   grown so it cuts past the face it grazes; closed faces split at their seams; glued faces. apart, parts_touch and
   parts_overlap get none: the geometry says no, so they fail at once. Every rewrite is checked like the plain one.
5. **Time bound.** The ladder stops at `budget` seconds (FORM_BOOLEAN_BUDGET, default 25) and says what it skipped.
6. **Error text.** A BooleanError (a RecipeError) with what was measured (overlap in mm³, gap in mm, coincident area,
   which operand is invalid and why), what each attempt did, and a hint for that cause. It never says the parts do
   not overlap when overlap was measured.

The oracle is a heuristic (evidence: mesh check). By default it refuses a result only on the silent-failure
signature: the kernel changed the body by under 1 % of the smaller operand where the oracle expects a real change, and
a finer oracle and the result's own tessellation confirm it. Any other disagreement keeps the kernel's result and
leaves a note with both numbers. FORM_BOOLEAN_VERIFY=full checks every result and refuses every confirmed gross
disagreement; off skips the oracle. Measured on twelve exemplars, checking every free-form result cost up to twice the
build time, and default-volume estimates were not reliable enough on trimmed B-spline faces to refuse more.

A mesh result is never taken silently: mesh_fallback=True (explicit, run() only) returns a faceted solid made from the
oracle's mesh, labelled "mesh fallback" in its label and in the notes. craft.fuse / craft.cut never do that.

    from form.craft import boolean
    body = boolean.run(body, pad, "fuse")                       # what craft.fuse does
    rep = boolean.last()                                         # {"class", "facts", "attempts", "seconds", ...}
    d = boolean.diagnose(body, pad, "fuse")                      # pre-flight and class only: {"class", "fact", "hint"}

Imports OCCT and manifold3d only when called (kernel worker).
"""
from __future__ import annotations

import math
import os
import time
from collections import OrderedDict

from ..recipes.base import RecipeError
from ._common import note

BRIDGE = 0.05                       # mm: the largest gap safe_union closes on its own
BUDGET_S = 25.0                     # s: the whole ladder of one boolean, unless FORM_BOOLEAN_BUDGET says otherwise
_ANALYTIC = None                    # GeomAbs surface types the kernel handles exactly (filled on first use)
_LAST: dict = {}
_VALID: "OrderedDict[int, tuple]" = OrderedDict()     # hash -> (shape, valid): shapes the engine already checked
_MESH: "OrderedDict[int, tuple]" = OrderedDict()      # hash -> (shape, (tol, manifold)): tessellations of exact shapes
_VOLD: "OrderedDict[int, tuple]" = OrderedDict()      # hash -> (shape, default volume)
_VOLP: "OrderedDict[int, tuple]" = OrderedDict()      # hash -> (shape, precise volume)

VERBS = {"fuse": "fuse", "cut": "cut", "common": "intersect"}


class BooleanError(RecipeError):
    """A boolean that failed after its class rewrites. .report holds the class, the measured facts and the attempts."""

    def __init__(self, message: str, feature: str = "", hint: str = "", params=None, report: dict | None = None):
        super().__init__(message, feature, hint, list(params or []))
        self.report = report or {}

    def public(self) -> dict:
        return {**super().public(), "boolean": _public_report(self.report)}


def last() -> dict:
    """The report of the last boolean run() finished (class, facts, attempts, seconds), success or failure."""
    return dict(_LAST)


def budget_s() -> float:
    try:
        return max(1.0, float(os.environ.get("FORM_BOOLEAN_BUDGET", BUDGET_S)))
    except ValueError:
        return BUDGET_S


def _verify_mode() -> str:
    m = os.environ.get("FORM_BOOLEAN_VERIFY", "auto").strip().lower()
    return m if m in ("auto", "full", "off") else "auto"


# ---- small kernel helpers ------------------------------------------------------------------------------------------

def _remember(cache: OrderedDict, shape, value, cap: int = 8):
    try:
        k = hash(shape)
    except Exception:
        return
    cache[k] = (shape, value)
    cache.move_to_end(k)
    while len(cache) > cap:
        cache.popitem(last=False)


def _recall(cache: OrderedDict, shape):
    try:
        k = hash(shape)
        hit = cache.get(k)
        if hit is not None and hit[0].wrapped.IsSame(shape.wrapped) and hit[0].wrapped.Location().IsEqual(
                shape.wrapped.Location()):
            return hit[1]
    except Exception:
        pass
    return None


def _solids(s) -> int:
    try:
        return len(s.solids())
    except Exception:
        return 0


def _valid(s) -> bool:
    v = _recall(_VALID, s)
    if v is not None:
        return v
    try:
        v = bool(s.is_valid)
    except Exception:
        v = False
    _remember(_VALID, s, v, 32)
    return v


def _volume(s, precise: bool = False) -> float:
    """Volume in mm³, cached per shape: default integration (fast, about 1 % off on trimmed free-form faces) or
    precise (eps 1e-6, slower)."""
    cache = _VOLP if precise else _VOLD
    v = _recall(cache, s)
    if v is not None:
        return v
    try:
        if not precise:
            v = float(s.volume)
        else:
            from OCP.BRepGProp import BRepGProp
            from OCP.GProp import GProp_GProps
            p = GProp_GProps()
            BRepGProp.VolumeProperties_s(s.wrapped, p, 1e-6, False)
            v = abs(float(p.Mass()))
    except Exception:
        return 0.0
    _remember(cache, s, v, 32)
    return v


def _area(s) -> float:
    try:
        return float(s.area)
    except Exception:
        return 0.0


def _usable(r) -> tuple[bool, str]:
    """(ok, why not): a valid solid result with positive volume."""
    if r is None:
        return False, "no result"
    n = _solids(r)
    if n == 0:
        return False, "no solid in the result"
    if not _valid(r):
        f = _faults(r)
        return False, "the result is not a valid solid" + (f" ({', '.join(f)})" if f else "")
    if _volume(r) <= 1e-9:
        return False, "the result has no volume"
    return True, ""


def _faults(s) -> list:
    """What is wrong with an invalid shape: BRepCheck faults by kind, and free edges (an open shell)."""
    out = []
    try:
        from ..build_diag import _faults as f
        out = f(s)
    except Exception:
        pass
    try:
        from collections import Counter
        uses = Counter(hash(e) for f in s.faces() for e in f.edges())
        free = sum(1 for n in uses.values() if n == 1)
        if free:
            out.append(f"open shell: {free} free edge{'s' if free > 1 else ''}")
    except Exception:
        pass
    return out


def _freeform(s) -> bool:
    """True when a face is not a plane, cylinder, cone, sphere or torus (B-spline skins, offsets, lofts)."""
    global _ANALYTIC
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import (GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus)
        if _ANALYTIC is None:
            _ANALYTIC = {GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere, GeomAbs_Torus}
        for f in s.faces():
            if BRepAdaptor_Surface(f.wrapped).GetType() not in _ANALYTIC:
                return True
    except Exception:
        return True
    return False


def _bbox(s):
    return s.bounding_box(optimal=False)


def _diag(*shapes) -> float:
    d = 0.0
    for s in shapes:
        try:
            bb = _bbox(s)
            d = max(d, math.dist((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)))
        except Exception:
            pass
    return d or 1.0


def _boxes_overlap(a, b, pad: float = 0.0) -> bool:
    try:
        x, y = _bbox(a), _bbox(b)
        return all(getattr(x.min, k) <= getattr(y.max, k) + pad and getattr(y.min, k) <= getattr(x.max, k) + pad
                   for k in "XYZ")
    except Exception:
        return True


def _list(*shapes):
    try:
        from OCP.TopTools import TopTools_ListOfShape
    except ImportError:                                   # newer OCP names the template instance
        from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape
    out = TopTools_ListOfShape()
    for s in shapes:
        out.Append(s.wrapped)
    return out


def occt(a, b, op: str, fuzzy: float = 0.0, glue: str = ""):
    """One kernel boolean with options: fuzzy value (mm) and glue ("shift", "full"). Returns a build123d shape."""
    from build123d import Part, Shape
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    mk = {"cut": BRepAlgoAPI_Cut, "fuse": BRepAlgoAPI_Fuse, "common": BRepAlgoAPI_Common}[op]()
    mk.SetArguments(_list(a))
    mk.SetTools(_list(b))
    if fuzzy:
        mk.SetFuzzyValue(fuzzy)
    if glue:
        from OCP.BOPAlgo import BOPAlgo_GlueEnum
        mk.SetGlue({"shift": BOPAlgo_GlueEnum.BOPAlgo_GlueShift, "full": BOPAlgo_GlueEnum.BOPAlgo_GlueFull}[glue])
    mk.SetRunParallel(True)
    mk.SetNonDestructive(True)                            # never raise the operands' own tolerances
    mk.Build()
    if not mk.IsDone():
        raise ValueError("boolean not done")
    r = Shape.cast(mk.Shape())
    try:
        r = r.clean()
    except Exception:
        pass
    return r if r.solids() else Part()


def _feature_time_left() -> float | None:
    """Seconds left in the FeatureDesign feature being built (form/featureprog.py), or None outside one."""
    import sys
    fp = sys.modules.get(__package__.rsplit(".", 1)[0] + ".featureprog")
    try:
        return fp.time_left() if fp is not None else None
    except Exception:
        return None


def _plain(a, b, op: str):
    return a + b if op == "fuse" else a - b if op == "cut" else a & b


def fix(shape):
    """ShapeFix the shape (tolerances, small edges, orientation); the fixed shape only when it is valid."""
    from build123d import Shape
    try:
        from OCP.ShapeFix import ShapeFix_Shape
        fx = ShapeFix_Shape(shape.wrapped)
        fx.Perform()
        out = Shape.cast(fx.Shape())
        if _solids(out) and _valid(out):
            return _one(out)
    except Exception:
        pass
    return None


def split_closed(shape):
    """Closed (periodic) faces split at their seams (ShapeUpgrade_ShapeDivideClosed): a loft skin that wraps round
    is one face with a seam edge, and a tool crossing that seam is a classic failed boolean."""
    from build123d import Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed
    d = ShapeUpgrade_ShapeDivideClosed(shape.wrapped)
    d.Perform()
    return _one(Shape.cast(d.Result()))


def _closed_faces(shape) -> int:
    try:
        from OCP.BRep import BRep_Tool
        n = 0
        for f in shape.faces():
            s = BRep_Tool.Surface_s(f.wrapped)
            if s.IsUClosed() or s.IsVClosed():
                n += 1
        return n
    except Exception:
        return 0


def grow(shape, amount: float):
    """The shape offset outward by amount (mm): a true offset first, a scale about its centre when the offset fails
    (that moves no face further than amount)."""
    from build123d import Pos, Shape
    try:
        from OCP.BRepOffset import BRepOffset_Skin
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
        from OCP.GeomAbs import GeomAbs_Arc
        mk = BRepOffsetAPI_MakeOffsetShape()
        mk.PerformByJoin(shape.wrapped, amount, 1e-5, BRepOffset_Skin, False, False, GeomAbs_Arc)
        if mk.IsDone():
            out = _one(Shape.cast(mk.Shape()))
            if _solids(out) == _solids(shape) and _valid(out) and (_volume(out) - _volume(shape)) * amount > 0:
                return out, "offset"
    except Exception:
        pass
    bb = _bbox(shape)
    c = bb.center()
    r = max(math.dist((c.X, c.Y, c.Z), (x, y, z)) for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y)
            for z in (bb.min.Z, bb.max.Z)) or 1.0
    k = 1.0 + amount / r
    return Pos(c.X, c.Y, c.Z) * (Pos(-c.X, -c.Y, -c.Z) * shape).scale(k), f"scale x{k:.6f}"


def _retype(like, out):
    from build123d import Compound
    if isinstance(like, Compound) and isinstance(out, Compound) and type(out) is not type(like):
        try:
            out = type(like)(out.wrapped)                 # the same build123d class (a Part stays a Part)
        except Exception:
            pass
    try:
        out.label, out.color = like.label, like.color
    except Exception:
        pass
    return out


def _copy(shape):
    """A copy with new topology (where OCCT keeps tolerances), the same geometry and the faces' meshes (so a later
    tessellation of the result reuses them for untouched faces, as it did before). A boolean raises its operands'
    tolerances in place, so a failed try would leave the caller's body changed and the next try behaving differently;
    the geometry stays shared, so operands built on one surface (two bands cut from one offset body) still share it
    instead of making the kernel intersect two identical surfaces, which is slow and fragile."""
    from build123d import Shape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    return _retype(shape, Shape.cast(BRepBuilderAPI_Copy(shape.wrapped, False, True).Shape()))


def _copy_pair(a, b):
    """_copy of both operands in one go, so the sub-shapes they share (a face or edge both came from) stay shared."""
    from build123d import Shape
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.TopoDS import TopoDS_Compound, TopoDS_Iterator
    bld, comp = BRep_Builder(), TopoDS_Compound()
    bld.MakeCompound(comp)
    bld.Add(comp, a.wrapped)
    bld.Add(comp, b.wrapped)
    cp = BRepBuilderAPI_Copy(comp, False, True)
    copied = cp.Shape()                                   # kept alive while the iterator walks it
    it = TopoDS_Iterator(copied)
    kids = []
    while it.More():
        kids.append(it.Value())
        it.Next()
    if len(kids) != 2:
        return _copy(a), _copy(b)
    return _retype(a, Shape.cast(kids[0])), _retype(b, Shape.cast(kids[1]))


def _one(shape):
    try:
        s = shape.solids()
        return s[0] if len(s) == 1 else shape
    except Exception:
        return shape


# ---- the mesh oracle ------------------------------------------------------------------------------------------------

def _manifold(shape, tol: float):
    """A manifold3d mesh of a copy of the shape (the shape's own triangulation is left alone), cached by shape."""
    hit = _recall(_MESH, shape)
    if hit is not None and hit[0] <= tol * 1.5:
        return hit[1]
    import numpy as np
    import manifold3d as m3
    from build123d import Shape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from ..meshbody import weld
    cp = Shape.cast(BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape())
    vs, ts = cp.tessellate(tol, 0.2)
    if not ts:
        raise ValueError("no triangles")
    V = np.array([(q.X, q.Y, q.Z) for q in vs], dtype=np.float64)
    F = np.asarray(ts, dtype=np.int64)
    V, F = weld(V[F], 1e-6)
    m = m3.Manifold(m3.Mesh(vert_properties=np.asarray(V, np.float32), tri_verts=np.asarray(F, np.uint32)))
    if m.status() != m3.Error.NoError:
        raise ValueError(f"tessellation is not closed ({m.status()})")
    _remember(_MESH, shape, (tol, m), 6)
    return m


def oracle(a, b, op: str, precise: bool = False) -> dict | None:
    """What the boolean should give, from exact mesh booleans of the operands' tessellations (manifold3d): the
    result's volume, its solids (pieces under the mesh error are slivers and are not counted), the operands' overlap,
    and the mesh error (how far each mesh's volume is from the exact one). None when manifold3d is missing or an
    operand does not tessellate to a closed mesh."""
    try:
        from ..meshbody import has_manifold
        if not has_manifold():
            return None
        t0 = time.perf_counter()
        tol = min(0.2, max(0.01, 1e-3 * _diag(a, b))) if not precise else min(0.05, max(0.005, 2e-4 * _diag(a, b)))
        ma, mb = _manifold(a, tol), _manifold(b, tol)
        va, vb = _volume(a), _volume(b)
        mva, mvb = float(ma.volume()), float(mb.volume())
        err = abs(mva - va) + abs(mvb - vb)
        res = ma + mb if op == "fuse" else ma - mb if op == "cut" else ma ^ mb
        vo = float(res.volume())
        sliver = max(5e-4 * max(va, vb), 1e-3)
        # solids and overlap only for the pre-flight (precise): a verification needs the volume alone
        parts = [p for p in res.decompose() if float(p.volume()) > sliver] if precise else None
        overlap = float((ma ^ mb).volume()) if precise else None
        return {"volume": vo, "solids": len(parts) if parts is not None else None, "delta": vo - mva,
                "overlap": overlap, "err": err, "err_a": abs(mva - va), "err_b": abs(mvb - vb), "area_b": _area(b),
                "mesh_a": mva, "mesh_b": mvb, "va": va, "vb": vb, "tol": tol, "sliver": sliver, "manifold": res,
                "seconds": time.perf_counter() - t0}
    except Exception:
        return None


def _agrees(r, a, orc: dict, b=None, strict: bool = False) -> tuple[bool, str]:
    """Does the kernel's result agree with the oracle? Compared as the change of volume (the result's against the
    first operand's), so error over the faces the operation does not touch cancels out; the slack is what the
    tessellation can be off by where the tool's faces are (its area times the mesh tolerance, both sides). Default
    volumes only: precise integration can take minutes on a few trimmed B-spline faces. A disagreement is confirmed
    with an oracle four times finer and with the result's own tessellation. Then only the silent-failure signature
    refuses the result: the kernel changed (almost) nothing, under 1 % of the smaller operand, where the oracle expects
    a real change (a cut that removed nothing, a pad that added nothing). Any other disagreement keeps the kernel's
    result with a note: the oracle can be off too (on the mouse exemplar's grip bands, over near-coincident offset
    surfaces, it disagreed with two independent estimates of the kernel's result that agreed with each other).
    strict (FORM_BOOLEAN_VERIFY=full): refuse every confirmed gross disagreement."""
    def slack_of(o, de):
        return (0.15 * max(abs(de), abs(o["delta"])) + 2 * o["tol"] * o["area_b"] + 2 * o["err_b"]
                + 1e-4 * max(o["va"], o["vb"]) + 1e-3)
    de = _volume(r) - _volume(a)
    if abs(de - orc["delta"]) <= slack_of(orc, de) + 2e-3 * orc["va"]:
        return True, ""
    o = orc
    if b is not None:
        fine = _fine_oracle(a, b, orc)
        o = fine or orc
    slack = slack_of(o, de) + 2e-3 * o["va"]
    if abs(de - o["delta"]) <= slack:
        return True, ""
    word = "removed" if orc.get("op") == "cut" else "added" if orc.get("op") == "fuse" else "changed"
    got, want = (-de, -o["delta"]) if word == "removed" else (de, o["delta"])
    gross = abs(de - o["delta"]) > 0.5 * max(abs(o["delta"]), abs(de)) + slack
    if gross:
        # default volumes can be far off on trimmed free-form faces, so a second, independent estimate must agree
        # before a result is refused: the result's own tessellation, at the oracle's tolerance
        try:
            dm = float(_manifold(r, o["tol"]).volume()) - o["mesh_a"]
            if abs(dm - o["delta"]) <= 0.5 * max(abs(o["delta"]), abs(dm)) + slack:
                gross = False
        except Exception:
            pass
    if gross and not strict and abs(de) > 0.01 * min(o["va"], o["vb"]) + 1e-6:
        gross = False                                       # it did change the body: not a silent failure
    orc["borderline"] = None if gross else (f"the result {word} {got:.4g} mm³ where the mesh check expects "
                                            f"{want:.4g} ± {slack:.2g} mm³")
    if not gross:
        return True, ""
    return False, (f"the result {word} {got:.4g} mm³ where the mesh check expects {want:.4g} ± {slack:.2g} mm³ "
                   "(a valid-looking wrong result)")


def _fine_oracle(a, b, orc: dict) -> dict | None:
    """The oracle again with a mesh four times finer (cached on orc), to confirm a disagreement."""
    if "fine" in orc:
        return orc["fine"]
    try:
        tol = orc["tol"] / 4
        ma, mb = _manifold(a, tol), _manifold(b, tol)
        op = orc.get("op")
        res = ma + mb if op == "fuse" else ma - mb if op == "cut" else ma ^ mb
        mva, mvb = float(ma.volume()), float(mb.volume())
        fine = {**{k: v for k, v in orc.items() if k != "fine"}, "tol": tol, "delta": float(res.volume()) - mva,
                "mesh_a": mva, "mesh_b": mvb, "err_b": abs(mvb - orc["vb"]), "manifold": res}
    except Exception:
        fine = None
    orc["fine"] = fine
    return fine


def _bounds(r, a, b, va: float, vb: float, op: str, extra: float = 0.0) -> tuple[bool, str]:
    """Volumes no correct boolean can break (default volumes: exact on analytic faces; on trimmed free-form faces they
    can be off, so there a broken bound only sends the result to the oracle)."""
    def test(vr, va, vb, s):
        if op == "fuse" and not (max(va, vb) - s <= vr <= va + vb + s):
            return f"the result is {vr:.5g} mm³, outside what fusing {va:.5g} and {vb:.5g} mm³ can give"
        if op == "cut" and not (va - vb - s <= vr <= va + s):
            return f"the result is {vr:.5g} mm³, outside what cutting {vb:.5g} from {va:.5g} mm³ can give"
        if op == "common" and vr > min(va, vb) + s:
            return f"the result is {vr:.5g} mm³, more than the smaller operand"
        return ""
    why = test(_volume(r), va, vb, 1e-3 * max(va, vb) + 1e-6 + extra)
    return (not why), why


# ---- measurement -----------------------------------------------------------------------------------------------------

def _gap(a, b) -> float:
    try:
        return max(0.0, float(a.distance_to(b)))
    except Exception:
        try:
            from OCP.BRepExtrema import BRepExtrema_DistShapeShape
            d = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
            d.Perform()
            return float(d.Value()) if d.IsDone() else math.inf
        except Exception:
            return math.inf


def _face_samples(shape, n_max: int = 240):
    """(points, area per point) spread over the shape's faces by area, inside each face's trim."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN
    faces = list(shape.faces())
    areas = []
    for f in faces:
        try:
            areas.append(max(float(f.area), 0.0))
        except Exception:
            areas.append(0.0)
    tot = sum(areas) or 1.0
    out = []
    for f, ar in zip(faces, areas):
        k = max(2, min(9, int(math.sqrt(n_max * ar / tot)) + 1))
        try:
            umin, umax, vmin, vmax = BRepTools.UVBounds_s(f.wrapped)
            ad = BRepAdaptor_Surface(f.wrapped)
            fw = f.wrapped
        except Exception:
            continue
        pts = []
        while True:                                  # a thin face (a cut ring) needs a finer grid to be hit at all
            for i in range(k):
                for j in range(k):
                    u = umin + (umax - umin) * (i + 0.5) / k
                    v = vmin + (vmax - vmin) * (j + 0.5) / k
                    try:
                        if BRepClass_FaceClassifier(fw, gp_Pnt2d(u, v), 1e-7).State() == TopAbs_IN:
                            pts.append(ad.Value(u, v))
                    except Exception:
                        continue
            if len(pts) >= 3 or k >= 48:
                break
            pts, k = [], k * 3
        if len(pts) > 81:
            pts = pts[::max(1, len(pts) // 81)]
        for p in pts:
            out.append((p, ar / len(pts)))
    return out


def _projectors(shape, pad: float):
    """Per face: the face, a ShapeAnalysis_Surface (projection with a cached grid) and its box grown by pad."""
    from OCP.BRep import BRep_Tool
    from OCP.ShapeAnalysis import ShapeAnalysis_Surface
    out = []
    for f in shape.faces():
        try:
            bb = _bbox(f)
            box = (bb.min.X - pad, bb.min.Y - pad, bb.min.Z - pad, bb.max.X + pad, bb.max.Y + pad, bb.max.Z + pad)
            out.append((f.wrapped, ShapeAnalysis_Surface(BRep_Tool.Surface_s(f.wrapped)), box))
        except Exception:
            continue
    return out


def contact(a, b, tol: float = 0.02, n_max: int = 240, seconds: float = 4.0) -> dict:
    """Coincident-face sampling: points spread over b's faces (by area, inside each face's trim) projected onto a's
    faces. A point within tol of a face of a, inside that face's trim, lies on a's surface: on_area_mm2 is the share
    of b's area that does, dev_mm the largest distance among those points (how coincident they are)."""
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_OUT
    t0 = time.perf_counter()
    samples = _face_samples(b, n_max)
    proj = _projectors(a, tol)
    on, area_on, area, devs = 0, 0.0, 0.0, []
    for p, w in samples:
        if time.perf_counter() - t0 > seconds:
            break
        area += w
        best = None
        x, y, z = p.X(), p.Y(), p.Z()
        for fw, sas, bx in proj:
            if not (bx[0] <= x <= bx[3] and bx[1] <= y <= bx[4] and bx[2] <= z <= bx[5]):
                continue
            try:
                uv = sas.ValueOfUV(p, 1e-7)
                d = sas.Gap()
                if d <= tol and BRepClass_FaceClassifier(fw, uv, 1e-6).State() != TopAbs_OUT:
                    best = d if best is None else min(best, d)
            except Exception:
                continue
        if best is not None:
            on += 1
            area_on += w
            devs.append(best)
    return {"samples": len(samples), "on": on, "on_share": area_on / area if area else 0.0,
            "on_area_mm2": area_on, "area_mm2": area, "dev_mm": max(devs) if devs else None, "tol_mm": tol,
            "seconds": time.perf_counter() - t0}


def measure(a, b, op: str, seconds: float = 8.0) -> dict:
    """The pre-flight, measured: validity (and whether ShapeFix repairs it), exact volumes, the mesh oracle, overlap,
    gap, coincident faces both ways, closed faces. Every number is computed from the shapes."""
    t0 = time.perf_counter()
    f: dict = {"op": op}
    for k, s in (("a", a), ("b", b)):
        f[f"solids_{k}"] = _solids(s)
        f[f"valid_{k}"] = _valid(s) if f[f"solids_{k}"] else False
        if not f[f"valid_{k}"] and f[f"solids_{k}"]:
            f[f"faults_{k}"] = _faults(s)
            f[f"fixed_{k}"] = fix(_copy(s)) is not None
        f[f"freeform_{k}"] = _freeform(s) if f[f"solids_{k}"] else False
        f[f"closed_faces_{k}"] = _closed_faces(s) if f[f"solids_{k}"] else 0
    if not (f["solids_a"] and f["solids_b"]):
        f["seconds"] = time.perf_counter() - t0
        return f
    orc = oracle(a, b, op, precise=True)
    if orc:
        orc["op"] = op
        f["oracle"] = {k: v for k, v in orc.items() if k != "manifold"}
        f["overlap_mm3"] = orc["overlap"]
        f["_oracle"] = orc
    va, vb = (orc["va"], orc["vb"]) if orc else (_volume(a), _volume(b))
    f["volume_a"], f["volume_b"] = va, vb
    over_thr = max(2e-3 * min(va, vb), 1e-3)
    f["overlap_threshold_mm3"] = over_thr
    overlapping = orc is not None and orc["overlap"] > over_thr
    f["overlaps"] = overlapping if orc else None
    if not overlapping:
        f["gap_mm"] = _gap(a, b) if _boxes_overlap(a, b, 5.0) else _gap(a, b)
    left = max(0.5, seconds - (time.perf_counter() - t0))
    tol = min(0.05, max(0.005, 2e-4 * _diag(a, b)))
    try:
        cb = contact(a, b, tol, seconds=left / 2)
        ca = contact(b, a, tol, seconds=left / 2)
        f["contact_b_on_a"], f["contact_a_on_b"] = cb, ca
        f["coincident_mm2"] = max(cb["on_area_mm2"], ca["on_area_mm2"])
        devs = [c["dev_mm"] for c in (cb, ca) if c["dev_mm"] is not None]
        f["coincident_dev_mm"] = max(devs) if devs else None
        f["coincident_share"] = max(cb["on_share"], ca["on_share"])
    except Exception:
        pass
    f["seconds"] = time.perf_counter() - t0
    return f


# ---- classification ------------------------------------------------------------------------------------------------

def classify(f: dict, min_solids: int, lim: int, bridge: float, wrong: bool = False) -> str:
    """One cause from the measured facts (see the module docstring for the classes)."""
    op = f["op"]
    if not (f.get("solids_a") and f.get("solids_b")):
        return "empty_operand"
    if (not f.get("valid_a") and not f.get("fixed_a")) or (not f.get("valid_b") and not f.get("fixed_b")):
        return "invalid_operand"
    overl = f.get("overlaps")
    gap = f.get("gap_mm")
    coinc = (f.get("coincident_share") or 0.0) >= 0.01 and (f.get("coincident_mm2") or 0.0) >= 0.5
    orc = f.get("oracle")
    if op == "fuse" and min_solids >= 2:
        if overl:
            return "parts_overlap"
        if gap is not None and gap <= 1e-6:
            return "parts_touch"
    if op == "fuse" and not overl and gap is not None:
        if gap > 1e-6:
            return "small_gap" if gap <= bridge else "apart"
        return "touching"
    if op == "cut" and not overl and gap is not None and gap <= 1e-6 and coinc:
        return "grazing"
    if coinc:
        return "coincident_faces" if op == "fuse" else "grazing" if op == "cut" else "coincident_faces"
    if wrong:
        return "silent_wrong"
    if op == "fuse" and orc and orc["solids"] <= lim:
        return "not_joined"
    if (not f.get("valid_a")) or (not f.get("valid_b")):
        return "invalid_operand"
    return "kernel"


def _rewrites(cls: str, f: dict, a, b, op: str, bridge: float):
    """(label, thunk) rewrites for a class, most likely first."""
    dev = f.get("coincident_dev_mm")
    gap = f.get("gap_mm") or 0.0
    out = []
    if cls in ("empty_operand", "apart", "parts_overlap", "parts_touch"):
        return out                                            # nothing to rewrite: the geometry says no
    if cls == "small_gap":
        fz = gap * 1.5 + 1e-4
        return [(f"fuzzy {VERBS[op]} closing the measured {gap:.3g} mm gap", lambda: occt(a, b, op, fz))]
    fa = fix(_copy(a)) if not f.get("valid_a") else None
    fb = fix(_copy(b)) if not f.get("valid_b") else None
    if fa is not None or fb is not None:
        ra, rb = fa or a, fb or b
        out.append(("operands repaired (ShapeFix)", lambda: _plain(ra, rb, op)))
        a, b = ra, rb
    if cls == "invalid_operand":
        out += [("fuzzy 1e-4 on the operands as they are", lambda: occt(a, b, op, 1e-4))]
        return out
    if cls == "touching":
        out += [("fuzzy 1e-4", lambda: occt(a, b, op, 1e-4)), ("glued faces", lambda: occt(a, b, op, glue="full"))]
        return out
    d = min(0.05, max(0.01, 4 * (dev or 0.0) + 0.005))      # mm a tool moves past a face it coincides with
    fz = min(0.01, max(1e-5, 3 * dev)) if dev else 1e-4
    if op == "fuse":
        # exact first: only the part of the tool outside the body, so the coincident faces are already merged
        out.append(("only the part of the tool outside the body fused (tool minus body, then fuse)",
                    lambda: _plain(a, _plain(b, a, "cut"), "fuse")))
        out.append(("fuzzy fuse 0.01 mm", lambda: occt(a, b, op, 0.01)))
        out.append((f"tool grown {d:g} mm so it overshoots the coincident face", lambda: _plain(a, grow(b, d)[0], op)))
        out.append((f"tool shrunk {d:g} mm so its face sits under the coincident one",
                    lambda: _plain(a, grow(b, -d)[0], op)))
    elif op == "cut":
        out.append((f"fuzzy cut {fz:.2g} mm (the measured deviation)", lambda: occt(a, b, op, fz)))
        out.append((f"tool grown {d:g} mm so it cuts past the face it grazes", lambda: _plain(a, grow(b, d)[0], op)))
        out.append(("fuzzy cut 0.01 mm", lambda: occt(a, b, op, 0.01)))
    else:
        out.append((f"fuzzy {VERBS[op]} {fz:.2g} mm", lambda: occt(a, b, op, fz)))
    if f.get("closed_faces_a") or f.get("closed_faces_b"):
        out.append(("closed faces split at their seams", lambda: _plain(split_closed(a), split_closed(b), op)))
    out.append(("glued faces", lambda: occt(a, b, op, glue="full")))
    return out


# ---- the engine --------------------------------------------------------------------------------------------------

def run(a, b, op: str, *, min_solids: int = 1, max_solids: int | None = None, bridge: float = 1e-3,
        must_remove: bool = True, what: str | None = None, names: tuple[str, str] = ("body", "tool"),
        params=None, budget: float | None = None, verify: str | None = None, mesh_fallback: bool = False):
    """a fuse/cut/common b, verified, with class-specific rewrites when the plain boolean fails (module docstring).

    min_solids / max_solids: the solid count the result must have (fuse default max: a's own count, so an added
    part must join it). bridge: the largest gap (mm) a fuse closes on its own (noted). must_remove: a cut whose tool
    overlaps the body but removes nothing is a failure. verify: "auto" (the oracle checks a result that changed nothing, or whose
    volume breaks a bound on free-form faces), "full" (every result), "off".
    budget: seconds for the whole ladder. mesh_fallback: when every B-rep rewrite fails, return a faceted solid made
    from the oracle mesh (labelled)."""
    op = {"intersect": "common"}.get(op, op)
    what = what or VERBS[op]
    budget = budget_s() if budget is None else float(budget)
    left = _feature_time_left()
    if left is not None:                           # inside a FeatureDesign feature: never outlast its budget
        budget = max(1.0, min(budget, left - 1.0))
    verify = verify or _verify_mode()
    params = list(params or [names[1]])
    t0 = time.perf_counter()
    lim = max_solids if max_solids is not None else max(1, _solids(a)) if op == "fuse" else 10 ** 6
    attempts: list[dict] = []
    rep = {"op": op, "what": what, "class": "", "attempts": attempts, "facts": {}, "seconds": 0.0}
    na, nb = names
    rep["min_solids"] = min_solids

    if a is None or b is None or not _solids(a) or not _solids(b):
        f = {"op": op, "solids_a": _solids(a) if a is not None else 0, "solids_b": _solids(b) if b is not None else 0}
        return _raise(rep, "empty_operand", f, names, t0, params)

    va, vb = _volume(a), _volume(b)
    orc_holder: dict = {}
    slack = {"mm3": 0.0}                                # material a fuzzy fuse adds when it closes a gap

    def get_oracle():
        if "o" not in orc_holder:
            o = oracle(a, b, op)
            if o:
                o["op"] = op
            orc_holder["o"] = o
        return orc_holder["o"]

    def check(r) -> tuple[bool, str, bool]:
        """(accept, why not, wrong-but-valid)."""
        good, why = _usable(r)
        if not good:
            return False, why, False
        n = _solids(r)
        if n < min_solids or n > lim:
            return False, (f"{n} solid{'s' if n != 1 else ''} where {min_solids if min_solids == lim else f'{min_solids} to {lim}'}"
                           " allowed" if lim < 10 ** 6 else f"{n} solids where at least {min_solids} are needed"), False
        good, why = _bounds(r, a, b, va, vb, op, slack["mm3"])
        if not good and not (_freeform(a) or _freeform(b)):
            return False, why, True
        suspicious = not good                              # free-form: the oracle decides
        # the tool reaches the body but (almost) nothing went, or nothing was added: under 1 % of the smaller
        # operand is how a grazing or coincident face fails silently; the oracle says whether that is right
        tiny = abs(_volume(r) - va) <= 0.01 * min(va, vb) + 1e-6
        if op == "cut" and must_remove and tiny and _boxes_overlap(a, b):
            suspicious = True
        if op == "fuse" and tiny and _boxes_overlap(a, b):
            suspicious = True
        if verify == "full" or suspicious:
            if verify != "off":
                o = get_oracle()
                if o:
                    agree, why = _agrees(r, a, o, b, strict=verify == "full")
                    if not agree:
                        return False, why, True
        return True, "", False

    def attempt(label, fn) -> object | None:
        t = time.perf_counter()
        try:
            r = fn()
        except RecipeError:
            raise
        except Exception as e:
            attempts.append({"label": label, "outcome": f"the kernel gave up ({type(e).__name__}: {str(e)[:80]})",
                             "seconds": round(time.perf_counter() - t, 3)})
            return None
        good, why, wrong = check(r)
        attempts.append({"label": label, "outcome": "accepted" if good else why, "wrong": wrong,
                         "seconds": round(time.perf_counter() - t, 3)})
        if good:
            _remember(_VALID, r, True, 32)
            o = orc_holder.get("o")
            txt = o.pop("borderline", None) if o else None
            if txt:
                # within half of what the oracle expects: tessellating near-coincident or thin faces can be that far
                # off, so the kernel's result is kept, and the difference is said, never hidden
                note(f"{what}: kept the kernel's result, though {txt} (mesh check, heuristic)")
                rep["borderline"] = txt
            return r
        return None

    # a boolean can raise its operands' tolerances in place (OCCT's default), which leaves the body broken for every
    # later try: pristine copies are taken first, and the pre-flight and every rewrite run on copies of them. The
    # plain boolean runs on the operands themselves, as before, so its result shares the untouched faces (and their
    # meshes) with the body it came from, and tessellating the next stage stays cheap.
    pa, pb = _copy_pair(a, b)
    r = attempt(f"plain {VERBS[op]}", lambda: _plain(a, b, op))
    if r is not None:
        rep["class"] = "ok"
        rep["seconds"] = time.perf_counter() - t0
        _LAST.clear()
        _LAST.update(rep)
        _log(rep)
        return r
    t_plain = attempts[-1]["seconds"]
    skipped = []
    if time.perf_counter() - t0 >= budget:         # the plain boolean alone used the bound: no pre-flight, no rewrite
        cls, f = "slow", {"op": op, "plain_s": round(t_plain, 2), "budget_s": budget}
        rep["class"], rep["facts"] = cls, f
        skipped = ["pre-flight", "class rewrites"]
    else:
        # pre-flight, measured
        f = measure(pa, pb, op, seconds=min(8.0, max(1.0, budget - (time.perf_counter() - t0)) / 2))
        if f.get("_oracle") and "o" not in orc_holder:
            orc_holder["o"] = f["_oracle"]
        wrong = any(x.get("wrong") for x in attempts)
        cls = classify(f, min_solids, lim, bridge, wrong)
        rep["class"], rep["facts"] = cls, f
        if cls == "small_gap":
            try:
                slack["mm3"] = 2.0 * f["gap_mm"] * min(float(a.area), float(b.area))
            except Exception:
                pass
    labels = [] if cls == "slow" else [x[0] for x in _rewrites(cls, f, pa, pb, op, bridge)]
    for i, label in enumerate(labels):
        spent = time.perf_counter() - t0
        if spent + max(0.2, 0.8 * t_plain) > budget:
            skipped.append(label)
            continue
        r = attempt(label, lambda i=i: _rewrites(cls, f, *_copy_pair(pa, pb), op, bridge)[i][1]())
        if r is not None:
            rep["seconds"] = time.perf_counter() - t0
            _LAST.clear()
            _LAST.update(rep)
            _log(rep)
            first = attempts[0]["outcome"]
            if cls == "small_gap":
                note(f"{what}: a {f['gap_mm']:.3g} mm gap between {nb} and {na} was closed (fuzzy {VERBS[op]})")
            else:
                note(f"{what}: the plain {VERBS[op]} failed ({first}; {_CLASS_WORDS.get(cls, cls)}); used {label}")
            return r
    rep["skipped"] = skipped
    if mesh_fallback and cls not in ("empty_operand", "apart", "parts_overlap", "parts_touch"):
        o = orc_holder.get("o") or get_oracle()
        if o and o.get("manifold") is not None:
            r = _faceted(o["manifold"])
            if r is not None:
                try:
                    r.label = "mesh fallback (faceted, not exact B-rep)"
                except Exception:
                    pass
                note(f"{what}: mesh fallback: every exact {VERBS[op]} failed ({_CLASS_WORDS.get(cls, cls)}); the result "
                     f"is a faceted mesh solid ({o['manifold'].num_tri()} triangles, within {o['tol']:.2g} mm of the "
                     "exact shape), not an exact B-rep")
                rep["mesh_fallback"] = True
                rep["seconds"] = time.perf_counter() - t0
                _LAST.clear()
                _LAST.update(rep)
                return r
    return _raise(rep, cls, f, names, t0, params, budget if skipped else None)


def _log(rep):
    if os.environ.get("FORM_BOOLEAN_LOG"):
        import sys
        print(f"[boolean] {rep.get('what')} {rep.get('class')} {rep.get('seconds', 0):.2f}s "
              + " | ".join(f"{x['label']}: {x['outcome'][:60]} {x['seconds']}s" for x in rep.get("attempts", [])),
              file=sys.stderr, flush=True)


def _faceted(man):
    try:
        import numpy as np
        from ..recipes.meshsolid import solid_from_triangles
        mesh = man.to_mesh()
        V = np.asarray(mesh.vert_properties)[:, :3].astype(float)
        F = np.asarray(mesh.tri_verts).astype(int)
        return solid_from_triangles([tuple(map(tuple, V[t])) for t in F])
    except Exception:
        return None


_CLASS_WORDS = {
    "empty_operand": "an operand holds no solid",
    "invalid_operand": "an operand is not a valid solid",
    "apart": "the parts do not reach each other",
    "small_gap": "a small gap between the parts",
    "touching": "the parts only touch",
    "parts_touch": "two parts that must stay separate touch",
    "parts_overlap": "two parts that must stay separate overlap",
    "coincident_faces": "coincident faces",
    "grazing": "the tool grazes a face",
    "silent_wrong": "a valid-looking wrong result",
    "not_joined": "the kernel did not join overlapping parts",
    "kernel": "the kernel could not complete it",
    "slow": "the plain boolean alone used the time bound",
}


def _n(x, unit="mm"):
    return f"{x:.3g} {unit}"


def explain(cls: str, f: dict, names: tuple[str, str], op: str, min_solids: int = 1) -> tuple[str, str]:
    """(fact sentence, hint) for a class, from the measured facts."""
    na, nb = names
    ov = f.get("overlap_mm3")
    gap = f.get("gap_mm")
    coinc = f.get("coincident_mm2") or 0.0
    dev = f.get("coincident_dev_mm")
    share = f.get("coincident_share") or 0.0
    ov_txt = f"they overlap by {ov:.3g} mm³" if ov is not None and f.get("overlaps") else (
        "they do not overlap" if f.get("overlaps") is False else "")
    if cls == "empty_operand":
        who = na if not f.get("solids_a") else nb
        return (f"{who} holds no solid (an earlier step returned nothing)",
                f"Fix the step that made {who}: it is empty before this {VERBS[op]}.")
    if cls == "invalid_operand":
        bad = [(n, f.get(f"faults_{k}") or []) for n, k in ((na, "a"), (nb, "b")) if not f.get(f"valid_{k}")]
        txt = "; ".join(f"{n} is not a valid solid" + (f" ({', '.join(fl)})" if fl else "") for n, fl in bad)
        fixed = all(f.get(f"fixed_{k}") for _n_, k in ((na, "a"), (nb, "b")) if not f.get(f"valid_{k}"))
        return (txt + ("; ShapeFix repairs it, but the repaired boolean still failed" if fixed else
                       "; ShapeFix cannot repair it"),
                f"Fix the step that made {bad[0][0]} first (it is the real culprit: check it with craft.inspect "
                f"right after it is made); this {VERBS[op]} only inherited the broken shape.")
    if cls == "apart":
        return (f"{nb} does not reach {na} ({_n(gap)} apart)",
                f"Move {nb} into {na} so they overlap by 0.2 mm or more (they are {_n(gap)} apart, so there is nothing "
                f"to join), or keep it as a separate part.")
    if cls == "small_gap":
        return (f"{nb} is {_n(gap)} from {na} and the fuzzy fuse at that gap failed too",
                f"Overlap them by 0.2 mm instead of leaving a {_n(gap)} gap.")
    if cls == "parts_touch":
        return (f"{na} and {nb} touch (0 mm gap, no overlap; about {coinc:.3g} mm² of shared face), so a fuse joins "
                f"them into one solid and they cannot stay {min_solids} solids",
                f"Keep them as separate parts instead of fusing them: put both in the stage as Compound([{na}, {nb}]) "
                f"(or an assembly), or open a gap of 0.2 mm or more where they meet if they must not touch.")
    if cls == "parts_overlap":
        return (f"{na} and {nb} overlap by {ov:.3g} mm³, so they fuse into one solid and cannot stay {min_solids} solids",
                f"Parts that must stay separate need a gap: move or trim {nb} so it clears {na} by 0.2 mm or more.")
    if cls == "touching":
        return (f"{na} and {nb} only touch (0 mm gap, no overlap{f'; about {coinc:.3g} mm² of shared face' if coinc else ''})",
                f"Sink {nb} into {na} by 0.2 mm or more so they overlap instead of meeting face to face.")
    if cls == "coincident_faces":
        return (f"{ov_txt + '; ' if ov_txt else ''}about {coinc:.3g} mm² of {nb}'s surface lies on {na}'s "
                f"({share * 100:.0f} % of the sampled points, within {_n(dev or f.get('contact_b_on_a', {}).get('tol_mm', 0.02))}), "
                "and the kernel cannot merge coincident free-form faces",
                "Give the two pieces different surfaces where they meet: overlap their regions by 0.5 mm or more instead "
                "of meeting edge to edge, make one stand 0.1 mm higher (a different band amount), or unite the pieces "
                "first and add them as one.")
    if cls == "grazing":
        return (f"{ov_txt + '; ' if ov_txt else ''}the tool's surface runs within {_n(dev or 0.02)} of the body's over "
                f"about {coinc:.3g} mm² ({share * 100:.0f} % of the sampled points): it grazes the face instead of "
                "crossing it",
                f"Make {nb} cross the face clearly: let it reach 0.2 mm or more past the surface it ends on (grow it, "
                "or build it from that surface offset by a clear amount), or move it off the face.")
    if cls == "silent_wrong":
        wrong = next((x["outcome"] for x in f.get("_attempts", []) if x.get("wrong")), "")
        return ((f"{ov_txt}; " if ov_txt else "") + (wrong or "the kernel returned a valid-looking wrong result"),
                f"Change the geometry where {na} and {nb} meet (a seam, a tangent or nearly coincident face): move "
                f"{nb} 0.2 mm or make it cross the surface clearly.")
    if cls == "slow":
        return (f"the plain {VERBS[op]} of {nb} and {na} took {f.get('plain_s', 0):.1f} s and failed, which uses the "
                f"{f.get('budget_s', 0):g} s bound, so no rewrite was tried",
                f"Make the operands cheaper to intersect: fewer faces (a coarser loft or fewer spline points), or "
                f"join a pattern's instances into one tool first and {VERBS[op]} it once.")
    if cls == "not_joined":
        return (f"{ov_txt}, so they should join, but the kernel left separate solids",
                f"Overlap {nb} with {na} more deeply (0.5 mm or more), away from seams and tangent faces.")
    return ((ov_txt + "; " if ov_txt else "") + "the kernel could not complete it",
            f"Simplify where {na} and {nb} meet: move the joint off a loft seam or a tangent face, and check both are "
            "valid solids (craft.inspect).")


def _raise(rep, cls, f, names, t0, params, budget=None):
    rep["class"] = cls
    rep["facts"] = f
    rep["seconds"] = time.perf_counter() - t0
    f["_attempts"] = rep["attempts"]
    fact, hint = explain(cls, f, names, rep["op"], rep.get("min_solids", 1))
    tried = "; ".join(f"{x['label']}: {x['outcome']}" for x in rep["attempts"])
    msg = f"{rep['what']} could not be built: {fact}."
    if tried:
        msg += f" Tried: {tried}."
    if budget is not None:
        msg += f" Stopped at the {budget:g} s time bound ({', '.join(rep.get('skipped', []))} not tried)."
    msg += f" ({rep['seconds']:.1f} s)"
    rep["message"], rep["hint"] = msg, hint
    _LAST.clear()
    _LAST.update(rep)
    _log(rep)
    raise BooleanError(msg, "", hint, params, rep)


def _public_report(rep: dict) -> dict:
    f = rep.get("facts") or {}
    keep = ("valid_a", "valid_b", "faults_a", "faults_b", "fixed_a", "fixed_b", "volume_a", "volume_b", "overlap_mm3",
            "overlaps", "gap_mm", "coincident_mm2", "coincident_dev_mm", "coincident_share", "closed_faces_a",
            "closed_faces_b")
    facts = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items() if k in keep}
    if f.get("oracle"):
        o = f["oracle"]
        facts["oracle"] = {k: round(o[k], 4) for k in ("volume", "delta", "overlap", "err") if k in o}
        facts["oracle"]["solids"] = o.get("solids")
    return {"class": rep.get("class"), "op": rep.get("op"), "facts": facts, "seconds": round(rep.get("seconds", 0), 2),
            "attempts": [{k: x[k] for k in ("label", "outcome", "seconds")} for x in rep.get("attempts", [])]}


def report_facts(rep: dict) -> list[str]:
    """The measured facts of a report as short sentences (for build_diag)."""
    f = rep.get("facts") or {}
    out = []
    if f.get("overlaps") and f.get("overlap_mm3") is not None:
        out.append(f"measured overlap {f['overlap_mm3']:.3g} mm³")
    elif f.get("overlaps") is False:
        out.append("measured overlap 0 mm³" + (f", gap {f['gap_mm']:.3g} mm" if f.get("gap_mm") is not None else ""))
    if f.get("coincident_mm2"):
        out.append(f"about {f['coincident_mm2']:.3g} mm² of coincident face"
                   + (f" (within {f['coincident_dev_mm']:.0e} mm)" if f.get("coincident_dev_mm") else ""))
    for k in ("a", "b"):
        if f.get(f"valid_{k}") is False and f.get(f"solids_{k}"):
            out.append(f"operand {k} is not a valid solid" + (f" ({', '.join(f.get(f'faults_{k}') or [])})"
                                                                 if f.get(f"faults_{k}") else ""))
    return out


def diagnose(a, b, op: str, *, min_solids: int = 1, max_solids: int | None = None, bridge: float = 1e-3,
             names: tuple[str, str] = ("body", "tool"), seconds: float = 8.0) -> dict:
    """The pre-flight and the class for a pair of operands, without running any boolean: what run() would measure
    and conclude if this boolean failed. {"class", "fact", "hint", "facts", "seconds"}."""
    op = {"intersect": "common"}.get(op, op)
    f = measure(a, b, op, seconds=seconds)
    lim = max_solids if max_solids is not None else max(1, _solids(a)) if op == "fuse" else 10 ** 6
    cls = classify(f, min_solids, lim, bridge)
    fact, hint = explain(cls, f, names, op, min_solids)
    return {"class": cls, "fact": fact, "hint": hint, "facts": _public_report({"facts": f})["facts"],
            "seconds": f.get("seconds", 0.0)}
