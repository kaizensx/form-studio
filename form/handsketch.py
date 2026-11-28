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
    if "datum" not in pl and "face" not in pl:
        raise _bad("The plane is a datum (XY, XZ, YZ) or a picked face.")
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


def literal(data: dict, indent: str = "        ") -> str:
    """The sketch as a Python literal laid out one list per line (what the feature method holds)."""
    import json
    d = check(data)
    rows = []
    for k in ("plane", "points", "fixed", "entities", "constraints"):
        if k in ("entities", "constraints") and d[k]:
            inner = (",\n" + indent + "    ").join(json.dumps(x) for x in d[k])
            rows.append(f'"{k}": [\n{indent}    {inner}]')
        else:
            rows.append(f'"{k}": {json.dumps(d[k])}')
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

def plane_of(data: dict, body, trail, what: str):
    """The build123d Plane the sketch lies on, now."""
    from build123d import Plane, Vector
    pl = data["plane"]
    if "datum" in pl:
        x, _y, z = DATUMS[pl["datum"]]
        n = Vector(*z)
        return Plane(origin=n * float(pl.get("offset") or 0), x_dir=x, z_dir=z)
    if body is None:
        raise RecipeError(f"{what}: its sketch is on a face, but there is no body yet", what,
                          "Sketch the first feature on a datum plane (XY, XZ or YZ).")
    from . import handfeat
    f = handfeat.find_face(body, trail, pl["face"], what)
    n = Vector(*handfeat._vec(f.normal_at(f.center()))).normalized()
    o = Vector(*pl["origin"])
    o = o - n * ((o - f.center()).dot(n))
    return Plane(origin=o, x_dir=tuple(pl["x"]), z_dir=tuple(handfeat._vec(n)))


def profile(data: dict, v: dict, prefix: str, plane):
    sk, vals = build(data, v, prefix)
    try:
        face = sk.face(vals)
    except SketchError as e:
        raise RecipeError(str(e), prefix.rstrip("_"), e.hint)
    return plane.location * face


def extrude(body, trail, data: dict, v: dict, fid: str, depth: float, mode: str = "add"):
    """The sketch's profile extruded depth mm along the plane's normal (add), or cut into the body (depth 0 = through
    everything, both ways on a datum)."""
    from build123d import extrude as _extrude
    from .craft import safe_cut, safe_union
    plane = plane_of(data, body, trail, fid)
    f = profile(data, v, fid + "_", plane)
    if mode == "add":
        if depth <= 0:
            raise RecipeError(f"{fid}: an extrusion needs a depth above 0", fid, "Set its depth.")
        tool = _extrude(f, amount=float(depth))
        if body is None:
            return tool
        try:
            return safe_union(body, tool)
        except RecipeError as e:
            raise RecipeError(f"{fid}: {e}", fid, e.hint or "The extrusion does not touch the part: sketch on its face.")
    if body is None:
        raise RecipeError(f"{fid}: a cut needs a body to cut", fid, "Extrude first.")
    if depth and depth > 0:
        tool = _extrude(f, amount=-float(depth))
    else:
        bb = body.bounding_box()
        L = 2 * math.dist((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)) + 2
        tool = _extrude(f, amount=L, both=True) if "datum" in data["plane"] else _extrude(f, amount=-L)
    try:
        return safe_cut(body, tool)
    except RecipeError as e:
        raise RecipeError(f"{fid}: {e}", fid, e.hint or "The cut does not reach the part.")


def revolve(body, trail, data: dict, v: dict, fid: str, axis_entity: int, angle: float, mode: str = "add"):
    """The profile turned about one of the sketch's lines (often a construction line) by angle degrees."""
    from build123d import Axis, Vector
    from build123d import revolve as _revolve
    from .craft import safe_cut, safe_union
    plane = plane_of(data, body, trail, fid)
    sk, vals = build(data, v, fid + "_")
    sol = sk.solve(vals)
    d = check(data)
    if not (0 <= axis_entity < len(d["entities"])) or d["entities"][axis_entity]["k"] != "line":
        raise RecipeError(f"{fid}: the axis is entity {axis_entity}, which is not a line", fid, "Pick a line.")
    a, b = (sol.pts[j] for j in d["entities"][axis_entity]["p"])
    pa, pb = plane.from_local_coords(Vector(a[0], a[1], 0)), plane.from_local_coords(Vector(b[0], b[1], 0))
    f = profile(d, v, fid + "_", plane)       # the axis may be an edge of the profile, or a construction line beside it
    tool = _revolve(f, Axis(tuple(pa), tuple(pb - pa)), float(angle))
    if body is None:
        return tool
    return safe_union(body, tool) if mode == "add" else safe_cut(body, tool)
