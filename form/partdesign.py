"""A design as a native FreeCAD PartDesign feature tree (.FCStd): editable history, not a baked solid.

    export(st, p, out=None, edit=None)  ->  the .FCStd, the script that made it, and a report of every feature

How it works:

1. The kernel builds the design once more with every hand feature watched (op `partdesign_plan`, in the worker):
   each call of form/handsketch.py (extrude, cut, revolve) and form/handfeat.py (fillet, chamfer, hole, pattern,
   shell) is recorded with the arguments it ran with, and the solid after every feature is written as a B-rep file.
   Which arguments are parameters is read from the feature's source (`v["fillet_1_r"]`: bindings()).
2. Each feature becomes PartDesign: a sketch (Sketcher geometry, its constraints and its named dimensions) and a Pad,
   Pocket, Revolution or Groove; a Fillet or Chamfer on the edges it picked; a Hole (with the ISO size and fit when
   FreeCAD's table gives the same diameter); a LinearPattern or PolarPattern of the feature it repeats; a Thickness
   for a shell. A feature written as free code is decomposed where it can be: what it added and what it cut, each
   recognised as a prism, becomes a sketch of its cap and a Pad or Pocket (the sketch is editable; its sizes are not
   bound to the parameters). What is not recognised goes in as a frozen solid (PartDesign Booleans with a tool Body).
3. The parameters go into a Spreadsheet ("Params"), one aliased cell each, and every feature size taken directly
   from a parameter is an expression on its cell, so editing the cell edits the model as the parameter does here.
4. freecadcmd runs the script (form/partdesign_fc.py after the plan). It builds the Body step by step, checks each
   step against Form Studio's solid for it, takes out a native feature that does not recompute to that solid and puts
   the step in frozen instead, and saves the .FCStd. Only features that recomputed to the expected solid in FreeCAD
   are reported editable. The report gives volume, bounding box and face count of both solids and the deviation.

FreeCAD's topological naming is still fragile: a fillet, chamfer or thickness names edges and faces (Edge12, Face3)
of the solid before it. They are found by geometry on FreeCAD's own recomputed solid, so they are right for the
exported values; after an edit that changes the topology before them, FreeCAD may attach them elsewhere or fail.

Nothing here imports OCCT at module level; op_partdesign_plan runs in the kernel worker.
"""
from __future__ import annotations

import ast
import inspect
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HAND_CALLS = {"handsketch": ("extrude", "revolve"), "handfeat": ("fillet", "chamfer", "hole", "pattern", "shell"),
              "handmore": ("sweep", "loft", "rib", "mirror", "draft", "move_face", "thicken", "boolean", "split",
                           "variable_fillet", "datum_plane", "datum_axis")}
# features PartDesign has no equivalent for: frozen (or decomposed into Pad/Pocket when the step is a prism), with why
NO_PD = {"handmore.rib": "PartDesign has no rib feature",
         "handmore.move_face": "PartDesign has no move/offset-face feature",
         "handmore.thicken": "PartDesign's Thickness hollows a solid; it does not thicken a surface",
         "handmore.boolean": "the bodies are one design's solids, not PartDesign Bodies",
         "handmore.split": "PartDesign has no split (it is Part workbench's Slice)",
         "handmore.variable_fillet": "PartDesign's Fillet has one radius; a variable radius has no equivalent",
         "handmore.datum_axis": "a datum axis changes no solid"}
TIMEOUT = 600.0
MARK = "FreeCAD PartDesign export written by Form Studio"   # the first comment line of every export script
TOPONAMING = ("FreeCAD's topological naming is still fragile: fillets, chamfers and thicknesses name edges and faces "
              "of the solid before them (Edge12, Face3). They were found by geometry on FreeCAD's own recomputed "
              "solid, so they are right for these values; after an edit that changes the topology before them FreeCAD "
              "may attach them to other edges or fail to recompute.")
FIT = {"close": "Fine", "normal": "Medium", "loose": "Coarse"}


# ---- reading the source: which arguments of a hand call are parameters ----------------------------------------------

def _sig(mod: str, fn: str):
    from . import handfeat, handmore, handsketch
    return inspect.signature(getattr({"handfeat": handfeat, "handsketch": handsketch, "handmore": handmore}[mod], fn))


def bindings(source: str) -> dict:
    """{feature id: {"call": "handfeat.fillet", "args": {argument name: parameter key}}} for every feature method that
    makes exactly one hand call, read from the source (no kernel). An argument counts only when it is v["key"]."""
    from . import featureprog
    try:
        tree = ast.parse(featureprog.strip_partial(source or ""))
    except SyntaxError:
        return {}
    c = featureprog._feature_class(tree)
    out: dict = {}
    for fn in (c.body if c else []):
        if not isinstance(fn, ast.FunctionDef) or not featureprog._is_feature(fn):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.attr in HAND_CALLS.get(n.func.value.id, ())]
        if len(calls) != 1:
            continue
        call = calls[0]
        mod, name = call.func.value.id, call.func.attr
        names = list(_sig(mod, name).parameters)
        args: dict = {}

        def key(node):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "v" \
                    and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                return node.slice.value
            return None
        for i, a in enumerate(call.args):
            if i < len(names) and key(a):
                args[names[i]] = key(a)
        for kw in call.keywords:
            if kw.arg and key(kw.value):
                args[kw.arg] = key(kw.value)
        out[fn.name] = {"call": f"{mod}.{name}", "args": args}
    return out


def alias_of(key: str) -> str:
    """A spreadsheet alias for a parameter key: FreeCAD refuses names that read as a cell (d1, ab12) or start oddly."""
    a = re.sub(r"[^A-Za-z0-9_]", "_", key)
    if not a or not a[0].isalpha() or re.fullmatch(r"[A-Za-z]{1,3}\d+", a):
        a = "p_" + a
    return a


# ---- kernel side: the build, watched -------------------------------------------------------------------------------

def _v3(v) -> list:
    return [float(v.X), float(v.Y), float(v.Z)]


