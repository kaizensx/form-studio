"""Sketches drawn by hand: plain data that form.sketch2d solves, and the extrude, cut or revolve built from them.

A sketch lives inside the feature that uses it, as a literal the person, the app and the agent all edit
(form/modelling.py writes it; edit_sketch changes it with ops):

    @feature("Extrude 1", role="structure")
    def extrude_1(self, v, body):
        from form import handsketch
        sketch = {"plane": {"datum": "XY", "offset": 0},
                  "points": [[0, 0], [60, 0], [60, 40], [0, 40]], "fixed": [0],
                  "entities": [{"k": "line", "p": [0, 1]}, ...],
                  "constraints": [{"k": "horizontal", "e": [0]}, {"k": "length", "e": [0], "value": 60,
                                   "name": "w", "label": "Width"}, ...]}
        return handsketch.extrude(body, self._form_trail, sketch, v, "extrude_1", v["extrude_1_depth"], "add")

A named dimension is a parameter of the design, keyed "<feature>_<name>" (changing it is a parameter change, and the
sketch re-solves with its intent kept); an unnamed one is fixed. Points are where they were drawn; the solver moves
them to satisfy the constraints. The plane is a datum (XY, XZ or YZ with an offset) or a picked flat face (a stable
query as form/handfeat.py keeps them, an origin and the sketch's x and y directions): the face is found again on
each rebuild and the origin follows its plane.

Entities: line (two points), circle (centre point, r), arc (centre, start, end; counter-clockwise). Constraints:
coincident, horizontal, vertical, parallel, perpendicular, tangent, equal, midpoint, on, symmetric (two points about a
line), fix, and the dimensions length, distance, hdist, vdist, radius, diameter, angle.

Everything here but the build functions is plain Python (the solver is numpy), so the app and the MCP server solve
a sketch without the kernel.
"""
from __future__ import annotations

import copy
import math

from .recipes.base import RecipeError
from .sketch2d import Sketch, SketchError

ENTITIES = ("line", "circle", "arc")
GEOMETRIC = ("coincident", "horizontal", "vertical", "parallel", "perpendicular", "tangent", "equal", "midpoint",
             "on", "symmetric", "fix")
DIMENSIONS = ("length", "distance", "hdist", "vdist", "radius", "diameter", "angle")
DATUMS = {"XY": ((1, 0, 0), (0, 1, 0), (0, 0, 1)), "XZ": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
          "YZ": ((0, 1, 0), (0, 0, 1), (1, 0, 0))}          # x, y and normal of each datum plane


def _bad(msg: str, hint: str = "") -> SketchError:
    return SketchError(msg, "sketch", hint)


def empty(plane: dict | None = None) -> dict:
    return {"plane": plane or {"datum": "XY", "offset": 0}, "points": [], "fixed": [], "entities": [], "constraints": []}


def check(data) -> dict:
    """The sketch data, checked: every index in range, every kind known. Raises SketchError saying what is wrong."""
    if not isinstance(data, dict):
        raise _bad("A sketch is an object: {plane, points, entities, constraints}.")
    d = {"plane": data.get("plane") or {"datum": "XY", "offset": 0}, "points": data.get("points") or [],
         "fixed": data.get("fixed") or [], "entities": data.get("entities") or [], "constraints": data.get("constraints") or []}
    pl = d["plane"]
    if "datum" in pl and pl["datum"] not in DATUMS:
        raise _bad(f"Unknown datum plane {pl['datum']!r}.", "XY, XZ or YZ.")
    if not any(k in pl for k in ("datum", "face", "ref", "base", "through")):
        raise _bad("The plane is a datum (XY, XZ, YZ), a picked face or a datum plane.")
    n = len(d["points"])
    for i, p in enumerate(d["points"]):
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in p)):
            raise _bad(f"Point {i} is not two numbers.")
    for i in d["fixed"]:
        if not (isinstance(i, int) and 0 <= i < n):
            raise _bad(f"Fixed point {i} does not exist.")
    for i, e in enumerate(d["entities"]):
        if not isinstance(e, dict) or e.get("k") not in ENTITIES:
            raise _bad(f"Entity {i} is not a line, circle or arc.")
        want = {"line": 2, "circle": 1, "arc": 3}[e["k"]]
        ps = e.get("p") or []
        if len(ps) != want or not all(isinstance(j, int) and 0 <= j < n for j in ps):
            raise _bad(f"Entity {i} ({e['k']}) needs {want} existing point(s).")
        if e["k"] == "circle" and not (isinstance(e.get("r"), (int, float)) and e["r"] > 0):
            raise _bad(f"Circle {i} needs a radius above 0.")
    names = set()
    for i, c in enumerate(d["constraints"]):
        k = c.get("k") if isinstance(c, dict) else None
        if k not in GEOMETRIC + DIMENSIONS:
            raise _bad(f"Constraint {i} has an unknown kind {k!r}.", "Kinds: " + ", ".join(GEOMETRIC + DIMENSIONS) + ".")
        for j in c.get("e") or []:
            if not (isinstance(j, int) and 0 <= j < len(d["entities"])):
                raise _bad(f"Constraint {i} ({k}) names entity {j}, which does not exist.")
        for j in c.get("p") or []:
            if not (isinstance(j, int) and 0 <= j < n):
                raise _bad(f"Constraint {i} ({k}) names point {j}, which does not exist.")
        if k in DIMENSIONS:
            if not isinstance(c.get("value"), (int, float)):
                raise _bad(f"Dimension {i} ({k}) needs a value.")
            if c.get("name"):
                if not isinstance(c["name"], str) or not c["name"].replace("_", "").isalnum() or c["name"] in names:
                    raise _bad(f"Dimension {i}: the name {c.get('name')!r} is not usable or used twice.")
                names.add(c["name"])
    return d


