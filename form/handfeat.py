"""Features made by picking geometry: fillet, chamfer, hole, pattern and shell (kernel side; runs in the worker).

A picked feature is a method in the design's source (form/modelling.py writes it), so the person and the agent edit
the same thing. The method calls one function here with the body, the solid as each feature before it left it
(``self._form_trail``, set by form/featureprog.py), its parameters and the geometry it was picked on:

    @feature("Fillet 1", role="finish")
    def fillet_1(self, v, body):
        from form import handfeat
        return handfeat.fillet(body, self._form_trail, v["fillet_1_r"],
                               [{"owners": ["body", "body"], "geom": "LINE", "dir": [0, 0, 1], "pos": [1, 1, 0.5]}])

Edges and faces are named by a stable query, not by an index: the features that made the faces around them (the
same rule Form Studio colours faces by: a face belongs to the last feature that made the surface under it), the
geometry class (a line, a circle, a plane...), the direction of a line or the normal of a plane, and where it sits
in the body's bounding box as fractions of its size. A rebuild finds the edge whose owners and class match and whose
place is nearest; when none is within POS_TOL the feature says which edge it lost and is left out of the build
(the Program pane lists it as left out, with that reason), as every failing feature is. Nothing is guessed.

Sizes: a fillet or chamfer is made at the size its parameter says or not at all (no silent reduction); a hole's
diameter comes from the standard it names (ISO 273 clearance, tap drill, ISO 286 fit), computed in pick() with the
source written next to the parameter.
"""
from __future__ import annotations

import math

from .recipes.base import RecipeError

POS_TOL = 0.2           # a picked edge or face is found again within this share of the body's size
PARALLEL = 0.995        # |cos| at which two directions count as the same
ON_FACE = 0.05          # mm: a hole's point must be this close to its face after the rebuild
EVIDENCE = "computed (B-rep)"


# ---- reading the body: who made each face, and the queries that name edges and faces -------------------------------

def _box(shape):
    bb = shape.bounding_box()
    lo = (bb.min.X, bb.min.Y, bb.min.Z)
    sz = tuple(max(1e-6, b - a) for a, b in zip(lo, (bb.max.X, bb.max.Y, bb.max.Z)))
    return lo, sz


def _frac(c, lo, sz) -> list:
    return [round((c[i] - lo[i]) / sz[i], 4) for i in range(3)]


def _vec(v) -> tuple:
    return (float(v.X), float(v.Y), float(v.Z))


def _unit(d) -> list:
    n = math.sqrt(sum(x * x for x in d)) or 1.0
    u = [x / n for x in d]
    for x in u:                                      # one sign for a direction: the first clear component positive
        if abs(x) > 1e-6:
            if x < 0:
                u = [-y for y in u]
            break
    return [round(x, 4) + 0.0 for x in u]


def _par(a, b) -> bool:
    return abs(sum(x * y for x, y in zip(a, b))) >= PARALLEL


def owners_of(body, trail) -> dict:
    """{hash(face): feature id} for the faces of body, read from the stages that made it (form/kernel.py's rule)."""
    from . import kernel
    from .recipes.base import Stage
    stages = list(trail or [])
    if not stages:
        return {hash(f): "?" for f in body.faces()}
    if stages[-1].shape is not body:
        stages.append(Stage("?", body))
    feats, _tess = kernel._attribute(body, stages, kernel.ATTR_TOL)
    return {hash(f): (feats[i] or "?") for i, f in enumerate(body.faces())}


def _adjacency(body) -> dict:
    out: dict = {}
    for f in body.faces():
        for e in f.edges():
            out.setdefault(hash(e), []).append(f)
    return out


def _edges(body) -> list:
    seen, out = set(), []
    for f in body.faces():
        for e in f.edges():
            if hash(e) not in seen:
                seen.add(hash(e))
                out.append(e)
    return out


