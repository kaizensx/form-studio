"""Drag a face, change the parameter that drives it: direct manipulation mapped onto the design's own parameters.

When a person presses on a face in the viewport and pulls, the face should move the way the design allows: the box
gets taller, the wall thicker, the slot wider, the helmet's brow comes forward. Nothing is pushed by hand; the drag is
turned into a parameter value, and the design is rebuilt from it.

Which parameter: the face belongs to a feature (every face of a built design is attributed to the stage that made it,
form/kernel.py). The parameters are tried in order of attribution (those that name the face's feature first, then
the rest) by rebuilding the design with each moved a small step and measuring how far the surface under the pointer
moves along its normal (a ray through the picked point, so it is the face's own displacement, not a neighbour's). The
parameter that moves it most per unit is chosen; its rate (mm of face travel per unit of the parameter) turns the
drag distance into a value. This is a computed sensitivity (one finite difference per parameter), reported as such.

The app's viewport (FaceDrag.qml) asks once when the drag starts, then sets the parameter as the pointer moves; the
draft preview (Studio.preview) rebuilds and shows the impact (volume, mass, interfaces, fit) live.
"""
from __future__ import annotations

import math
import time

import numpy as np

MAX_TRIES = 24             # parameters rebuilt at most per question
MIN_RATE = 0.02            # mm of face travel per unit below which a parameter does not drive the face


def _ray_hits(shape, at, n, reach: float) -> list[tuple[float, np.ndarray]]:
    """Where the line at + s n crosses the shape's surface (|s| <= reach): [(s, the surface's unit normal there)]."""
    from build123d import Face, Vector
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    o = np.asarray(at, float) - reach * np.asarray(n, float)
    inter = BRepIntCurveSurface_Inter()
    inter.Init(shape.wrapped, gp_Lin(gp_Pnt(*map(float, o)), gp_Dir(*map(float, n))), 1e-7)
    out = []
    while inter.More():
        s = inter.W() - reach
        if abs(s) <= reach:
            p = inter.Pnt()
            try:
                v = Face(inter.Face()).normal_at(Vector(p.X(), p.Y(), p.Z()))
                nn = np.array([v.X, v.Y, v.Z])
            except Exception:
                nn = np.zeros(3)
            out.append((float(s), nn))
        inter.Next()
    return out


def _facing(hits, n):
    return sorted(s for s, nn in hits if float(np.dot(nn, n)) >= 0.866)


def _same_face(hits, n, s0: float, base: list | None = None):
    """The crossing that is still this face: facing the same way (outward normal within 30 degrees, so the wall's
    other side never counts) and, when the ray crosses several such faces (a ledge under the rim), the one in the
    same place in their order along the ray as before (faces do not pass each other in a small step); else the one
    nearest the original position."""
    ok = _facing(hits, n)
    if not ok:
        return None
    if base and len(base) == len(ok):
        k = min(range(len(base)), key=lambda i: abs(base[i] - s0))
        return ok[k]
    return min(ok, key=lambda x: abs(x - s0))