def build(data: dict, values: dict | None = None, prefix: str = "") -> tuple[Sketch, dict]:
    """(a form.sketch2d Sketch of the data, the values it solves for: {dimension name: value})."""
    d = check(data)
    sk = Sketch(prefix.rstrip("_") or "sketch")
    P = [sk.point(x, y, fix=i in d["fixed"]) for i, (x, y) in enumerate(d["points"])]
    E = []
    for e in d["entities"]:
        c = bool(e.get("construction"))
        if e["k"] == "line":
            E.append(sk.line(P[e["p"][0]], P[e["p"][1]], construction=c))
        elif e["k"] == "circle":
            E.append(sk.circle(P[e["p"][0]], float(e["r"]), construction=c))
        else:
            E.append(sk.arc(P[e["p"][0]], P[e["p"][1]], P[e["p"][2]], construction=c))
    vals = {}
    for c in d["constraints"]:
        k, es, ps = c["k"], [E[j] for j in c.get("e") or []], [P[j] for j in c.get("p") or []]
        try:
            if k in DIMENSIONS:
                name = c.get("name") or ""
                v = float(c["value"])
                if name and values is not None and (prefix + name) in values:
                    v = float(values[prefix + name])
                kw = dict(name=name, label=c.get("label", ""), lo=c.get("lo"), hi=c.get("hi"))
                if k == "length":
                    sk.length(es[0], c["value"], **kw)
                elif k == "radius":
                    sk.radius(es[0], c["value"], **kw)
                elif k == "diameter":
                    sk.diameter(es[0], c["value"], **kw)
                elif k == "angle":
                    sk.angle(es[0], es[1], c["value"], **kw)
                elif k == "distance":
                    sk.distance(ps[0], es[0] if es else ps[1], c["value"], **kw)
                elif k == "hdist":
                    sk.hdist(ps[0], ps[1], c["value"], **kw)
                else:
                    sk.vdist(ps[0], ps[1], c["value"], **kw)
                if name:
                    vals[name] = v
            elif k == "coincident":
                sk.coincident(ps[0], ps[1])
            elif k == "fix":
                sk.fix(ps[0])
            elif k in ("horizontal", "vertical"):
                getattr(sk, k)(es[0])
            elif k in ("parallel", "perpendicular", "tangent", "equal"):
                getattr(sk, k)(es[0], es[1])
            elif k == "midpoint":
                sk.midpoint(ps[0], es[0])
            elif k == "on":
                sk.on(ps[0], es[0])
            else:
                sk.symmetric(ps[0], ps[1], es[0])
        except (IndexError, TypeError):
            raise _bad(f"The {k} constraint names the wrong entities or points.")
    return sk, vals


def solve(data: dict, values: dict | None = None, prefix: str = "") -> dict:
    """The sketch solved: points where the constraints put them, the profile, degrees of freedom left, the dimensions.
    {"ok", "points", "edges", "dof", "fully_constrained", "dims", "closed", "solve_ms"} or {"ok": False, "error"}."""
    try:
        sk, vals = build(data, values, prefix)
        if not sk.points:
            return {"ok": True, "points": [], "edges": [], "dof": 0, "fully_constrained": False, "dims": [],
                    "closed": False, "solve_ms": 0.0, "loops": 0}
        sol = sk.solve(vals)
        rep = sk.report(vals)
    except SketchError as e:
        return {"ok": False, "error": str(e), "hint": e.hint}
    dims = [{"name": c.get("name", ""), "kind": c["k"], "value": vals.get(c.get("name"), c["value"]),
             "label": c.get("label") or (c.get("name") or c["k"]).replace("_", " ").capitalize(), "index": i}
            for i, c in enumerate(check(data)["constraints"]) if c["k"] in DIMENSIONS]
    from .sketch2d import _loops
    edges = sk.edges2d(vals)
    try:
        loops = _loops(edges) if edges else []
        closed = bool(loops) and all(_closed(lp) for lp in loops)
        why = ""
    except SketchError as e:                       # an end that meets nothing: drawn, not closed yet
        loops, closed, why = [], False, str(e)
    out = {"ok": True, "points": [list(map(lambda t: round(t, 6), p)) for p in sol.pts], "edges": edges,
           "dof": rep["dof"], "fully_constrained": rep["fully_constrained"], "dims": dims,
           "closed": closed, "loops": len(loops), "solve_ms": rep["solve_ms"]}
    if why:
        out["open"] = why
    if closed:                                      # the closed loops as points (arcs sampled), for whoever draws the profile
        out["polygons"] = [[[round(x, 5), round(y, 5)] for x, y in lp] for lp in sk.polygons(vals)]
    return out