def _stats(shape) -> dict:
    bb = shape.bounding_box()
    return {"volume": float(shape.volume), "faces": len(shape.faces()), "solids": len(shape.solids()),
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


def _edge_sig(e) -> dict:
    from build123d import CenterOf
    return {"c": _v3(e.center(CenterOf.MASS)), "l": float(e.length), "geom": e.geom_type.name}


def _face_sig(f) -> dict:
    from build123d import CenterOf
    return {"c": _v3(f.center(CenterOf.MASS)), "a": float(f.area)}


def _plane_dict(plane, datum=None, offset=0.0) -> dict:
    d = {"origin": _v3(plane.origin), "x": _v3(plane.x_dir), "z": _v3(plane.z_dir)}
    if datum:
        d.update(datum=datum, offset=float(offset or 0))
    return d


def _hand_sketch(data: dict, v: dict, fid: str, plane) -> dict:
    """Our sketch as Sketcher geometry and constraints, at the values it was built with. Sketcher numbers vertices
    by (geometry, position): 1 start, 2 end, 3 centre; a point shared by entities is one Coincident per extra use."""
    from . import handsketch
    from .handsketch import DIMENSIONS
    d = handsketch.check(data)
    sk, vals = handsketch.build(d, v, fid + "_")
    sol = sk.solve(vals)
    P = sol.pts
    geo, refs = [], {}
    for i, e in enumerate(d["entities"]):
        c = bool(e.get("construction"))
        ent = sk.ents[i]
        if e["k"] == "line":
            geo.append({"t": "line", "a": list(P[e["p"][0]]), "b": list(P[e["p"][1]]), "c": c})
            refs.setdefault(e["p"][0], []).append((i, 1))
            refs.setdefault(e["p"][1], []).append((i, 2))
        elif e["k"] == "circle":
            geo.append({"t": "circle", "o": list(P[e["p"][0]]), "r": sol.radius(ent), "c": c})
            refs.setdefault(e["p"][0], []).append((i, 3))
        else:
            a0, a1 = sol.arc_angles(ent)
            geo.append({"t": "arc", "o": list(P[e["p"][0]]), "r": sol.radius(ent), "a0": a0, "a1": a1, "c": c})
            refs.setdefault(e["p"][0], []).append((i, 3))
            refs.setdefault(e["p"][1], []).append((i, 1))
            refs.setdefault(e["p"][2], []).append((i, 2))
    for j in range(len(d["points"])):
        if j not in refs:
            refs[j] = [(len(geo), 1)]
            geo.append({"t": "point", "p": list(P[j]), "c": True})
    cons = []
    for j, rs in refs.items():
        for r in rs[1:]:
            cons.append({"t": "Coincident", "a": [rs[0][0], rs[0][1], r[0], r[1]]})

    def ref(j):
        return list(refs[j][0])
    for j in d["fixed"]:
        x, y = P[j]
        cons += [{"t": "DistanceX", "a": ref(j), "v": x}, {"t": "DistanceY", "a": ref(j), "v": y}]
    for c in d["constraints"]:
        k, es, ps = c["k"], c.get("e") or [], c.get("p") or []
        row = None
        if k == "coincident":
            row = {"t": "Coincident", "a": ref(ps[0]) + ref(ps[1])}
        elif k == "fix":
            for j in ps:
                x, y = P[j]
                cons += [{"t": "DistanceX", "a": ref(j), "v": x}, {"t": "DistanceY", "a": ref(j), "v": y}]
        elif k in ("horizontal", "vertical"):
            row = {"t": k.capitalize(), "a": [es[0]]}
        elif k in ("parallel", "perpendicular", "tangent", "equal"):
            row = {"t": k.capitalize(), "a": [es[0], es[1]]}
        elif k == "midpoint":
            row = {"t": "Symmetric", "a": [es[0], 1, es[0], 2] + ref(ps[0])}
        elif k == "on":
            row = {"t": "PointOnObject", "a": ref(ps[0]) + [es[0]]}
        elif k == "symmetric":
            row = {"t": "Symmetric", "a": ref(ps[0]) + ref(ps[1]) + [es[0]]}
        elif k in DIMENSIONS:
            name = c.get("name") or ""
            val = float(vals.get(name, c["value"])) if name else float(c["value"])
            if k == "length":
                row = {"t": "Distance", "a": [es[0]]}
            elif k == "radius":
                row = {"t": "Radius", "a": [es[0]]}
            elif k == "diameter":
                row = {"t": "Diameter", "a": [es[0]]}
            elif k == "angle":
                row = {"t": "Angle", "a": [es[0], es[1]], "angle": True}
            elif k == "distance":
                row = {"t": "Distance", "a": ref(ps[0]) + ([es[0]] if es else ref(ps[1]))}
            elif k == "hdist":
                row = {"t": "DistanceX", "a": ref(ps[0]) + ref(ps[1])}
            else:
                row = {"t": "DistanceY", "a": ref(ps[0]) + ref(ps[1])}
            row["v"] = val
            if name:                                    # named by its parameter key: a bare "h" or "d" reads as a unit
                row.update(name=f"{fid}_{name}", bind=f"{fid}_{name}")
        if row:
            cons.append(row)
    pl = d["plane"]
    if "datum" in pl and not isinstance(pl.get("offset"), str):
        pd = _plane_dict(plane, pl["datum"], pl.get("offset") or 0)
    else:
        pd = _plane_dict(plane)
        if pl.get("ref"):
            pd["ref"] = pl["ref"]
    return {"plane": pd, "geometry": geo, "constraints": cons}


def _sketch_axis_ref(data: dict, axis_entity: int) -> str:
    """Sketcher's name for a line of the sketch as a revolve axis: Edge<n> for profile lines, Axis<n> for
    construction lines (Sketcher counts each kind on its own, from 1 and from 0)."""
    ents = data["entities"]
    if ents[axis_entity].get("construction"):
        n = sum(1 for e in ents[:axis_entity] if e["k"] == "line" and e.get("construction"))
        return f"Axis{n}"
    n = sum(1 for e in ents[:axis_entity] if not e.get("construction"))
    return f"Edge{n + 1}"


def _hole_iso(label: str, doc: str) -> list:
    """FreeCAD Hole variants that name the ISO size this hole was made from (clearance or tapped), from the
    feature's label as form/modelling.py writes it ("M3 clearance hole") and its parameter's source."""
    m = re.match(r"^(M\d+(?:\.\d+)?) (clearance|tap-drill) hole", label or "")
    if not m:
        return []
    if m.group(2) == "clearance":
        fit = next((FIT[w] for w in FIT if (doc or "").rstrip().endswith(w)), "Medium")
        return [{"iso": {"size": m.group(1), "fit": fit}}]
    return [{"iso": {"size": m.group(1), "threaded": True}}]


# ---- prisms: a free-code step's added or cut volume, recognised as an extruded profile --------------------------------

def _normal(f):
    return f.normal_at(f.center())


def _side_ok(f, d) -> bool:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_SurfaceOfExtrusion
    s = BRepAdaptor_Surface(f.wrapped)
    t = s.GetType()
    if t == GeomAbs_Plane:
        return abs(_normal(f).dot(d)) < 1e-6
    if t == GeomAbs_Cylinder:
        a = s.Cylinder().Axis().Direction()
        return abs(abs(a.X() * d.X + a.Y() * d.Y + a.Z() * d.Z) - 1) < 1e-6
    if t == GeomAbs_SurfaceOfExtrusion:
        a = s.Direction()
        return abs(abs(a.X() * d.X + a.Y() * d.Y + a.Z() * d.Z) - 1) < 1e-6
    return False


def _cap_geometry(face, plane) -> list | None:
    """The cap's edges as sketch geometry in plane's coordinates, or None when one is not a line, circle or arc."""
    from build123d import Vector
    o, x, y = plane.origin, plane.x_dir, plane.y_dir

    def loc(p):
        r = Vector(p) - o
        return [r.dot(x), r.dot(y)]
    out = []
    for e in face.edges():
        g = e.geom_type.name
        if g == "LINE":
            out.append({"t": "line", "a": loc(e.position_at(0)), "b": loc(e.position_at(1))})
        elif g == "CIRCLE":
            c = loc(e.arc_center)
            r = float(e.radius)
            if e.is_closed:
                out.append({"t": "circle", "o": c, "r": r})
                continue
            s, m, t = loc(e.position_at(0)), loc(e.position_at(0.5)), loc(e.position_at(1))
            cross = (s[0] - c[0]) * (m[1] - c[1]) - (s[1] - c[1]) * (m[0] - c[0])
            a, b = (s, t) if cross > 0 else (t, s)
            a0 = math.atan2(a[1] - c[1], a[0] - c[0])
            a1 = math.atan2(b[1] - c[1], b[0] - c[0])
            while a1 <= a0 + 1e-9:
                a1 += 2 * math.pi
            out.append({"t": "arc", "o": c, "r": r, "a0": a0, "a1": a1})
        else:
            return None
    return out


def prism(solid, op: str) -> dict | None:
    """{"op": pad | pocket, "sketch", "length"} when the solid is a planar profile extruded straight: two opposite
    planar caps of the same area, every other face parallel to the direction, volume = area x height."""
    from build123d import Plane
    planes = [f for f in solid.faces() if f.geom_type.name == "PLANE"]
    vol = float(solid.volume)
    best = None                                          # the pair with the largest cap: the sketch a person draws
    for i, a in enumerate(planes):
        na = _normal(a)
        for b in planes[i + 1:]:
            if na.dot(_normal(b)) > -1 + 1e-7 or abs(a.area - b.area) > 1e-6 * max(a.area, 1.0):
                continue
            h = (b.center() - a.center()).dot(-na)
            if h <= 1e-6 or abs(a.area * h - vol) > 1e-5 * max(vol, 1e-9):
                continue
            if best is not None and a.area <= best[0].area:
                continue
            if not all(_side_ok(f, na) for f in solid.faces() if not (f.is_same(a) or f.is_same(b))):
                continue
            best = (a, na, h)
    if best is None:
        return None
    a, na, h = best
    z = -na if op == "pad" else na                       # a pad grows along the sketch normal, a pocket against it
    pl = Plane(origin=a.center(), z_dir=z)
    geo = _cap_geometry(a, pl)
    if geo is None:
        return None
    return {"op": op, "length": float(h), "sketch": {"plane": _plane_dict(pl), "geometry": geo, "constraints": []}}


def _decompose(before, after) -> list | None:
    """Pads for what a step added and pockets for what it cut, each a recognised prism; None when one is not."""
    parts = []
    for op, sh in (("pad", after - before if before is not None else after),
                   ("pocket", before - after if before is not None else None)):
        if sh is None:
            continue
        for s in sh.solids():
            if s.volume < 1e-6:
                continue
            got = prism(s, op)
            if got is None:
                return None
            parts.append(got)
    return parts or None


# ---- the kernel op -------------------------------------------------------------------------------------------------

def op_partdesign_plan(key, recipe_id, values, out_dir, binds=None, tol=0.05):
    """Build the design with every hand call watched; write each feature's solid as a B-rep into out_dir.
    Returns the plan form/partdesign_fc.py builds from (every number computed on the B-rep)."""
    from build123d import export_brep

    from . import featureprog, handfeat, handmore, handsketch
    from .recipes import resolve
    recipe = resolve(recipe_id)
    v = recipe.validate(values)
    binds = binds or {}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    calls: list = []
    orig = {}

    def watch(mod, name):
        fn = getattr(mod, name)
        orig[(mod, name)] = fn
        sig = inspect.signature(fn)

        def w(*a, **kw):
            res = fn(*a, **kw)
            try:
                ba = sig.bind(*a, **kw)
                ba.apply_defaults()
                calls.append({"call": f"{mod.__name__.split('.')[-1]}.{name}", "args": dict(ba.arguments), "out": res})
            except TypeError:
                pass
            return res
        setattr(mod, name, w)

    for mod, names in ((handsketch, HAND_CALLS["handsketch"]), (handfeat, HAND_CALLS["handfeat"]),
                       (handmore, HAND_CALLS["handmore"])):
        for n in names:
            watch(mod, n)
    feats: list = []                                    # (fid, before, after, calls)
    is_fd = isinstance(recipe, featureprog.FeatureDesign)
    lookup = featureprog._lookup
    featureprog._lookup = lambda *a, **k: None          # build every feature: a checkpoint would not run the call
    wrapped = []
    try:
        if is_fd:
            for fid in type(recipe)._form_steps:
                meth = getattr(recipe, fid)

                def runner(vv, body, _fid=fid, _m=meth):
                    mark = len(calls)
                    res = _m(vv, body)
                    after = res
                    if isinstance(after, (list, tuple)) and after and hasattr(after[-1], "shape"):
                        after = after[-1].shape
                    elif hasattr(after, "shape") and not hasattr(after, "volume"):
                        after = after.shape
                    feats.append((_fid, body, body if after is None else after, calls[mark:]))
                    return res
                setattr(recipe, fid, runner)
                wrapped.append(fid)
        featureprog.begin()
        stages = recipe.build(v)
    finally:
        featureprog._lookup = lookup
        for (mod, name), fn in orig.items():
            setattr(mod, name, fn)
        for fid in wrapped:
            recipe.__dict__.pop(fid, None)
    final = stages[-1].shape
    if len(final.solids()) != 1:                         # one Body per part, each its frozen solid
        parts = []
        for k, s in enumerate(final.solids(), 1):
            parts.append({"i": k - 1, "feature": f"part_{k}", "label": f"Part {k}", "kind": "frozen",
                          "brep": f"part_{k:02d}.brep", "expect": _stats(s),
                          "why": f"the design is {len(final.solids())} solids and a PartDesign Body is one: each "
                                 "part is its own Body holding its solid; its features are not rebuilt"})
            export_brep(s, str(out / parts[-1]["brep"]))
        export_brep(final, str(out / "final.brep"))
        return {"steps": [], "parts": parts, "final": _stats(final), "final_brep": "final.brep",
                "design": "parts"}
    skipped = {d.get("feature") for d in featureprog._REPORT.get("skipped") or []}
    meta = getattr(type(recipe), "_form_meta", {}) or {}
    labels = {f.id: f.label for f in getattr(recipe, "features", []) or []}
    if not is_fd:                                       # a plain Recipe: its stages, each a step of free code
        feats, prev = [], None
        for s in stages:
            feats.append((s.feature, prev, s.shape, []))
            prev = s.shape
    steps = []
    done_ids = set()
    for fid in (type(recipe)._form_steps if is_fd else [f[0] for f in feats]):
        label = labels.get(fid, fid)
        if is_fd and (meta.get(fid) or {}).get("suppressed"):
            steps.append({"i": len(steps), "feature": fid, "label": label, "kind": "suppressed"})
            continue
        rec = next((f for f in feats if f[0] == fid and id(f) not in done_ids), None)
        if rec is None or fid in skipped:
            steps.append({"i": len(steps), "feature": fid, "label": label, "kind": "skipped",
                          "why": "left out of the build in Form Studio too"})
            continue
        done_ids.add(id(rec))
        _fid, before, after, cs = rec
        if after is before:
            row = {"i": len(steps), "feature": fid, "label": label, "kind": "empty"}
            if len(cs) == 1 and cs[0]["call"] == "handmore.datum_plane":
                try:
                    row.update(_datum_step(cs[0]["args"], before, binds.get(fid) or {}))
                except Exception as e:                     # noqa: BLE001 - reported; it changes no solid
                    row["why"] = f"the datum plane could not be read ({type(e).__name__})"
            steps.append(row)
            continue
        st = {"i": len(steps), "feature": fid, "label": label, "brep": f"step_{len(steps):02d}.brep",
              "expect": _stats(after)}
        export_brep(after, str(out / st["brep"]))
        st.update(_native(fid, label, before, after, cs, binds.get(fid) or {}, recipe, v, steps))
        steps.append(st)
    export_brep(final, str(out / "final.brep"))
    return {"steps": steps, "final": _stats(final), "final_brep": "final.brep", "design": "feature" if is_fd else "recipe"}


class _NoPD(Exception):
    """A hand feature with no PartDesign equivalent: it goes in decomposed or frozen, saying why."""


PAD_TYPES = {"blind": "Length", "mid": "Length", "vertex": "Length", "face": "UpToFace", "offset": "UpToFace",
             "next": "UpToFirst"}


def _pad_plan(a, data, sk, b, args, before, trail, plane, fid) -> dict:
    """A Pad or Pocket with its end conditions (Type, Midplane, Reversed, Offset, TaperAngle, a second side)."""
    from build123d import Vector

    from . import handfeat
    if float(a.get("thin") or 0):
        raise _NoPD("a thin feature: PartDesign's Pad and Pocket have no thin wall")
    add = a.get("mode") == "add"
    depth = float(a.get("depth") or 0)
    end = a.get("end") or ""
    if not end and not a.get("end2") and not a.get("draft") and not a.get("reverse"):     # the classic form
        if add:
            return {"kind": "pad", "source": "hand", "sketch": sk, "depth": depth, "bind": b}
        return {"kind": "pocket", "source": "hand", "sketch": sk, "depth": depth, "bind": b,
                "through": depth <= 0, "midplane": depth <= 0 and "datum" in data["plane"]}
    end = end or ("blind" if depth > 0 else ("through" if not add else "blind"))
    notes = []
    b = dict(b)
    for k in ("offset", "draft", "depth2", "offset2", "draft2"):
        if args.get(k):
            b[k] = args[k]

    def side(e, dep, to, d):
        out = {"Type": ("UpToLast" if add else "ThroughAll") if e == "through" else PAD_TYPES[e]}
        if e in ("blind", "mid"):
            out["Length"] = dep
        if e == "vertex":
            out["Length"] = (Vector(*to) - plane.origin).dot(d)
            out["computed"] = True
            notes.append("up to vertex: FreeCAD holds the depth to the vertex as a length")
        if e in ("face", "offset"):
            out["face"] = _face_sig(handfeat.find_face(before, trail, to, fid))
        return out
    n = plane.z_dir * ((-1.0 if not add else 1.0) * (-1.0 if a.get("reverse") else 1.0))
    row = {"kind": "pad" if add else "pocket", "source": "hand", "sketch": sk, "bind": b, "ends": True,
           "side1": side(end, depth, a.get("to"), n), "midplane": end == "mid",
           "reversed": bool(a.get("reverse")), "offset": float(a.get("offset") or 0) if end == "offset" else 0.0,
           "taper": float(a.get("draft") or 0)}
    if a.get("end2"):
        row["side2"] = side(a["end2"], float(a.get("depth2") or 0), a.get("to2"), -n)
        row["offset2"] = float(a.get("offset2") or 0) if a["end2"] == "offset" else 0.0
        row["taper2"] = float(a.get("draft2") or 0)
    if notes:
        row["note"] = "; ".join(notes)
    # FreeCAD's signs for the taper and the offset are tried both ways; the solid decides
    row["variants"] = [{}, {"flip_taper": True}, {"flip_offset": True}, {"flip_taper": True, "flip_offset": True}]
    return row


def _plane_ref(spec, before, trail, v, what) -> dict:
    """A plane a mirror or draft names, as FreeCAD can name it: an origin plane, a datum plane feature, or a face."""
    from . import handsketch
    pl = handsketch.resolve_plane(spec, before, trail, what, v)
    out = _plane_dict(pl)
    if "datum" in spec and not float(spec.get("offset") or 0):
        out["origin_plane"] = spec["datum"]
    elif "ref" in spec:
        out["ref"] = spec["ref"]
    elif "face" in spec:
        from . import handfeat
        out["face"] = _face_sig(handfeat.find_face(before, trail, spec["face"], what))
    return out


def _datum_step(a, before, bind) -> dict:
    """A datum plane feature as a PartDesign Plane: attached to an origin plane with an offset and a turn where it
    is written that way (both bound to the spreadsheet), else placed where it is."""
    from . import handsketch
    spec = a["spec"]
    v = a.get("v") or {}
    pl = handsketch.resolve_plane(spec, before, list(a.get("trail") or []), "datum", v)
    row = {"kind": "datum_plane", "source": "hand", "plane": _plane_dict(pl)}
    if isinstance(spec.get("base"), str) and "through" not in spec:
        row["attach"] = {"datum": spec["base"], "offset": handsketch._val(spec.get("offset", 0), v),
                         "angle": handsketch._val(spec.get("angle", 0), v), "about": spec.get("about", "x"),
                         "bind_offset": spec.get("offset") if isinstance(spec.get("offset"), str) else None,
                         "bind_angle": spec.get("angle") if isinstance(spec.get("angle"), str) else None}
    return row


def _native(fid, label, before, after, cs, bind, recipe, v, steps) -> dict:
    """The PartDesign form of one step: a native feature from its one hand call, else a decomposition, else frozen."""
    from . import handfeat, handsketch
    args = (bind or {}).get("args") or {}
    one = cs[0] if len(cs) == 1 and cs[0]["args"].get("body") is before and cs[0]["out"] is after else None
    why = "free code"
    if one is not None:
        a, call = one["args"], one["call"]
        b = {k: args[n] for k, n in (("depth", "depth"), ("angle", "angle"), ("size", "radius"), ("size", "length"),
                                     ("d", "d"), ("head_d", "head_d"), ("head_depth", "head_depth"),
                                     ("count", "count"), ("step", "step"), ("thickness", "thickness")) if n in args}
        try:
            vv = a.get("v") or v
            if call in ("handsketch.extrude", "handsketch.revolve"):
                data = handsketch.check(a.get("data"))
                trail0 = list(a.get("trail") or [])
                plane = handsketch.plane_of(data, before, trail0, fid, vv)
                sk = _hand_sketch(data, vv, fid, plane)
                if a.get("mode") == "new":
                    raise _NoPD("a new body beside the first: a PartDesign Body holds one solid")
                if call == "handsketch.extrude":
                    return _pad_plan(a, data, sk, b, args, before, trail0, plane, fid)
                kind = "revolution" if a.get("mode") == "add" else "groove"
                row = {"kind": kind, "source": "hand", "sketch": sk, "angle": float(a["angle"]), "bind": b,
                       "axis_ref": _sketch_axis_ref(data, int(a["axis_entity"])),
                       "variants": [{}, {"Reversed": True}]}
                if a.get("end") == "face":
                    from . import handfeat
                    row["upto_face"] = _face_sig(handfeat.find_face(before, trail0, a["to"], fid))
                if float(a.get("angle2") or 0):
                    row["angle2"] = float(a["angle2"])
                    if args.get("angle2"):
                        b["angle2"] = args["angle2"]
                if a.get("mid"):
                    row["midplane"] = True
                if a.get("reverse"):
                    row["variants"] = [{"Reversed": True}, {}]
                return row
            if call == "handmore.sweep":
                if abs(float(a.get("twist") or 0)) > 1e-9:
                    raise _NoPD("a twisted sweep: PartDesign's Pipe has no twist")
                if a.get("mode") == "new":
                    raise _NoPD("a new body beside the first: a PartDesign Body holds one solid")
                pd = handsketch.check(a["profile"])
                trail0 = list(a.get("trail") or [])
                prof = _hand_sketch(pd, vv, fid, handsketch.plane_of(pd, before, trail0, fid, vv))
                row = {"kind": "pipe", "source": "hand", "cut": a.get("mode") == "cut", "sketch": prof, "bind": b,
                       "frenet": bool(a.get("frenet")), "variants": [{"Transition": "Right corner"}, {}]}
                path = a["path"]
                if isinstance(path, dict) and "edges" in path:
                    from . import handfeat
                    row["spine_edges"] = [_edge_sig(e) for e in handfeat.find_edges(before, trail0, path["edges"], fid)]
                else:
                    pdd = handsketch.check(path)
                    row["spine"] = _hand_sketch(pdd, vv, fid + "_path", handsketch.plane_of(pdd, before, trail0, fid, vv))
                return row
            if call == "handmore.loft":
                if a.get("mode") == "new":
                    raise _NoPD("a new body beside the first: a PartDesign Body holds one solid")
                trail0 = list(a.get("trail") or [])
                secs = []
                for i, sd in enumerate(a["sections"], 1):
                    d = handsketch.check(sd)
                    secs.append(_hand_sketch(d, vv, f"{fid}_s{i}", handsketch.plane_of(d, before, trail0, fid, vv)))
                return {"kind": "loft", "source": "hand", "cut": a.get("mode") == "cut", "sections": secs,
                        "ruled": bool(a.get("ruled")), "bind": b, "variants": [{}]}
            if call == "handmore.mirror":
                of = a.get("of")
                return {"kind": "mirrored", "source": "hand", "of": ([of] if isinstance(of, str) else list(of or [])),
                        "plane": _plane_ref(a["plane"], before, list(a.get("trail") or []), vv, fid), "bind": b,
                        "variants": [{}]}
            if call == "handmore.draft":
                from . import handfeat
                trail0 = list(a.get("trail") or [])
                faces = [handfeat.find_face(before, trail0, q, fid) for q in a["faces"]]
                if args.get("angle"):
                    b["angle"] = args["angle"]
                return {"kind": "draft", "source": "hand", "angle": float(a["angle"]),
                        "faces": [_face_sig(f) for f in faces],
                        "plane": _plane_ref(a["neutral"], before, trail0, vv, fid), "flip": bool(a.get("flip")),
                        "bind": b, "variants": [{}, {"Reversed": True}]}
            if call in NO_PD:
                raise _NoPD(NO_PD[call])
            trail = list(a.get("trail") or [])
            if call in ("handfeat.fillet", "handfeat.chamfer"):
                edges = handfeat.find_edges(before, trail, a["edges"], fid)
                return {"kind": call.split(".")[1], "source": "hand", "size": float(a.get("radius") or a.get("length")),
                        "edges": [_edge_sig(e) for e in edges], "bind": b}
            if call == "handfeat.hole":
                from build123d import Plane, Vector
                f = handfeat.find_face(before, trail, a["face"], fid)
                n = Vector(*handfeat._vec(f.normal_at(f.center()))).normalized()
                p = Vector(*a["at"])
                p = p - n * ((p - f.center()).dot(n))
                pl = Plane(origin=p, z_dir=n)
                doc = ""
                if b.get("d"):
                    try:
                        doc = recipe.spec(b["d"]).doc
                    except Exception:
                        doc = ""
                return {"kind": "hole", "source": "hand", "origin": _v3(p), "normal": _v3(n), "x": _v3(pl.x_dir),
                        "d": float(a["d"]), "depth": float(a.get("depth") or 0), "style": a.get("style") or "plain",
                        "head_d": float(a.get("head_d") or 0), "head_depth": float(a.get("head_depth") or 0),
                        "bind": b, "variants": _hole_iso(label, doc) + [{}]}
            if call == "handfeat.pattern":
                kind = "linear_pattern" if a["kind"] == "linear" else "polar_pattern"
                return {"kind": kind, "source": "hand", "of": a["of"], "count": int(round(a["count"])),
                        "step": float(a["step"]), "axis": [float(x) for x in a["axis"]],
                        "origin": [float(x) for x in (a.get("origin") or (0, 0, 0))], "bind": b,
                        "variants": [{}, {"Reversed": "flip"}]}
            if call == "handfeat.shell":
                if not a.get("open_face"):
                    why = "a closed shell (no open face): PartDesign Thickness needs a face to remove"
                else:
                    f = handfeat.find_face(before, trail, a["open_face"], fid)
                    return {"kind": "thickness", "source": "hand", "thickness": float(a["thickness"]),
                            "faces": [_face_sig(f)], "bind": b,
                            "variants": [{"Join": "Arc"}, {"Join": "Arc", "Reversed": True}, {"Join": "Intersection"},
                                         {"Join": "Intersection", "Reversed": True}]}
        except _NoPD as e:
            why = str(e)
        except Exception as e:                           # noqa: BLE001 - reported, the step goes in another way
            why = f"its {call} could not be read ({type(e).__name__}: {str(e)[:160]})"
    elif len(cs) > 1:
        why = f"{len(cs)} hand calls in one feature"
    try:
        parts = _decompose(before, after)
    except Exception:                                    # noqa: BLE001
        parts = None
    if parts:
        return {"kind": "prism", "source": "code", "parts": parts,
                "note": f"{why}: decomposed into {len(parts)} sketch-based Pad/Pocket feature(s); their sizes are "
                        "not bound to the parameters"}
    return {"kind": "frozen", "source": "code" if one is None else "hand",
            "why": f"{why}; not recognised as a sketch and a Pad or Pocket, so it is a frozen solid"}


KERNEL_OPS = {"partdesign_plan": op_partdesign_plan}


# ---- the script and the run ----------------------------------------------------------------------------------------

RUNNER = Path(__file__).with_name("partdesign_fc.py")


def script_text(plan: dict, title: str = "") -> str:
    """The FreeCAD script: a header, the plan, the runner. Run it with FreeCAD (freecadcmd script.py, or the macro
    editor): it writes plan["fcstd"] next to itself and prints one tagged JSON line."""
    head = ("# -*- coding: utf-8 -*-\n"
            f"# {MARK}{(' for ' + title) if title else ''}.\n"
            "# Run it with FreeCAD (freecadcmd this.py): it builds the feature tree, checks every feature against the\n"
            "# solid Form Studio built (the .brep files in the folder next to it) and saves the .FCStd it names.\n")
    body = RUNNER.read_text(encoding="utf-8")
    body = body.split('"""', 2)[2]                       # the runner without its module docstring
    return head + "\ntrue, false, null = True, False, None    # the plan is JSON\nPLAN = " + json.dumps(plan, indent=1) + "\n" + body + "\n\nmain(PLAN, PLAN.get('edit'))\n"


def parse(text: str) -> dict:
    from .partdesign_fc import TAG
    for line in reversed((text or "").splitlines()):
        i = line.find(TAG)
        if i >= 0:
            try:
                return json.loads(line[i + len(TAG):])
            except ValueError:
                break
    return {"ok": False, "error": "FreeCAD did not report a result. Last output: " +
            " ".join((text or "").strip().splitlines()[-4:])[:400]}


def run_freecad(exe: str, script: Path, timeout: float = TIMEOUT) -> dict:
    """freecadcmd on the script, with a FreeCAD settings folder of its own (the person's FreeCAD settings are not
    read or written)."""
    home = tempfile.mkdtemp(prefix="form-fc-home-")
    try:
        r = subprocess.run([exe, str(script)], capture_output=True, text=True, timeout=timeout, cwd=str(script.parent),
                           stdin=subprocess.DEVNULL, env=dict(os.environ, FREECAD_USER_HOME=home))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"FreeCAD did not finish within {timeout:g} s."}
    except OSError as e:
        return {"ok": False, "error": f"FreeCAD could not start: {e}"}
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return parse((r.stdout or "") + "\n" + (r.stderr or ""))