def edge_query(e, adj: dict, own: dict, lo, sz) -> dict:
    geom = e.geom_type.name
    q = {"owners": sorted(own.get(hash(f), "?") for f in adj.get(hash(e), [])), "geom": geom,
         "pos": _frac(_vec(e.center()), lo, sz)}
    if geom == "LINE":
        q["dir"] = _unit([b - a for a, b in zip(_vec(e.position_at(0)), _vec(e.position_at(1)))])
    elif geom == "CIRCLE":
        try:
            q["r"] = round(float(e.radius), 4)
        except Exception:
            pass
    return q


def face_query(f, own: dict, lo, sz) -> dict:
    geom = f.geom_type.name
    q = {"owner": own.get(hash(f), "?"), "geom": geom, "pos": _frac(_vec(f.center()), lo, sz)}
    if geom == "PLANE":
        q["normal"] = [round(x, 4) for x in _vec(f.normal_at(f.center()))]
    return q


def _say_edge(q: dict) -> str:
    o = list(dict.fromkeys(q.get("owners") or ["?"]))
    where = f"between two faces of {o[0]}" if len(o) == 1 else "between " + " and ".join(o)
    return f"a {q.get('geom', 'edge').lower()} edge {where}"


def find_edges(body, trail, queries: list, what: str) -> list:
    """The edges of body the queries name, one each, or a RecipeError naming the first one that is not there."""
    own = owners_of(body, trail)
    adj = _adjacency(body)
    lo, sz = _box(body)
    cands = [(e, edge_query(e, adj, own, lo, sz)) for e in _edges(body)]
    out, used = [], set()
    for i, q in enumerate(queries, 1):
        best = None
        for e, c in cands:
            if hash(e) in used or c["geom"] != q.get("geom") or c["owners"] != sorted(q.get("owners") or []):
                continue
            if q.get("dir") and not (c.get("dir") and _par(c["dir"], q["dir"])):
                continue
            d = math.dist(c["pos"], q.get("pos") or c["pos"])
            if q.get("r") and c.get("r"):
                d += 0.5 * abs(c["r"] - q["r"]) / max(q["r"], 1e-6)
            if best is None or d < best[0]:
                best = (d, e)
        if best is None or best[0] > POS_TOL:
            raise RecipeError(f"{what}: edge {i} of {len(queries)} ({_say_edge(q)}) is not on the part now",
                              "", "Pick the edges again on this revision, or change the parameter back toward "
                              "the value it was picked at.")
        used.add(hash(best[1]))
        out.append(best[1])
    return out


def find_face(body, trail, q: dict, what: str):
    own = owners_of(body, trail)
    lo, sz = _box(body)
    best = None
    for f in body.faces():
        c = face_query(f, own, lo, sz)
        if c["geom"] != q.get("geom") or c["owner"] != q.get("owner"):
            continue
        if q.get("normal") and not (c.get("normal") and sum(x * y for x, y in zip(c["normal"], q["normal"])) >= PARALLEL):
            continue
        d = math.dist(c["pos"], q.get("pos") or c["pos"])
        if best is None or d < best[0]:
            best = (d, f)
    if best is None or best[0] > POS_TOL:
        raise RecipeError(f"{what}: its face (a {str(q.get('geom', '')).lower()} face made by {q.get('owner', '?')}) "
                          "is not on the part now", "", "Pick the face again on this revision.")
    return best[1]


# ---- the features ----------------------------------------------------------------------------------------------------

def _blend(body, edges, size, chamfer, what):
    from .craft.surfaces import guarded_blend
    try:
        out = guarded_blend(body, size, edges, chamfer=chamfer)
    except Exception as e:                           # OCCT: the blend does not fit these edges at this size
        raise RecipeError(f"{what}: a {size:g} mm {'chamfer' if chamfer else 'fillet'} does not fit these "
                          f"{len(edges)} edge(s) ({type(e).__name__})", "",
                          "Make it smaller than the faces it runs between, or pick fewer edges.")
    if not out.is_valid:
        raise RecipeError(f"{what}: the {size:g} mm blend leaves an invalid solid", "", "Make it smaller.")
    return out