def _closed(loop) -> bool:
    from .sketch2d import _ends
    if len(loop) == 1 and loop[0]["kind"] == "circle":
        return True
    a, _ = _ends(loop[0])
    _, b = _ends(loop[-1])
    return math.dist(a, b) < 1e-5


def params(data: dict, fid: str) -> list[dict]:
    """The sketch's named dimensions as parameter declarations (for edit ops), keyed "<fid>_<name>"."""
    out = []
    for c in check(data)["constraints"]:
        if c["k"] in DIMENSIONS and c.get("name"):
            v = float(c["value"])
            ang = c["k"] == "angle"
            lo = c.get("lo", max(0.0, v - 45) if ang else round(v * 0.25, 3))
            hi = c.get("hi", min(180.0, v + 45) if ang else round(max(v * 4, v + 10), 3))
            out.append({"key": f"{fid}_{c['name']}", "label": c.get("label") or c["name"].replace("_", " ").capitalize(),
                        "default": round(v, 4), "min": round(lo, 4), "max": round(hi, 4), "step": 0.5 if ang else 0.1,
                        "unit": "°" if ang else "mm", "group": "form", "feature": fid,
                        "doc": f"a driving dimension of the sketch of {fid}"})
    return out


def _py(x) -> str:
    """A value as Python source, laid out as json.dumps lays it out (True, False and None, not JSON's words: a
    construction line wrote "construction": true, which the design then could not run)."""
    import json
    if isinstance(x, bool) or x is None:
        return repr(x)
    if isinstance(x, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))}: {_py(v)}" for k, v in x.items()) + "}"
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(_py(v) for v in x) + "]"
    return json.dumps(x)


def literal(data: dict, indent: str = "        ") -> str:
    """The sketch as a Python literal laid out one list per line (what the feature method holds)."""
    d = check(data)
    rows = []
    for k in ("plane", "points", "fixed", "entities", "constraints"):
        if k in ("entities", "constraints") and d[k]:
            inner = (",\n" + indent + "    ").join(_py(x) for x in d[k])
            rows.append(f'"{k}": [\n{indent}    {inner}]')
        else:
            rows.append(f'"{k}": {_py(d[k])}')
    return "{" + (",\n" + indent).join(rows) + "}"


# ---- ops on a sketch (edit_sketch) --------------------------------------------------------------------------------

SKETCH_OPS = ("add_point", "add_line", "add_polyline", "add_rect", "add_circle", "add_arc", "constrain", "dimension",
              "set", "move", "delete", "construction", "plane")


def _pt_index(d, ref, made: list) -> int:
    """A point reference: an index, or [x, y] (an existing point within 1e-6 is reused, else one is added)."""
    if isinstance(ref, int):
        if not 0 <= ref < len(d["points"]):
            raise _bad(f"There is no point {ref}.")
        return ref
    try:
        x, y = float(ref[0]), float(ref[1])
    except (TypeError, ValueError, IndexError):
        raise _bad("A point is an index or [x, y].")
    for i, (px, py) in enumerate(d["points"]):
        if abs(px - x) < 1e-6 and abs(py - y) < 1e-6:
            return i
    d["points"].append([x, y])
    made.append(len(d["points"]) - 1)
    return len(d["points"]) - 1


def _auto_hv(d, ei, tol_deg: float = 2.0):
    """A line drawn within tol_deg of horizontal or vertical gets that constraint (what a sketch pad does)."""
    a, b = (d["points"][j] for j in d["entities"][ei]["p"])
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
    if min(ang, 180 - ang) <= tol_deg:
        d["constraints"].append({"k": "horizontal", "e": [ei]})
    elif abs(ang - 90) <= tol_deg:
        d["constraints"].append({"k": "vertical", "e": [ei]})


def _free_name(d, base: str) -> str:
    used = {c.get("name") for c in d["constraints"]}
    n = 1
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"


