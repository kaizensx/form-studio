"""The dimension loop of a gap, found on the B-rep (kernel worker only; imports OCCT).

``op_stack_loop`` takes two picked faces of a design and a direction, and returns the loop that sets the gap between
them, with the sensitivity of every link to every parameter:

1. **The gap.** Face A and face B, each picked by a point (as built, the frame selections use; or assembled) or by
   the index of a model face. The direction n is given, or is face A's outward normal (a face that bounds a gap
   faces into it). The gap is ``level(B) - level(A)`` along n, where a face's level is its extreme along n on the
   side facing the gap (exact for planes; OCCT's optimal bounding box in a frame whose Z is n for other faces).
2. **The mate graph.** Parts are nodes. A declared ``Mate`` is an edge along n when the two parts have an interface
   that holds them along n: a *seat* (two planar faces, normals opposite and along n, within SEAT_MM of each other:
   the lid on the rim, the screw head on the lid) or a *radial fit* (two coaxial cylinders whose axis is square to n:
   a pin in its hole, which lets the part float by the radial clearance). A thread or a pin along n holds nothing
   along n and is not an edge. Where the parts on either side are joined by no declared mate, seats found on the
   model between any two parts are edges too, labelled ``found`` (so an assembly declared without mates still has
   a loop), at a higher cost so a declared mate is always preferred.
3. **The loop.** The cheapest path through the graph from A's part to B's part (Dijkstra). In every part on it the
   *link* is the distance along n between the face it is entered by and the face it is left by; between parts the
   *interface term* is the seat's gap or the fit's offset. Their sum telescopes to the gap exactly (the closure is
   reported).
4. **Sensitivities.** Each parameter is nudged both ways (central difference, step h) and the design rebuilt by the
   kernel; every face of the loop is found again by its part, the feature that made it, its kind and its normal or
   axis, nearest to where it was in its part. ``d link / d parameter`` per part: a parameter that sizes two parts is
   two contributors, because each part is made on its own. Angles and any other geometry are handled the same way,
   because the derivative is taken on the real rebuild, not on a formula.
"""
from __future__ import annotations

import heapq
import math
import time

import numpy as np

SEAT_MM = 0.02           # two opposite faces this close along the loop seat on each other
COAXIAL_MM = 0.05        # two cylinder axes this close are one fit
PARALLEL = 0.9998        # |cos| for "along n" (about 1.1 degrees)
SQUARE = 0.0175          # |cos| under which an axis is square to n (1 degree)
FOUND_COST = 5.0         # a seat found on the model, with no Mate declared, costs this much more than a declared one


class LoopError(ValueError):
    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


# ---- geometry helpers ------------------------------------------------------------------------------------------
def _v(p) -> np.ndarray:
    """A build123d Vector or an OCP gp_Pnt / gp_Dir (whose X, Y, Z are methods) as an array."""
    xs = [getattr(p, a) for a in ("X", "Y", "Z")]
    return np.array([float(x() if callable(x) else x) for x in xs])


def _unit(d) -> np.ndarray:
    d = np.asarray(d, float)
    n = float(np.linalg.norm(d))
    if n < 1e-12:
        raise LoopError("The direction is zero.", "Give direction=[x, y, z].")
    return d / n


def _geom(face) -> str:
    return str(getattr(face.geom_type, "name", face.geom_type)).upper()


def _support(face, n) -> tuple:
    """(lowest, highest) of a face along n."""
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.Bnd import Bnd_Box
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf
    t = gp_Trsf()
    t.SetTransformation(gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(*[float(x) for x in n])))
    s = BRepBuilderAPI_Transform(face.wrapped, t, True).Shape()
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(s, b, False, False)
    return float(b.CornerMin().Z()), float(b.CornerMax().Z())