def fillet(body, trail, radius: float, edges: list, what: str = "fillet"):
    """Round the picked edges with this radius, or fail saying why (never a smaller radius in silence)."""
    return _blend(body, find_edges(body, trail, edges, what), float(radius), False, what)


def chamfer(body, trail, length: float, edges: list, what: str = "chamfer"):
    return _blend(body, find_edges(body, trail, edges, what), float(length), True, what)


def hole(body, trail, face: dict, at, d: float, depth: float = 0.0, style: str = "plain", head_d: float = 0.0,
         head_depth: float = 0.0, what: str = "hole"):
    """A hole into the picked face at the point `at`, along the face's inward normal. depth 0: through all.
    style: plain | counterbore (head_d, head_depth) | countersink (head_d, 90 degrees)."""
    from build123d import Cone, Cylinder, Plane, Pos, Vector
    f = find_face(body, trail, face, what)
    n = Vector(*_vec(f.normal_at(f.center()))).normalized()
    p = Vector(*at)
    p = p - n * ((p - f.center()).dot(n))           # the point, on the face's plane as it is now
    if f.distance_to(p) > ON_FACE:
        raise RecipeError(f"{what}: its point ({p.X:.2f}, {p.Y:.2f}, {p.Z:.2f}) is no longer on its face", "",
                          "Move the hole (edit its point in the code) or pick the face again.")
    lo, sz = _box(body)
    through = math.sqrt(sum(s * s for s in sz)) * 2 + 2
    L = float(depth) if depth and depth > 0 else through
    pl = Plane(origin=p, z_dir=-n)
    tool = pl * Pos(0, 0, -0.2) * Cylinder(d / 2, L + 0.2, align=(_C, _C, _MIN))
    if style == "counterbore" and head_d > d and head_depth > 0:
        tool = tool + pl * Pos(0, 0, -0.2) * Cylinder(head_d / 2, head_depth + 0.2, align=(_C, _C, _MIN))
    elif style == "countersink" and head_d > d:
        h = (head_d - d) / 2                         # 90 degrees: as deep as it is wide on one side
        tool = tool + pl * Pos(0, 0, -0.2) * Cone(head_d / 2 + 0.2, d / 2, h + 0.2, align=(_C, _C, _MIN))
    from .craft import safe_cut
    try:
        return safe_cut(body, tool)
    except RecipeError as e:
        raise RecipeError(f"{what}: {e}", "", e.hint or "The hole does not cut the part where it was picked.")


def pattern(body, trail, of: str, kind: str, count: int, step: float, axis, origin=(0.0, 0.0, 0.0),
            what: str = "pattern"):
    """Repeat what feature `of` added and cut, count times in all: linear (step mm along axis) or polar (step degrees
    about the axis through origin). The copies are booleans of that change, so it works for any feature."""
    from build123d import Location, Vector
    ids = [s.feature for s in trail]
    if of not in ids:
        raise RecipeError(f"{what}: it repeats {of}, which is not built before it", "",
                          f"Restore {of} or move this pattern after it.")
    i = ids.index(of)
    if i == 0:
        raise RecipeError(f"{what}: the first feature is the whole body and cannot be repeated", "",
                          "Pattern a feature that adds or cuts something.")
    before, after = trail[i - 1].shape, trail[i].shape
    added, removed = after - before, before - after
    n_add = sum(s.volume for s in added.solids()) if added is not None else 0.0
    n_cut = sum(s.volume for s in removed.solids()) if removed is not None else 0.0
    if n_add < 1e-6 and n_cut < 1e-6:
        raise RecipeError(f"{what}: {of} changes no volume, so there is nothing to repeat", "", "Pick another feature.")
    count = int(round(count))
    if count < 2:
        raise RecipeError(f"{what}: count is {count}; a pattern has 2 or more", "", "Set count to 2 or more.")
    ax = Vector(*axis).normalized()
    out = body
    for k in range(1, count):
        loc = Location(ax * (step * k)) if kind == "linear" else _rotation(origin, ax, step * k)
        if n_add >= 1e-6:
            out = out + added.moved(loc)
        if n_cut >= 1e-6:
            out = out - removed.moved(loc)
    return out