def apply_ops(data: dict, ops: list) -> tuple[dict, list]:
    """The sketch after the ops, and what each op made. Raises SketchError naming the op that cannot be applied."""
    d = copy.deepcopy(check(data))
    made_all = []
    for n, op in enumerate(ops or [], 1):
        k = op.get("op") if isinstance(op, dict) else None
        made: list = []
        try:
            if k not in SKETCH_OPS:
                raise _bad(f"unknown sketch op {k!r}", "Ops: " + ", ".join(SKETCH_OPS) + ".")
            if k == "add_point":
                _pt_index(d, op["at"], made)
            elif k in ("add_line", "add_polyline"):
                pts = op.get("points") or [op.get("from"), op.get("to")]
                idx = [_pt_index(d, p, made) for p in pts]
                if op.get("close"):
                    idx.append(idx[0])
                for a, b in zip(idx, idx[1:]):
                    d["entities"].append({"k": "line", "p": [a, b]})
                    made.append(("entity", len(d["entities"]) - 1))
                    if op.get("auto", True):
                        _auto_hv(d, len(d["entities"]) - 1)
            elif k == "add_rect":
                x, y = (float(t) for t in op["at"])
                w, h = (float(t) for t in op["size"])
                idx = [_pt_index(d, p, made) for p in ([x, y], [x + w, y], [x + w, y + h], [x, y + h])]
                base = len(d["entities"])
                for a, b in zip(idx, idx[1:] + idx[:1]):
                    d["entities"].append({"k": "line", "p": [a, b]})
                d["constraints"] += [{"k": "horizontal", "e": [base]}, {"k": "vertical", "e": [base + 1]},
                                     {"k": "horizontal", "e": [base + 2]}, {"k": "vertical", "e": [base + 3]}]
                made += [("entity", base + i) for i in range(4)]
            elif k == "add_circle":
                c = _pt_index(d, op["center"], made)
                d["entities"].append({"k": "circle", "p": [c], "r": float(op["r"])})
                made.append(("entity", len(d["entities"]) - 1))
            elif k == "add_arc":
                ps = [_pt_index(d, p, made) for p in (op["center"], op["start"], op["end"])]
                d["entities"].append({"k": "arc", "p": ps})
                made.append(("entity", len(d["entities"]) - 1))
            elif k == "constrain":
                kind = op.get("kind")
                if kind not in GEOMETRIC:
                    raise _bad(f"unknown constraint {kind!r}", "Kinds: " + ", ".join(GEOMETRIC) + ".")
                c = {"k": kind}
                if op.get("entities"):
                    c["e"] = [int(x) for x in op["entities"]]
                if op.get("points"):
                    c["p"] = [int(x) for x in op["points"]]
                if kind == "fix":
                    for j in c.get("p", []):
                        if j not in d["fixed"]:
                            d["fixed"].append(j)
                else:
                    d["constraints"].append(c)
            elif k == "dimension":
                kind = op.get("kind")
                if kind not in DIMENSIONS:
                    raise _bad(f"unknown dimension {kind!r}", "Kinds: " + ", ".join(DIMENSIONS) + ".")
                c = {"k": kind, "value": float(op["value"])}
                if op.get("entities") is not None:
                    c["e"] = [int(x) for x in op["entities"]]
                if op.get("points") is not None:
                    c["p"] = [int(x) for x in op["points"]]
                name = op.get("name", None)
                c["name"] = _free_name(d, {"length": "l", "radius": "r", "diameter": "d", "angle": "a"}.get(kind, "dist")) \
                    if name is None else name
                if not c["name"]:
                    c.pop("name")
                if op.get("label"):
                    c["label"] = op["label"]
                d["constraints"].append(c)
                made.append(("dimension", c.get("name", "")))
            elif k == "set":
                hit = [c for c in d["constraints"] if c.get("name") == op.get("name")]
                if not hit:
                    raise _bad(f"no dimension named {op.get('name')!r}")
                hit[0]["value"] = float(op["value"])
            elif k == "move":
                i = int(op["point"])
                if not 0 <= i < len(d["points"]):
                    raise _bad(f"there is no point {i}")
                d["points"][i] = [float(op["to"][0]), float(op["to"][1])]
            elif k == "construction":
                d["entities"][int(op["entity"])]["construction"] = bool(op.get("on", True))
            elif k == "plane":
                d["plane"] = op["plane"]
            else:  # delete
                if "constraint" in op:
                    del d["constraints"][int(op["constraint"])]
                elif "entity" in op:
                    j = int(op["entity"])
                    del d["entities"][j]
                    keep = []
                    for c in d["constraints"]:
                        if j in (c.get("e") or []):
                            continue
                        c["e"] = [x - 1 if x > j else x for x in c.get("e") or []] or c.get("e")
                        if not c["e"]:
                            c.pop("e", None)
                        keep.append(c)
                    d["constraints"] = keep
                else:
                    raise _bad("delete needs constraint or entity (an index)")
            check(d)
        except SketchError as e:
            raise _bad(f"sketch op {n} ({k}): {e}", e.hint)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise _bad(f"sketch op {n} ({k}) is missing or has a wrong field ({type(e).__name__}: {e})")
        made_all.append(made)
    return d, made_all


# ---- kernel side: the plane, and the features ---------------------------------------------------------------------

END_CONDITIONS = ("blind", "through", "next", "face", "vertex", "offset", "mid")
THIN_MODES = ("one", "mid", "two")
REVOLVE_ENDS = ("angle", "face")