def _pct(a, b) -> float:
    return round(100.0 * abs(a - b) / max(abs(b), 1e-9), 6)


def parity(ours: dict, theirs: dict | None) -> dict:
    if not theirs:
        return {}
    db = max(abs(x - y) for lo_hi in zip(theirs["bbox"], ours["bbox"]) for x, y in zip(*lo_hi))
    return {"volume_mm3": {"form": round(ours["volume"], 4), "freecad": round(theirs["volume"], 4),
                           "deviation_pct": _pct(theirs["volume"], ours["volume"])},
            "bbox_mm": {"form": ours["bbox"], "freecad": theirs["bbox"], "max_deviation_mm": round(db, 6)},
            "faces": {"form": ours["faces"], "freecad": theirs["faces"]},
            "valid_in_freecad": theirs.get("valid")}


EDITABLE = {"native", "decomposed"}


def summarise(plan: dict, res: dict, params: list) -> dict:
    rows, editable, frozen = [], [], []
    by = {r["i"]: r for r in res.get("steps") or []}
    for st in plan["steps"] or plan.get("parts") or []:
        r = by.get(st["i"], {})
        status = r.get("status") or ("not run" if not res.get("ok") else st["kind"])
        row = {"feature": st["feature"], "label": st.get("label", ""), "planned": st["kind"], "status": status,
               "editable": status in EDITABLE}
        for k in ("objects", "bound", "dev", "tried", "error", "iso"):
            if r.get(k) not in (None, [], ""):
                row[k] = round(r[k], 8) if k == "dev" else r[k]
        if st.get("why"):
            row["why"] = st["why"]
        if st.get("note"):
            row["note"] = st["note"]
        if status in EDITABLE and res.get("restart_at") is not None and st["i"] < res["restart_at"]:
            status = row["status"] = "superseded"
            row["editable"] = False
            row["note"] = "in the file, but a later step starts a new Body from its own solid: it no longer drives the part"
        if status in EDITABLE:
            editable.append(st["feature"])
        elif status in ("frozen", "failed", "superseded"):
            frozen.append(st["feature"])
        rows.append(row)
    bound = sorted(set(res.get("bound") or []))
    return {"features": rows, "editable": editable, "non_parametric": frozen,
            "params_bound": bound, "params_in_sheet_only": sorted(p["key"] for p in params if p["key"] not in bound)}