def _rotation(origin, ax, deg):
    from build123d import Location, Vector
    o = Vector(*origin)
    # translate the origin to 0, turn about ax, translate back
    return Location(o) * Location((0, 0, 0), tuple(_vec(ax)), deg) * Location(-o)


def shell(body, trail, thickness: float, open_face: dict | None = None, what: str = "shell"):
    """A hollow body, walls `thickness` thick, open at the picked face (none: closed inside)."""
    from .craft.surfaces import shell as _shell
    faces = [find_face(body, trail, open_face, what)] if open_face else []
    try:
        return _shell(body, float(thickness), faces)
    except RecipeError as e:
        raise RecipeError(f"{what}: {e}", "", e.hint)


_C, _MIN = None, None


def _align():
    global _C, _MIN
    from build123d import Align
    _C, _MIN = Align.CENTER, Align.MIN


try:
    _align()
except Exception:                                   # importable without the kernel (the docs and tests read it)
    pass


# ---- picking: what the person clicked, as queries and standard sizes (a kernel op) ---------------------------------

def _hole_size(o: dict) -> dict:
    """The hole's diameters and their source, from the standard it names."""
    from . import parts
    std = o.get("standard") or ("tapped" if o.get("style") == "tapped" else "clearance")
    size = str(o.get("size") or "M3")
    out = {"standard": std}
    if std == "clearance":
        d, src = parts.clearance_d(size, o.get("fit") or "normal")
        out.update(d=d, source=f"{src}, {o.get('fit') or 'normal'}", size=size)
    elif std == "tapped":
        s = parts._size(size)
        if s not in parts.TAP_DRILL:
            raise RecipeError(f"No tap drill for {size} in the table", "", "Use M2 to M6, or a plain hole with its Ø.")
        out.update(d=parts.TAP_DRILL[s][0], source=parts.TAP_SOURCE + " (soft)", size=s,
                   pitch=parts.PITCH.get(s))
    elif std == "iso286":
        from .craft import fits
        nominal = float(o.get("nominal") or 0)
        code = str(o.get("fit") or "H7")
        import re
        m = re.fullmatch(r"([A-Z]{1,2})(\d{1,2})", code)
        if not m or nominal <= 0:
            raise RecipeError(f"An ISO 286 hole needs a nominal Ø and a hole tolerance such as H7 (got {code!r}, "
                              f"{nominal:g})", "", "For example nominal 8, fit H7.")
        lo, hi = fits.hole_limits(m.group(1), int(m.group(2)), nominal)
        out.update(d=round((lo + hi) / 2, 4), limits=[round(lo, 4), round(hi, 4)], nominal=nominal, fit=code,
                   source=f"{fits.SOURCE}: {code} on Ø{nominal:g}, modelled at mid-tolerance")
    elif std == "plain":
        d = float(o.get("d") or 0)
        if d <= 0:
            raise RecipeError("A plain hole needs its diameter", "", "Give d in mm.")
        out.update(d=d, source="given")
    else:
        raise RecipeError(f"Unknown hole standard {std!r}", "", "Use clearance, tapped, iso286 or plain.")
    style = o.get("style") or "plain"
    if style in ("counterbore", "countersink"):
        head = "socket" if style == "counterbore" else "countersunk"
        try:
            dk, k, src = parts.head_dims(out.get("size") or size, head)
        except RecipeError:
            dk, k, src = 0.0, 0.0, ""
        hc = float(o.get("head_clearance", 0.3))
        out.update(head_d=round(float(o.get("head_d") or dk + hc), 3),
                   head_depth=round(float(o.get("head_depth") or (k + hc if style == "counterbore" else 0)), 3),
                   head_source=(f"{src} + {hc:g} mm clearance" if src else "given"))
        if out["head_d"] <= out["d"]:
            raise RecipeError(f"No {head} head size for {out.get('size') or size}", "", "Give head_d (and head_depth).")
    return out