def _val(x, v, what: str = "") -> float:
    """A number in a plane or end condition: a literal, or the key of a parameter (read from v)."""
    if isinstance(x, str):
        if v is None or x not in v:
            raise RecipeError(f"{what}: it reads the parameter {x}, which the design does not have", what,
                              f"Add the parameter {x}, or write the number.")
        return float(v[x])
    return float(x or 0)


def plane_of(data: dict, body, trail, what: str, v: dict | None = None):
    """The build123d Plane the sketch lies on, now: a datum (XY, XZ, YZ with an offset), a picked face, or a datum
    plane feature ({"ref": "datum_plane_1", ...its definition}; form/handmore.py)."""
    return resolve_plane(data["plane"], body, trail, what, v)


def resolve_plane(pl: dict, body, trail, what: str, v: dict | None = None):
    """A plane from its definition. Datum planes (form/handmore.py datum_plane) are written as their definition:
    base (XY, XZ, YZ or a face query), offset and angle (numbers or parameter keys), about (x or y: the base plane's
    own axis the angle turns about), or through (three points)."""
    from build123d import Plane, Vector
    if not isinstance(pl, dict):
        raise RecipeError(f"{what}: a plane is an object (datum, face or a datum plane's definition)", what, "")
    if "through" in pl:
        p = [Vector(*q) for q in pl["through"]]
        if len(p) != 3:
            raise RecipeError(f"{what}: a plane through points needs three points", what, "Give three points.")
        x, n = p[1] - p[0], (p[1] - p[0]).cross(p[2] - p[0])
        if x.length < 1e-6 or n.length < 1e-6 * max(1.0, x.length ** 2):
            raise RecipeError(f"{what}: the three points are on one line, so they make no plane", what,
                              "Pick three points that are not in a row.")
        plane = Plane(origin=p[0], x_dir=x.normalized(), z_dir=n.normalized())
    elif "base" in pl or "ref" in pl:
        base = pl.get("base", "XY")
        if isinstance(base, str):
            if base not in DATUMS:
                raise RecipeError(f"{what}: unknown base plane {base!r}", what, "XY, XZ or YZ, or a picked face.")
            x, _y, z = DATUMS[base]
            plane = Plane(origin=(0, 0, 0), x_dir=x, z_dir=z)
        else:
            plane = _face_plane(base.get("face", base), body, trail, what)
        ang = _val(pl.get("angle", 0), v, what)
        if abs(ang) > 1e-12:
            plane = plane.rotated((ang, 0, 0) if pl.get("about", "x") == "x" else (0, ang, 0))
        off = _val(pl.get("offset", 0), v, what)
        if abs(off) > 1e-12:
            plane = plane.offset(off)
    elif "datum" in pl:
        x, _y, z = DATUMS[pl["datum"]]
        n = Vector(*z)
        plane = Plane(origin=n * _val(pl.get("offset") or 0, v, what), x_dir=x, z_dir=z)
    elif "face" in pl:
        if body is None:
            raise RecipeError(f"{what}: its sketch is on a face, but there is no body yet", what,
                              "Sketch the first feature on a datum plane (XY, XZ or YZ).")
        from . import handfeat
        f = handfeat.find_face(body, trail, pl["face"], what)
        n = Vector(*handfeat._vec(f.normal_at(f.center()))).normalized()
        if "origin" in pl:
            o = Vector(*pl["origin"])
            o = o - n * ((o - f.center()).dot(n))
            return Plane(origin=o, x_dir=tuple(pl["x"]), z_dir=tuple(handfeat._vec(n)))
        return Plane(origin=f.center(), z_dir=n)
    else:
        raise RecipeError(f"{what}: the plane is a datum (XY, XZ, YZ), a picked face or a datum plane", what, "")
    return plane


def _face_plane(q: dict, body, trail, what: str):
    """The plane of a picked flat face, found again on this rebuild (origin at its centre, z along its normal)."""
    from build123d import Plane, Vector

    from . import handfeat
    if body is None:
        raise RecipeError(f"{what}: it is on a face, but there is no body yet", what, "Use a datum plane.")
    f = handfeat.find_face(body, trail, q, what)
    if f.geom_type.name != "PLANE":
        raise RecipeError(f"{what}: its face is {f.geom_type.name.lower()}, not flat", what, "Pick a flat face.")
    return Plane(origin=f.center(), z_dir=Vector(*handfeat._vec(f.normal_at(f.center()))).normalized())


def profile(data: dict, v: dict, prefix: str, plane):
    sk, vals = build(data, v, prefix)
    try:
        face = sk.face(vals)
    except SketchError as e:
        raise RecipeError(str(e), prefix.rstrip("_"), e.hint)
    return plane.location * face