def export(st, p: dict, out: str | os.PathLike | None = None, edit: dict | None = None,
           timeout: float = TIMEOUT) -> dict:
    """Write <out>.FCStd (a PartDesign Body with a Params spreadsheet), the script that made it and its step solids,
    built and checked in FreeCAD. edit: {parameter key: value} also opens the file, sets those cells, recomputes and
    reports what FreeCAD makes of it, next to Form Studio's own build at those values."""
    from . import cad_bridges, edits
    from .studio import StudioError
    exe = cad_bridges.freecad(st.cfg)
    if not exe:
        from . import use
        raise StudioError("FreeCAD's command line (freecadcmd) is not available." if use.on("freecad", st.cfg)
                          else use.off_reason("freecad"),
                          "Install FreeCAD from https://www.freecad.org/downloads.php (1.0 or newer), or set [cad] "
                          "freecad in studio.toml.", status=409)
    rev = st.rev(p)
    try:
        c = edits.canonical(st, p)
        rid, src = c["rid"], c["source"]
    except Exception:                                     # noqa: BLE001 - a built-in block or OpenSCAD design
        rid, src = st.rid(p), st.source_text(p) or ""
    from .recipes import SCAD_PREFIX
    if rid.startswith(SCAD_PREFIX):
        raise StudioError("This is a mesh design (OpenSCAD): there is no B-rep to rebuild as PartDesign.",
                          "Open its STL in FreeCAD's Mesh workbench instead.", status=409)
    vals = rev["values"]
    name = f"{p['id']}_r{rev['n']:02d}"
    if out:
        target = Path(out).expanduser()
        if target.suffix.lower() != ".fcstd":
            target = target / f"{name}.FCStd" if (target.is_dir() or not target.suffix) else target.with_suffix(".FCStd")
    else:
        target = st.dir(p["id"]) / "partdesign" / f"{name}.FCStd"
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    steps_dir = target.parent / f"{target.stem}_steps"
    script = target.with_suffix(".py")
    if script.exists() and MARK not in script.read_text(encoding="utf-8", errors="replace")[:400]:
        raise StudioError(f"{script.name} exists and is not a script this export wrote; it is left as it is.",
                          "Choose another file name or folder for the export.", status=409)
    if steps_dir.exists():
        if any(f.is_dir() or f.suffix != ".brep" for f in steps_dir.iterdir()):
            raise StudioError(f"{steps_dir.name} holds files this export did not write; it is left as it is.",
                              "Choose another file name or folder for the export.", status=409)
        shutil.rmtree(steps_dir)
    plan = st._k("partdesign_plan", key=st.geometry_key(p, rid, vals), recipe_id=rid, values=vals,
                 out_dir=str(steps_dir), binds=bindings(src), p=p)
    recipe = st.recipe(p)
    params = []
    for k, val in vals.items():
        try:
            sp = recipe.spec(k)
            label, unit, lo, hi = sp.label, sp.unit, sp.min, sp.max
        except Exception:                                 # noqa: BLE001
            label, unit, lo, hi = k, "", None, None
        params.append({"key": k, "alias": alias_of(k), "label": label, "value": float(val), "unit": unit,
                       "source": rev.get("provenance", {}).get(k, {}).get("source", "assumed"), "min": lo, "max": hi})
    plan = {**plan, "doc": re.sub(r"[^A-Za-z0-9_]", "_", p["name"])[:40] or "FormStudio", "label": p["name"],
            "params": params, "fcstd": target.name, "here": "", "steps_dir": steps_dir.name}
    # the B-rep files sit in the steps folder: the plan names them relative to it
    for s in plan["steps"] + (plan.get("parts") or []):
        if s.get("brep"):
            s["brep"] = f"{steps_dir.name}/{s['brep']}"
    plan["final_brep"] = f"{steps_dir.name}/{plan['final_brep']}"
    if edit:
        unknown = [k for k in edit if k not in vals]
        if unknown:
            raise StudioError(f"No parameter {', '.join(unknown)}.", "Parameters: " + ", ".join(vals) + ".")
        plan["edit"] = {alias_of(k): float(x) for k, x in edit.items()}
    script.write_text(script_text(plan, p["name"]), encoding="utf-8")
    res = run_freecad(exe, script, timeout)
    if not res.get("ok"):
        from . import compat
        why = compat.wrap_message("freecad", cad_bridges.version(exe), res.get("error", ""), res.get("trace", ""))
        raise StudioError("FreeCAD could not build the PartDesign tree: " + (f"{why[0]} {why[1]}" if why else
                          res.get("error", "")), "The script is kept next to the file: " + str(script), status=422)
    summary = summarise(plan, res, params)
    out_rep = {"fcstd": str(target), "script": str(script), "steps_dir": str(steps_dir),
               "freecad": res.get("version"), "revision": rev["n"], **summary,
               "parity": parity(plan["final"], res.get("freecad")),
               "final_deviation": round(res.get("final_dev", 1.0), 8) if res.get("final_dev") is not None else None,
               "notes": res.get("notes") or [], "toponaming": TOPONAMING,
               "evidence": "computed: built and recomputed in FreeCAD " + str(res.get("version")) + ", compared with "
                           "Form Studio's B-rep (volume, bounding box, face count, symmetric difference per feature)"}
    if res.get("invalid"):
        out_rep["invalid_in_freecad"] = res["invalid"]
    if edit:
        theirs = (res.get("edit") or {}).get("freecad")
        new = {**vals, **{k: float(x) for k, x in edit.items()}}
        try:
            mine = st._k("partdesign_solid", key=st.geometry_key(p, rid, new), recipe_id=rid, values=new, p=p)
        except Exception as e:                            # noqa: BLE001
            mine = None
            out_rep["edit_note"] = f"Form Studio did not build these values: {e}"
        out_rep["edit"] = {"values": edit, "freecad": theirs, "invalid": (res.get("edit") or {}).get("invalid"),
                           **({"parity": parity(mine, theirs)} if mine and theirs else {}), "saved": False,
                           "note": "The edit was made on a copy in memory; the saved file keeps the exported values."}
    return out_rep