def _outward(shape, p, n, eps: float = 0.05):
    """n, turned to point out of the solid at p (a point just along it must be outside)."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    q = np.asarray(p, float) + eps * np.asarray(n, float)
    cl = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*map(float, q)), 1e-7)
    return -np.asarray(n, float) if cl.State() == TopAbs_IN else np.asarray(n, float)


def _shape_at(recipe, values: dict):
    v = recipe.validate(values)
    return recipe.build(v)[-1].shape


def _step(p, v: float) -> float:
    """A small change of parameter p from v that stays in range: 1 % of the range, at least one step."""
    d = max(float(p.step or 0.1), 0.01 * (p.max - p.min))
    d = min(d, max(p.max - p.min, 1e-6) / 4)
    return d if v + d <= p.max + 1e-9 else -d


def _allowance(c) -> bool:
    """A fit allowance (clearance, gap, tolerance): set for the printer and the fit, rarely what a drag means."""
    words = (c["key"] + " " + c["label"]).lower()
    return any(w in words for w in ("clear", "gap", "toleran", "allowance"))


def _flag(p) -> bool:
    """An on/off or count switch (0..1 or 0..2 in whole steps): never what a drag means."""
    return p.step >= 1 and p.max - p.min <= 2 and p.unit in ("", "count", "#")


def candidates(recipe, feature: str) -> list:
    """Numeric parameters in the order they are tried: the face's own feature first, then lengths before the rest
    (grouped: form, interface, brief, process); switches never."""
    order = {"form": 0, "interface": 1, "brief": 2, "process": 3}
    ps = [p for p in recipe.params if p.max > p.min and not _flag(p)]
    own = [p for p in ps if p.feature == feature]
    rest = sorted((p for p in ps if p.feature != feature), key=lambda p: (p.unit != "mm", order.get(p.group, 4)))
    return own + rest


def _volume(shape) -> float:
    try:
        return float(shape.volume)
    except Exception:
        return float("nan")


def sensitivity(recipe, values: dict, at, normal, feature: str = "", budget_s: float = 90.0, tries: int = MAX_TRIES,
                base_shape=None, face_area: float | None = None) -> dict:
    """How each parameter moves the surface at `at` along `normal`, and how much else it changes.

    rate: mm the face travels per unit of the parameter. locality: the solid's volume change over (face area x
    travel); 1 means only this face moved (pulling a box's top up by its height), more means the parameter also moves
    other faces (the floor thickness lifts the top and the floor). The chosen parameter moves the face (|rate| >= 0.2
    when any does) with the most local change; the face's own feature wins a near tie."""
    t0 = time.perf_counter()
    at = np.asarray(at, float)
    n = np.asarray(normal, float)
    n = n / (np.linalg.norm(n) or 1)
    base = base_shape if base_shape is not None else _shape_at(recipe, values)
    v_base = _volume(base)
    bb = base.bounding_box()
    reach = max(5.0, 0.25 * max(bb.size.X, bb.size.Y, bb.size.Z))
    hb = _ray_hits(base, at, n, reach)
    h0 = [x for x, _ in hb]
    s0 = min(h0, key=abs) if h0 else 0.0
    b0 = _facing(hb, n)
    area = face_area or 1.0
    out = []
    tried = 0
    for p in candidates(recipe, feature):
        if tried >= tries or time.perf_counter() - t0 > budget_s:
            break
        tried += 1
        v0 = float(values.get(p.key, p.default))
        d = _step(p, v0)
        try:
            shp = _shape_at(recipe, {**values, p.key: v0 + d})
        except Exception:
            try:
                d = -d
                shp = _shape_at(recipe, {**values, p.key: v0 + d})
            except Exception:
                continue
        hit = _same_face(_ray_hits(shp, at, n, reach), n, s0, b0)
        if hit is None:
            continue
        s = hit - s0
        rate = s / d
        if abs(rate) < MIN_RATE:
            continue
        dv = abs(_volume(shp) - v_base)
        loc = dv / max(area * abs(s), 1e-9) if math.isfinite(dv) else 99.0
        out.append({"key": p.key, "label": p.label, "unit": p.unit, "feature": p.feature, "group": p.group,
                    "value": v0, "min": p.min, "max": p.max, "step": p.step, "rate": round(rate, 6),
                    "locality": round(loc, 3), "own": p.feature == feature})

    def score(c):
        # most local first; the face's own feature, and a size rather than a fit allowance, win a near tie; then the
        # rate nearest one (the face moves with the value, not twice as fast)
        s = max(c["locality"], 1.0) * (0.8 if c["own"] else 1.0) / math.sqrt(min(1.0, abs(c["rate"])))
        s *= 1.5 if _allowance(c) else 1.0
        return (round(s, 2), abs(math.log(abs(c["rate"]))))
    strong = [c for c in out if abs(c["rate"]) >= 0.2] or out
    strong.sort(key=score)
    rest = [c for c in out if c not in strong]
    ranked = strong + sorted(rest, key=score)
    return {"best": ranked[0] if ranked else None, "candidates": ranked[:5], "tried": tried,
            "seconds": round(time.perf_counter() - t0, 3),
            "evidence": "computed (one rebuild per parameter: face travel along its normal, and volume change)"}


def op_drag_face(key, recipe_id, values, at, normal=None, tol=0.05):
    """Worker: the parameter that drives the face under `at` (design millimetres), and its rate."""
    from . import kernel
    from .selection import _Ctx
    model = kernel._get_near(key, recipe_id, values, tol)
    ctx = _Ctx(model, "as_modelled")
    if ctx.mesh:
        return {"best": None, "candidates": [], "reason": "A mesh design has no parameters behind its faces."}
    p = np.asarray(at, float)
    dist, fi, on, tk = ctx.nearest(p)
    face = model["faces"][fi]
    nrm = ctx.normal(fi, tk, on)
    if normal is not None and len(normal) == 3 and float(np.dot(nrm, normal)) < 0:
        nrm = -nrm                   # the viewer's normal points out of the part; a face's B-rep orientation may not
    elif normal is None:
        nrm = _outward(model["shape"], on, nrm)
    out = sensitivity(model["recipe"], model["values"], on, nrm, face["feature"], base_shape=model["shape"],
                      face_area=float(face["area"]))
    out.update({"feature": face["feature"], "at": [float(x) for x in on], "normal": [float(x) for x in nrm]})
    labels = {f.id: f.label for f in model["recipe"].features}
    out["feature_label"] = labels.get(face["feature"], face["feature"])
    return out


KERNEL_OPS = {"drag_face": op_drag_face}


# ── engine side ──────────────────────────────────────────────────────────────────────────────────────────────────

def find(st, p: dict, at, normal=None, rev: int | None = None) -> dict:
    """Which parameter a drag on the face at `at` changes (head revision by default)."""
    from .studio import StudioError
    try:
        at = [float(x) for x in at]
        assert len(at) == 3 and all(math.isfinite(x) for x in at)
    except Exception:
        raise StudioError("A face drag needs the point that was pressed: x, y, z in design millimetres.")
    r = st.rev(p, rev)
    out = st._k("drag_face", timeout=180, key=st.keys(p, r["n"])["geometry"], recipe_id=st.rid(p, r["n"]),
                values=r["values"], at=at, normal=normal, p=p)
    out.update({"rev": r["n"], "project": p["id"]})
    b = out.get("best")
    if b:
        out["text"] = (f"Dragging this face of {out.get('feature_label') or 'the part'} changes {b['label']}: "
                       f"{abs(b['rate']):.2f} mm of travel per {b['unit'] or 'unit'}.")
    else:
        out["text"] = "No parameter moves this face; it follows from the others."
    return out


def value_for(best: dict, travel_mm: float) -> float:
    """The parameter value for a drag of travel_mm along the face's normal (clamped to its range, on its step)."""
    v = best["value"] + travel_mm / best["rate"]
    st = best.get("step") or 0
    if st:
        v = round(v / st) * st
    return float(min(best["max"], max(best["min"], v)))


def probe(shape, origin, direction):
    """The first surface point a ray from `origin` along `direction` meets: (point, outward normal, face) or None.
    For tests and journeys that need a point on a particular face without a viewport."""
    from build123d import Face, Vector
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    inter = BRepIntCurveSurface_Inter()
    inter.Init(shape.wrapped, gp_Lin(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, direction))), 1e-7)
    best = None
    while inter.More():
        if inter.W() > 0 and (best is None or inter.W() < best[0]):
            p = inter.Pnt()
            best = (inter.W(), (p.X(), p.Y(), p.Z()), Face(inter.Face()))
        inter.Next()
    if best is None:
        return None
    _, p, f = best
    nv = f.normal_at(Vector(*p))
    nrm = np.array([nv.X, nv.Y, nv.Z])
    if np.dot(nrm, direction) > 0:                 # the ray meets an outside face from outside: normal against it
        nrm = -nrm
    return np.array(p), nrm, f