def open_wire(data: dict, v: dict, prefix: str, plane, what: str):
    """The sketch's drawn (not construction) lines and arcs as one connected 3D wire, open or closed: a sweep's
    path or a rib's line."""
    from build123d import Edge, Vector, Wire
    sk, vals = build(data, v, prefix)
    try:
        eds = sk.edges2d(vals)
    except SketchError as e:
        raise RecipeError(f"{what}: {e}", what, e.hint)
    if not eds:
        raise RecipeError(f"{what}: the sketch has no lines or arcs", what, "Draw the path or the rib's line.")
    edges = []
    for ed in eds:
        if ed["kind"] == "line":
            edges.append(Edge.make_line(Vector(*ed["a"], 0), Vector(*ed["b"], 0)))
        elif ed["kind"] == "arc":
            edges.append(Edge.make_three_point_arc(Vector(*ed["s"], 0), Vector(*ed["m"], 0), Vector(*ed["e"], 0)))
        else:
            raise RecipeError(f"{what}: a circle is not a path or a rib line", what, "Use lines and arcs.")
    try:
        ws = Wire.combine(edges)
    except Exception as e:                                    # noqa: BLE001
        raise RecipeError(f"{what}: its lines do not join into one chain ({type(e).__name__})", what,
                          "Join them end to end (coincident).")
    if len(ws) != 1:
        raise RecipeError(f"{what}: its lines make {len(ws)} separate chains, not one", what,
                          "Join them end to end into one chain.")
    return plane.location * ws[0]


def _thin(face, t: float, mode: str, t2: float, what: str):
    """A closed profile as a wall: one (outside, t), mid (t centred on the outline) or two (t outside, t2 inside)."""
    from build123d import Kind, offset
    if t <= 0:
        raise RecipeError(f"{what}: a thin feature's wall needs a thickness above 0", what, "Set thin.")
    if mode not in THIN_MODES:
        raise RecipeError(f"{what}: unknown thin mode {mode!r}", what, "one, mid or two.")
    out_t, in_t = {"one": (t, 0.0), "mid": (t / 2, t / 2), "two": (t, t2)}[mode]
    if mode == "two" and t2 <= 0:
        raise RecipeError(f"{what}: a two-sided wall needs its inside thickness above 0", what, "Set thin2.")
    try:
        outer = offset(face, out_t, kind=Kind.INTERSECTION) if out_t > 0 else face
        inner = offset(face, -in_t, kind=Kind.INTERSECTION) if in_t > 0 else face
        ring = outer - inner
    except Exception as e:                                    # noqa: BLE001
        raise RecipeError(f"{what}: the profile cannot be offset by {max(out_t, in_t):g} mm ({type(e).__name__})",
                          what, "Make the wall thinner than the profile's narrowest part.")
    if not ring.faces() or ring.area <= 1e-9:
        raise RecipeError(f"{what}: the wall leaves no area", what, "Make the wall thinner.")
    return ring


def _far(body, plane) -> float:
    if body is None:
        return 1000.0
    bb = body.bounding_box()
    c = [(bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)]
    return 2 * (math.dist(*c) + math.dist(tuple(plane.origin), tuple((a + b) / 2 for a, b in zip(*c)))) + 2


def _inner_point(f):
    """A point inside the profile (its centre when that is inside, else a sampled one)."""
    c = f.center()
    for face in f.faces():
        if face.is_inside(c):
            return c
        for u in (0.5, 0.25, 0.75, 0.1, 0.9):
            for w in (0.5, 0.25, 0.75, 0.1, 0.9):
                p = face.position_at(u, w)
                if face.is_inside(p):
                    return p
    return c


def _upto_next(f, plane, d, body, what, draft, add):
    """Up to next: the profile extruded far along d, kept only up to the first face of the body it meets (a pad fills
    the gap to that face; a cut goes on until it leaves the material it starts in)."""
    from build123d import extrude as _ex
    long = _ex(f, amount=_far(body, plane), dir=d, taper=draft)
    pieces = (long - body) if add else (long & body)
    probe = _inner_point(f) + d * 1e-3
    keep = [s for s in (pieces.solids() if pieces is not None else []) if s.is_inside(probe)]
    if not keep:
        raise RecipeError(f"{what}: up to next: {'the body is already there' if add else 'there is no material'} "
                          "where the profile starts", what, "Reverse the direction, or use blind.")
    tool = keep[0]
    reach = max((q.center() - plane.origin).dot(d) for q in tool.vertices())
    if reach > 0.9 * _far(body, plane):
        raise RecipeError(f"{what}: up to next meets no face ahead", what, "Reverse the direction, or use blind.")
    return tool


def _upto_depth(plane, d, target_plane, offset, what):
    """How far along d (from the sketch plane) a flat target is, when it is parallel to the sketch plane; else None."""
    m = target_plane.z_dir
    if abs(abs(m.dot(plane.z_dir)) - 1) > 1e-7:
        return None
    dist = (target_plane.origin - plane.origin).dot(d) - offset
    if dist <= 1e-6:
        raise RecipeError(f"{what}: the face it goes up to is not ahead of the sketch ({dist:.3f} mm along the "
                          "direction)", what, "Reverse the direction, or pick a face on the other side.")
    return dist