def op_partdesign_solid(key, recipe_id, values, tol=0.05):
    """Volume, bounding box and face count of the design at these values (for the edit check)."""
    from . import kernel
    return _stats(kernel._brep(key, recipe_id, values)["shape"])


KERNEL_OPS["partdesign_solid"] = op_partdesign_solid


# ---- the command line: form export fcstd <project> ----------------------------------------------------------------

def main(argv=None) -> int:
    """form export fcstd <project> [--out PATH] [--edit key=value ...]: prints the report as JSON."""
    import argparse

    from . import config
    from .studio import Studio, StudioError
    ap = argparse.ArgumentParser(prog="form export fcstd",
                                 description="The design as a FreeCAD PartDesign feature tree (.FCStd), built and "
                                             "checked in FreeCAD's command line.")
    ap.add_argument("project")
    ap.add_argument("--out", help="the .FCStd to write, or a folder (default: <project folder>/partdesign/)")
    ap.add_argument("--edit", nargs="*", default=[], metavar="KEY=VALUE",
                    help="also set these spreadsheet cells in FreeCAD, recompute and compare with Form Studio's build")
    a = ap.parse_args(argv)
    edit = {}
    for kv in a.edit:
        k, sep, v = kv.partition("=")
        try:
            edit[k] = float(v)
        except ValueError:
            sep = ""
        if not sep:
            print(json.dumps({"error": {"message": f"--edit takes key=value, not {kv!r}"}}))
            return 2
    st = Studio(config.load())
    try:
        print(json.dumps(export(st, st.load(a.project), a.out, edit or None), indent=1, ensure_ascii=False, default=str))
        return 0
    except StudioError as e:
        print(json.dumps({"error": e.public()}, ensure_ascii=False))
        return 2
    finally:
        st.kernel.stop()