def _cyl(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    c = BRepAdaptor_Surface(face.wrapped).Cylinder()
    ax = c.Axis()
    return _v(ax.Location()), _unit(_v(ax.Direction())), float(c.Radius())


def _info(part: dict, j: int, owner: dict) -> dict:
    fp, fl = part["pfaces"][j], part["faces"][j]
    g = _geom(fl)
    mi, feat = owner.get(hash(fp), (-1, ""))
    c = _v(fl.center())
    rec = {"part": part["id"], "index": j, "model_face": mi, "feature": feat, "geom": g, "center": c,
           "center_as_built": _v(fp.center()), "local": _v(fp.center()) - part["lo"], "area": float(fl.area),
           "face": fl}
    if g == "PLANE":
        rec["normal"] = _unit(_v(fl.normal_at(fl.center())))
    elif g == "CYLINDER":
        o, u, r = _cyl(fl)
        rec.update({"origin": o, "axis": u, "radius": r})
    return rec


def _level(rec: dict, n, side: str) -> float:
    """A face's level along n: a plane square to n is one number; an axis (a fit) is its line; anything else its
    extreme on `side` ("max": the side facing +n, "min": facing -n)."""
    if rec.get("role") == "axis":
        return float(rec["origin"] @ n)
    if rec["geom"] == "PLANE" and abs(float(rec["normal"] @ n)) > PARALLEL:
        return float(rec["center"] @ n)
    lo, hi = _support(rec["face"], n)
    return hi if side == "max" else lo


# ---- the design's parts ----------------------------------------------------------------------------------------
def _parts(model) -> tuple:
    """[{id, label, printed, placed, faces (placed), pfaces (printed), lo}], the Assembly or None, and face owners."""
    from .. import assembly as asm
    a = asm.get(model)
    rows = []
    if a is None:
        solids = model["shape"].solids()
        if len(solids) != 1:
            raise LoopError("This design builds several solids and no assembly.", "Declare assembly() with Mate(...).")
        rows.append({"id": "design", "label": "Design", "printed": solids[0], "placed": solids[0], "material": ""})
        spec = None
    elif a.get("error"):
        raise LoopError("The assembly cannot be used: " + a["error"])
    else:
        spec = a["spec"]
        for pt, pr, pl in zip(spec.parts, a["printed"], a["placed"]):
            rows.append({"id": pt.id, "label": pt.label, "printed": pr, "placed": pl, "material": pt.material})
    for r in rows:
        r["pfaces"] = list(r["printed"].faces())
        r["faces"] = list(r["placed"].faces())
        b = r["printed"].bounding_box()
        r["lo"] = np.array([b.min.X, b.min.Y, b.min.Z])
    owner = {hash(f["face"]): (i, f["feature"]) for i, f in enumerate(model["faces"])}
    return rows, spec, owner


def _pick(parts, owner, sel: dict) -> dict:
    from build123d import Vector, Vertex
    if not isinstance(sel, dict):
        raise LoopError(f"A face is picked by a dict, got {sel!r}.", '{"at": [x, y, z]} or {"face": i}.')
    if "face" in sel:
        i = int(sel["face"])
        for p in parts:
            for j, fp in enumerate(p["pfaces"]):
                if owner.get(hash(fp), (-1,))[0] == i:
                    return _info(p, j, owner)
        raise LoopError(f"Face {i} is not a face of the design.", "Pick it by a point: {\"at\": [x, y, z]}.")
    if "at" not in sel:
        raise LoopError("A pick needs at=[x, y, z] (a point on the face) or face=i.")
    pt = Vertex(Vector(*[float(x) for x in sel["at"]]))
    frame = sel.get("frame", "as_built")
    if frame not in ("as_built", "assembled"):
        raise LoopError("frame is as_built (the part as printed, the frame selections use) or assembled.")
    want = _unit(sel["normal"]) if sel.get("normal") is not None else None
    best = None
    for p in parts:
        if sel.get("part") and p["id"] != sel["part"]:
            continue
        fs = p["pfaces"] if frame == "as_built" else p["faces"]
        for j, f in enumerate(fs):
            d = f.distance_to(pt)
            if best is not None and d >= best[0]:
                continue
            if want is not None:
                rec = _info(p, j, owner)
                if rec["geom"] != "PLANE" or float(rec["normal"] @ want) < PARALLEL:
                    continue
            best = (d, p, j)
    if best is None:
        raise LoopError(f"No face matches {sel}.", "Check the part id and the point.")
    if best[0] > 0.5:
        raise LoopError(f"The nearest face is {best[0]:.2f} mm from the point {sel['at']}.",
                        "Pick a point on the face (as built unless frame='assembled').")
    return _info(best[1], best[2], owner)


# ---- interfaces along n ----------------------------------------------------------------------------------------
def _seat(pa, pb, owner, n) -> dict | None:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    fa = [_info(pa, j, owner) for j, f in enumerate(pa["faces"]) if _geom(f) == "PLANE"]
    fb = [_info(pb, j, owner) for j, f in enumerate(pb["faces"]) if _geom(f) == "PLANE"]
    fa = [r for r in fa if abs(float(r["normal"] @ n)) > PARALLEL]
    fb = [r for r in fb if abs(float(r["normal"] @ n)) > PARALLEL]
    best = None
    for ra in fa:
        la = float(ra["center"] @ n)
        for rb in fb:
            if float(ra["normal"] @ rb["normal"]) > -PARALLEL:
                continue
            gap = float(rb["center"] @ n) - la
            if abs(gap) > SEAT_MM:
                continue
            dss = BRepExtrema_DistShapeShape(ra["face"].wrapped, rb["face"].wrapped)
            d = float(dss.Value()) if dss.IsDone() else math.inf
            if d > SEAT_MM + 1e-6:
                continue
            key = (round(d, 6), -min(ra["area"], rb["area"]))
            if best is None or key < best[0]:
                best = (key, ra, rb, gap)
    if best is None:
        return None
    _, ra, rb, gap = best
    return {"kind": "seat", "a": {**ra, "role": "seat"}, "b": {**rb, "role": "seat"}, "offset": gap}


def _radial(pa, pb, owner, n) -> dict | None:
    ca = [_info(pa, j, owner) for j, f in enumerate(pa["faces"]) if _geom(f) == "CYLINDER"]
    cb = [_info(pb, j, owner) for j, f in enumerate(pb["faces"]) if _geom(f) == "CYLINDER"]
    best = None
    for ra in ca:
        if abs(float(ra["axis"] @ n)) > SQUARE:
            continue
        for rb in cb:
            if abs(float(ra["axis"] @ rb["axis"])) < PARALLEL:
                continue
            w = rb["origin"] - ra["origin"]
            off = float(np.linalg.norm(w - (w @ ra["axis"]) * ra["axis"]))
            if off > COAXIAL_MM:
                continue
            fl = abs(ra["radius"] - rb["radius"])
            if best is None or fl < best[0]:
                best = (fl, ra, rb)
    if best is None:
        return None
    fl, ra, rb = best
    return {"kind": "fit", "a": {**ra, "role": "axis"}, "b": {**rb, "role": "axis"},
            "offset": float((rb["origin"] - ra["origin"]) @ n), "float": fl,
            "radii": [ra["radius"], rb["radius"]]}


def _interface(pa, pb, owner, n):
    return _seat(pa, pb, owner, n) or _radial(pa, pb, owner, n)


def _bbox_gap(pa, pb) -> float:
    a, b = pa["placed"].bounding_box(), pb["placed"].bounding_box()
    d = [max(0.0, a.min.X - b.max.X, b.min.X - a.max.X), max(0.0, a.min.Y - b.max.Y, b.min.Y - a.max.Y),
         max(0.0, a.min.Z - b.max.Z, b.min.Z - a.max.Z)]
    return math.sqrt(sum(x * x for x in d))


def _graph(parts, spec, owner, n) -> tuple:
    """Edges along n: {(a, b): interface}, and every mate with why it is or is not an edge."""
    idx = {p["id"]: i for i, p in enumerate(parts)}
    edges, mates, declared = {}, [], set()
    for m in (spec.mates if spec is not None else []):
        if m.a not in idx or m.b not in idx:
            continue
        declared.add(frozenset((m.a, m.b)))
        it = _interface(parts[idx[m.a]], parts[idx[m.b]], owner, n)
        row = {"a": m.a, "b": m.b, "kind": m.kind, "label": m.label, "clearance": m.clearance, "declared": True}
        if it is None:
            row["edge"] = False
            row["why"] = ("no seat (opposite faces along the gap's direction) and no radial fit square to it between "
                          "these parts: this mate does not hold them along the gap")
        else:
            row.update({"edge": True, "interface": it["kind"]})
            edges[(m.a, m.b)] = {**it, "mate": row, "cost": 1.0}
        mates.append(row)
    if len(parts) <= 40:
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                a, b = parts[i], parts[j]
                if frozenset((a["id"], b["id"])) in declared or _bbox_gap(a, b) > SEAT_MM:
                    continue
                it = _seat(a, b, owner, n)
                if it is not None:
                    row = {"a": a["id"], "b": b["id"], "kind": "contact", "label": "", "clearance": None,
                           "declared": False, "edge": True, "interface": "seat",
                           "why": "a seat found on the model; no Mate is declared between these parts"}
                    edges[(a["id"], b["id"])] = {**it, "mate": row, "cost": FOUND_COST}
                    mates.append(row)
    return edges, mates


def _path(edges, src: str, dst: str) -> list | None:
    """[(from part, to part, interface oriented from -> to)] of the cheapest path, or None."""
    adj = {}
    for (a, b), it in edges.items():
        adj.setdefault(a, []).append((b, it, False))
        adj.setdefault(b, []).append((a, it, True))
    dist, prev, q = {src: 0.0}, {}, [(0.0, src)]
    while q:
        d, u = heapq.heappop(q)
        if u == dst:
            break
        if d > dist.get(u, math.inf):
            continue
        for v, it, rev in sorted(adj.get(u, []), key=lambda x: x[0]):
            nd = d + it["cost"]
            if nd < dist.get(v, math.inf) - 1e-12:
                dist[v], prev[v] = nd, (u, it, rev)
                heapq.heappush(q, (nd, v))
    if dst not in dist:
        return None
    out, cur = [], dst
    while cur != src:
        u, it, rev = prev[cur]
        x, e = (it["b"], it["a"]) if rev else (it["a"], it["b"])
        out.append((u, cur, {**it, "x": x, "e": e, "offset": -it["offset"] if rev else it["offset"]}))
        cur = u
    return out[::-1]


# ---- the loop ------------------------------------------------------------------------------------------------
def _query(rec: dict) -> dict:
    q = {k: rec[k] for k in ("part", "feature", "geom", "local", "role") if k in rec}
    for k in ("normal", "axis", "radius"):
        if k in rec:
            q[k] = rec[k]
    q["side"] = rec.get("side")
    return q


def _refind(parts, owner, q: dict) -> dict | None:
    p = next((x for x in parts if x["id"] == q["part"]), None)
    if p is None:
        return None
    best = None
    for j, f in enumerate(p["faces"]):
        if _geom(f) != q["geom"]:
            continue
        r = _info(p, j, owner)
        if r["feature"] != q["feature"]:
            continue
        if "normal" in q and float(r["normal"] @ q["normal"]) < PARALLEL:
            continue
        if "axis" in q and abs(float(r["axis"] @ q["axis"])) < PARALLEL:
            continue
        d = float(np.linalg.norm(r["local"] - q["local"]))
        if best is None or d < best[0]:
            best = (d, r)
    if best is None:
        return None
    r = best[1]
    r["role"], r["side"] = q.get("role"), q.get("side")
    return r


def _links(chain_parts, faces_of, n) -> list:
    """Signed length of every part's link along n: level(exit) - level(entry)."""
    out = []
    for pid in chain_parts:
        e, x = faces_of[pid]
        out.append(_level(x, n, x.get("side") or "mid") - _level(e, n, e.get("side") or "mid"))
    return out


def _loop(model, a_sel, b_sel, direction):
    parts, spec, owner = _parts(model)
    A, B = _pick(parts, owner, a_sel), _pick(parts, owner, b_sel)
    if direction is not None:
        n, n_from = _unit(direction), "given"
    elif A["geom"] == "PLANE":
        n, n_from = A["normal"], "face A's outward normal (a face that bounds a gap faces into it)"
    else:
        raise LoopError("Face A is not planar, so it has no single normal to measure the gap along.",
                        "Give direction=[x, y, z].")
    A.update({"role": "end", "side": "max"})
    B.update({"role": "end", "side": "min"})
    lA, lB = _level(A, n, "max"), _level(B, n, "min")
    edges, mates = _graph(parts, spec, owner, n)
    path = [] if A["part"] == B["part"] else _path(edges, A["part"], B["part"])
    if path is None:
        raise LoopError(f"No chain of mates holds {A['part']} to {B['part']} along the gap's direction.",
                        "Declare Mate(a, b, ...) between the parts that touch, so each pair seats along the gap "
                        "(opposite faces) or fits on a pin square to it. The mates checked: "
                        + "; ".join(f"{m['a']}/{m['b']}: {m.get('why') or 'an edge'}" for m in mates))
    chain = [A["part"]] + [t for _, t, _ in path]
    entry, exit_ = {A["part"]: A}, {}
    for (u, v, it) in path:
        exit_[u] = {**it["x"]}
        entry[v] = {**it["e"]}
    exit_[B["part"]] = B
    faces_of = {pid: (entry[pid], exit_[pid]) for pid in chain}
    links = _links(chain, faces_of, n)
    terms = [it["offset"] for _, _, it in path]
    return {"parts": parts, "spec": spec, "owner": owner, "A": A, "B": B, "n": n, "n_from": n_from,
            "gap": lB - lA, "chain": chain, "path": path, "faces_of": faces_of, "links": links, "terms": terms,
            "mates": mates}


def _face_out(rec: dict, n) -> dict:
    out = {"part": rec["part"], "role": rec.get("role"), "feature": rec["feature"], "geom": rec["geom"],
           "model_face": rec["model_face"], "center": [round(float(x), 6) for x in rec["center"]],
           "center_as_built": [round(float(x), 6) for x in rec["center_as_built"]], "area_mm2": round(rec["area"], 4)}
    if "normal" in rec:
        out["normal"] = [round(float(x), 9) for x in rec["normal"]]
    if "axis" in rec:
        out.update({"axis": [round(float(x), 9) for x in rec["axis"]], "origin": [round(float(x), 6) for x in rec["origin"]],
                    "radius": round(rec["radius"], 6)})
    out["level"] = round(_level(rec, n, rec.get("side") or "mid"), 9)
    m = _face_mesh(rec.get("face"))
    if m:
        out["mesh"] = m
    return out


_MESHES: dict = {}


def _face_mesh(face, tol: float = 0.05) -> dict | None:
    """The face's own triangles in the assembled frame, for the viewport to light it (base64 float32 xyz, uint32)."""
    if face is None:
        return None
    k = id(face)
    if k in _MESHES and _MESHES[k][0] is face:
        return _MESHES[k][1]
    import base64
    try:
        vs, ts = face.tessellate(tol, 0.3)
    except Exception:                                    # noqa: BLE001 - a face that does not mesh is drawn as a cross
        return None
    if not vs or not ts:
        return None
    P = np.asarray([[v.X, v.Y, v.Z] for v in vs], np.float32)
    T = np.asarray(ts, np.uint32).reshape(-1, 3)
    m = {"positions": base64.b64encode(P.tobytes()).decode(), "indices": base64.b64encode(T.tobytes()).decode(),
         "triangles": int(len(T))}
    if len(_MESHES) > 64:
        _MESHES.clear()
    _MESHES[k] = (face, m)
    return m


def op_stack_loop(key, recipe_id, values, a, b, direction=None, params=None, budget_s: float = 90.0, tol: float = 0.1):
    """The loop of the gap between faces a and b, and d(link)/d(parameter) for every part on it.

    params: {key: step}: the parameters to nudge (central differences, ± step). Returns plain data (no OCCT)."""
    from .. import kernel
    from ..recipes import resolve
    model = kernel._get_near(key, recipe_id, values, tol)
    try:
        L = _loop(model, a, b, direction)
    except LoopError as e:
        return {"error": str(e), "hint": e.hint}
    n = L["n"]
    closure = sum(L["links"]) + sum(L["terms"]) - L["gap"]
    out = {"n": [float(x) for x in n], "direction_from": L["n_from"], "gap": L["gap"], "closure": closure,
           "chain": L["chain"], "links": [], "interfaces": [], "mates": L["mates"],
           "a": _face_out(L["A"], n), "b": _face_out(L["B"], n),
           "parts": [{"id": p["id"], "label": p["label"], "material": p["material"]} for p in L["parts"]],
           "sensitivity": {}, "skipped": {}}
    for pid, d in zip(L["chain"], L["links"]):
        e, x = L["faces_of"][pid]
        out["links"].append({"part": pid, "length": d, "entry": _face_out(e, n), "exit": _face_out(x, n)})
    for (u, v, it), off in zip(L["path"], L["terms"]):
        row = {"from": u, "to": v, "kind": it["kind"], "offset": off, "mate": it["mate"],
               "x": _face_out(it["x"], n), "e": _face_out(it["e"], n)}
        if it["kind"] == "fit":
            row.update({"float": it["float"], "radii": it["radii"]})
        out["interfaces"].append(row)
    queries = {pid: (_query(e), _query(x)) for pid, (e, x) in L["faces_of"].items()}
    recipe = resolve(recipe_id)
    v0 = recipe.validate(values)
    specs = {s.key: s for s in recipe.params}
    t0 = time.perf_counter()
    for k, h in (params or {}).items():
        if time.perf_counter() - t0 > budget_s:
            out["skipped"][k] = "time budget reached"
            continue
        if k not in v0 or not isinstance(v0[k], (int, float)):
            out["skipped"][k] = "not a numeric parameter"
            continue
        sp, base = specs.get(k), float(v0[k])
        hi_ok = sp is None or base + h <= sp.max + 1e-12
        lo_ok = sp is None or base - h >= sp.min - 1e-12
        steps = [s for s, ok in ((h, hi_ok), (-h, lo_ok)) if ok]
        if not steps:
            out["skipped"][k] = "its range is narrower than the step"
            continue
        got = {}
        for s in steps:
            vals = dict(v0)
            vals[k] = base + s
            try:
                m = kernel._build(recipe_id, vals, 0.5)
                ps, _, ow = _parts(m)
                fo = {}
                for pid, (qe, qx) in queries.items():
                    e, x = _refind(ps, ow, qe), _refind(ps, ow, qx)
                    if e is None or x is None:
                        raise LoopError(f"a face of {pid} on the loop was not found again")
                    fo[pid] = (e, x)
                got[s] = _links(L["chain"], fo, n)
            except Exception as e:  # noqa: BLE001 - a nudge that fails proves nothing; say why
                got[s] = f"{type(e).__name__}: {e}"[:200]
        bad = [g for g in got.values() if isinstance(g, str)]
        if bad:
            out["skipped"][k] = "the rebuild with it nudged failed: " + bad[0]
            continue
        if len(got) == 2:
            sens = [(p - q) / (2 * h) for p, q in zip(got[h], got[-h])]
            how = "central"
        else:
            s = steps[0]
            sens = [(p - q) / s for p, q in zip(got[s], out_links(out))]
            how = "one-sided (at the end of its range)"
        out["sensitivity"][k] = {"step": h, "how": how, "by_part": dict(zip(L["chain"], sens))}
    out["t_fd"] = round(time.perf_counter() - t0, 3)
    return out


def out_links(out: dict) -> list:
    return [x["length"] for x in out["links"]]


KERNEL_OPS = {"stack_loop": op_stack_loop}