def _one_side(f, plane, d, body, trail, v, what, end, depth, to, offset, draft, add=True):
    """The tool of one direction: the profile f extruded along the unit vector d under one end condition."""
    from build123d import Plane, Vector, extrude, split
    from build123d import Keep
    if end in ("blind", "mid"):
        if depth <= 0:
            raise RecipeError(f"{what}: a blind extrusion needs a depth above 0", what, "Set its depth.")
        return extrude(f, amount=depth / 2 if end == "mid" else depth, dir=d, both=end == "mid", taper=draft)
    if end == "through":
        return extrude(f, amount=_far(body, plane), dir=d, taper=draft)
    if end == "next":
        if body is None:
            raise RecipeError(f"{what}: up to next needs a body to reach", what, "Use blind for the first feature.")
        return _upto_next(f, plane, d, body, what, draft, add)
    if end == "vertex":
        if not to:
            raise RecipeError(f"{what}: up to vertex needs the point", what, "Pick a vertex.")
        dist = (Vector(*to) - plane.origin).dot(d)
        if dist <= 1e-6:
            raise RecipeError(f"{what}: the vertex is not ahead of the sketch ({dist:.3f} mm)", what,
                              "Reverse the direction, or pick another vertex.")
        return extrude(f, amount=dist, dir=d, taper=draft)
    if end in ("face", "offset"):
        if not to:
            raise RecipeError(f"{what}: up to face needs the picked face", what, "Pick the face to go up to.")
        tp = _face_plane(to, body, trail, what)
        off = offset if end == "offset" else 0.0
        dist = _upto_depth(plane, d, tp, off, what)
        if dist is not None:
            return extrude(f, amount=dist, dir=d, taper=draft)
        long = extrude(f, amount=_far(body, plane), dir=d, taper=draft)
        cut_at = Plane(origin=tp.origin - tp.z_dir * (off if tp.z_dir.dot(d) > 0 else -off), z_dir=tp.z_dir)
        keep = Keep.BOTTOM if cut_at.z_dir.dot(d) > 0 else Keep.TOP
        out = split(long, bisect_by=cut_at, keep=keep)
        if out is None or not out.solids() or out.volume <= 1e-9:
            raise RecipeError(f"{what}: the face it goes up to does not cross its path", what, "Pick another face.")
        return out
    raise RecipeError(f"{what}: unknown end condition {end!r}", what, ", ".join(END_CONDITIONS) + ".")


def extrude(body, trail, data: dict, v: dict, fid: str, depth: float, mode: str = "add", *, end: str = "",
            to=None, offset: float = 0.0, reverse: bool = False, draft: float = 0.0, end2: str = "",
            depth2: float = 0.0, to2=None, offset2: float = 0.0, draft2: float = 0.0, thin: float = 0.0,
            thin_mode: str = "one", thin2: float = 0.0):
    """The sketch's profile extruded depth mm along the plane's normal (add), cut into the body (cut) or kept as a new
    body beside it (new). Without end: the classic behaviour (a cut of depth 0 goes through everything, both ways on
    a datum). end: blind | through | next (up to the next face of the body) | face (up to a picked flat face, `to`
    its query) | vertex (up to a point, `to` [x, y, z]) | offset (from a picked face, `offset` mm short of it) |
    mid (depth centred on the sketch). reverse flips the direction (a cut goes into the part by default). end2 is a
    second direction with its own condition (depth2, to2, offset2, draft2). draft: degrees of taper (positive
    narrows). thin: a wall of this thickness along the profile instead of the filled profile (thin_mode one: outside,
    mid: centred, two: thin outside and thin2 inside)."""
    from build123d import Compound
    from build123d import extrude as _extrude
    from .craft import safe_cut, safe_union
    plane = plane_of(data, body, trail, fid, v)
    f = profile(data, v, fid + "_", plane)
    if mode not in ("add", "cut", "new"):
        raise RecipeError(f"{fid}: mode is add, cut or new, not {mode!r}", fid, "")
    if thin:
        f = _thin(f, float(thin), thin_mode, float(thin2 or 0), fid)
    if not end and not end2 and not draft and not reverse:
        # the classic behaviour, kept exactly (designs written before end conditions build the same solid)
        if mode in ("add", "new"):
            if depth <= 0:
                raise RecipeError(f"{fid}: an extrusion needs a depth above 0", fid, "Set its depth.")
            tool = _extrude(f, amount=float(depth))
        else:
            if body is None:
                raise RecipeError(f"{fid}: a cut needs a body to cut", fid, "Extrude first.")
            if depth and depth > 0:
                tool = _extrude(f, amount=-float(depth))
            else:
                L = _far(body, plane)
                tool = _extrude(f, amount=L, both=True) if "datum" in data["plane"] else _extrude(f, amount=-L)
    else:
        if mode == "cut" and body is None:
            raise RecipeError(f"{fid}: a cut needs a body to cut", fid, "Extrude first.")
        n = plane.z_dir
        s = (-1.0 if mode == "cut" else 1.0) * (-1.0 if reverse else 1.0)
        e1 = end or ("blind" if depth and depth > 0 else ("through" if mode == "cut" else "blind"))
        tool = _one_side(f, plane, n * s, body, trail, v, fid, e1, float(depth or 0), to, float(offset or 0),
                         float(draft or 0), mode != "cut")
        if end2:
            if e1 == "mid":
                raise RecipeError(f"{fid}: mid-plane already goes both ways", fid, "Use blind with a second direction.")
            t2 = _one_side(f, plane, n * -s, body, trail, v, fid, end2, float(depth2 or 0), to2, float(offset2 or 0),
                           float(draft2 or 0), mode != "cut")
            tool = tool + t2
    if body is None:
        return tool
    if mode == "new":
        return Compound(list(body.solids()) + list(tool.solids()))
    try:
        return safe_union(body, tool) if mode == "add" else safe_cut(body, tool)
    except RecipeError as e:
        raise RecipeError(f"{fid}: {e}", fid, e.hint or ("The extrusion does not touch the part: sketch on its face."
                                                          if mode == "add" else "The cut does not reach the part."))