def _nearest_edge(body, at):
    from build123d import Vector
    v = Vector(*at)
    best = None
    for e in _edges(body):
        try:
            d = float(e.distance_to(v))
        except Exception:
            continue
        if best is None or d < best[0]:
            best = (d, e)
    return best


def _nearest_face(body, at):
    from build123d import Vector
    v = Vector(*at)
    best = None
    for f in body.faces():
        try:
            d = float(f.distance_to(v))
        except Exception:
            continue
        if best is None or d < best[0]:
            best = (d, f)
    return best


def op_model_pick(key, recipe_id, values, kind, picks, opts=None, tol=0.05):
    """Read picked points on the head as stable queries (form/modelling.py writes them into the feature's code).

    picks: [{"at": [x, y, z]}] near edges (fillet, chamfer) or on a face (hole, shell; at most one). Returns
    {"edges" | "face", "size" (holes), "box"}; every number computed on the B-rep."""
    from . import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    body = model["shape"]
    own = {hash(f["face"]): f["feature"] for f in model["faces"] if f.get("face") is not None}
    lo, sz = _box(body)
    o = dict(opts or {})
    out: dict = {"kind": kind, "evidence": EVIDENCE, "box": [list(lo), list(sz)]}
    if kind in ("fillet", "chamfer"):
        adj = _adjacency(body)
        rows, seen = [], set()
        for pk in picks or []:
            hit = _nearest_edge(body, pk.get("at") or [0, 0, 0])
            if hit is None:
                continue
            d, e = hit
            if d > max(1.0, 0.02 * max(sz)):
                raise RecipeError(f"No edge near ({', '.join(f'{x:.1f}' for x in pk['at'])}): the nearest is {d:.2f} mm "
                                  "away", "", "Pick on an edge (the annotate tool, Edge mode, shows it).")
            if hash(e) in seen:
                continue
            seen.add(hash(e))
            q = edge_query(e, adj, own, lo, sz)
            info = {"query": q, "length_mm": round(float(e.length), 3), "at": [round(x, 3) for x in _vec(e.center())]}
            if q.get("r"):
                info["radius_mm"] = q["r"]
            rows.append(info)
        if not rows:
            raise RecipeError(f"A {kind} needs at least one picked edge", "", "Pick the edges to round.")
        out["edges"] = rows
        out["shortest_mm"] = min(r["length_mm"] for r in rows)
    elif kind in ("hole", "shell"):
        if not picks:
            if kind == "shell":
                out["face"] = None
                return out
            raise RecipeError("A hole needs a picked face", "", "Click the flat face to drill into.")
        at = picks[0].get("at") or [0, 0, 0]
        d, f = _nearest_face(body, at)
        if d > 0.5:
            raise RecipeError("The picked point is not on the part", "", "Click on a face.")
        if kind == "hole" and f.geom_type.name != "PLANE":
            raise RecipeError(f"A hole goes into a flat face; this one is {f.geom_type.name.lower()}", "",
                              "Pick a flat face.")
        q = face_query(f, own, lo, sz)
        out["face"] = {"query": q, "area_mm2": round(float(f.area), 3), "at": [round(x, 4) for x in at]}
        if kind == "hole":
            out["size"] = _hole_size(o)
            n = q.get("normal") or [0, 0, 1]
            # how deep the part is under the point, along the hole: what "through" means here
            from build123d import Axis, Vector
            try:
                hits = body.find_intersection_points(Axis(tuple(Vector(*at) + Vector(*n) * 0.01), tuple(-x for x in n)))
                ds = sorted(float((Vector(*at) - h[0]).length) for h in hits)
                out["through_mm"] = round(max(ds), 3) if ds else None
            except Exception:
                out["through_mm"] = None
    else:
        raise RecipeError(f"Picking for {kind!r} is not a thing", "", "fillet, chamfer, hole or shell.")
    return out


KERNEL_OPS = {"model_pick": op_model_pick}