def _axis_of(data, v, fid, plane, axis_entity):
    from build123d import Axis, Vector
    sk, vals = build(data, v, fid + "_")
    sol = sk.solve(vals)
    d = check(data)
    if not (0 <= axis_entity < len(d["entities"])) or d["entities"][axis_entity]["k"] != "line":
        raise RecipeError(f"{fid}: the axis is entity {axis_entity}, which is not a line", fid, "Pick a line.")
    a, b = (sol.pts[j] for j in d["entities"][axis_entity]["p"])
    pa, pb = plane.from_local_coords(Vector(a[0], a[1], 0)), plane.from_local_coords(Vector(b[0], b[1], 0))
    return Axis(tuple(pa), tuple(pb - pa))


def _angle_to_face(f, axis, tp, what) -> float:
    """The angle (degrees, in the revolve's positive sense) from the profile to a flat face whose plane holds the
    axis: what a revolve up to that face turns."""
    from build123d import Vector
    a = axis.direction.normalized()
    o = axis.position
    if abs(tp.z_dir.dot(a)) > 1e-6 or abs((o - tp.origin).dot(tp.z_dir)) > 1e-6:
        raise RecipeError(f"{what}: a revolve goes up to a flat face whose plane holds its axis; this one does not",
                          what, "Pick a face through the axis, or give the angle.")

    def flat(p):
        r = Vector(p) - o
        return r - a * r.dot(a)
    u, w = flat(f.center()), flat(tp.origin)
    if u.length < 1e-9 or w.length < 1e-9:
        raise RecipeError(f"{what}: the profile or the face sits on the axis", what, "Give the angle.")
    ang = math.degrees(math.atan2(u.cross(w).dot(a), u.dot(w))) % 360.0
    if ang < 1e-6:
        raise RecipeError(f"{what}: the face is where the profile already is", what, "Pick another face.")
    return ang


def revolve(body, trail, data: dict, v: dict, fid: str, axis_entity: int, angle: float, mode: str = "add", *,
            end: str = "angle", to=None, angle2: float = 0.0, mid: bool = False, reverse: bool = False):
    """The profile turned about one of the sketch's lines (often a construction line) by angle degrees. end: angle |
    face (up to a picked flat face whose plane holds the axis, `to` its query). angle2: a second direction, turned
    the other way. mid: the angle centred on the sketch. reverse: the other way round."""
    from build123d import revolve as _revolve
    from .craft import safe_cut, safe_union
    plane = plane_of(data, body, trail, fid, v)
    d = check(data)
    axis = _axis_of(data, v, fid, plane, axis_entity)
    f = profile(d, v, fid + "_", plane)       # the axis may be an edge of the profile, or a construction line beside it
    if end not in REVOLVE_ENDS:
        raise RecipeError(f"{fid}: unknown revolve end {end!r}", fid, "angle or face.")
    if end == "face":
        if not to:
            raise RecipeError(f"{fid}: up to face needs the picked face", fid, "Pick the face.")
        ang = _angle_to_face(f, axis if not reverse else axis.reverse(), _face_plane(to, body, trail, fid), fid)
    else:
        ang = float(angle)
    if not 0 < ang <= 360 or not 0 <= float(angle2 or 0) <= 360 or ang + float(angle2 or 0) > 360 + 1e-9:
        raise RecipeError(f"{fid}: the angles {ang:g}° and {float(angle2 or 0):g}° must be above 0 and at most 360° "
                          "together", fid, "Make them smaller.")
    start = -ang / 2 if mid else -float(angle2 or 0)
    total = ang + (0.0 if mid else float(angle2 or 0))
    if reverse:
        start, total = -(start + total), total
    if abs(start) > 1e-12:
        f = f.rotate(axis, start)
    tool = _revolve(f, axis, total)
    if body is None:
        return tool
    if mode == "new":
        from build123d import Compound
        return Compound(list(body.solids()) + list(tool.solids()))
    return safe_union(body, tool) if mode == "add" else safe_cut(body, tool)
