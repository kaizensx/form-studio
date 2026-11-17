"""Assemblies in the kernel worker: placed parts, per-part meshes, and checks computed from the geometry.

Runs inside the worker only (imports OCCT). The contract a design declares is in form/recipes/assembly.py.

Every check here is evidence class ``computed``: booleans and distances between the real B-rep solids.
Motion is checked at discrete positions only; that never proves the motion is free between samples.
"""
from __future__ import annotations

import math

import numpy as np

from .recipes import RecipeError

VOL_TOL = 0.01          # mm³; boolean noise on touching faces stays far below this


# ---- placement -----------------------------------------------------------------------------------------
def _loc_part(p):
    from build123d import Pos, Rot
    return Pos(*p.move) * Rot(*p.rotate)


def _trsf_joint(j, value: float):
    """Location of a joint at `value` (degrees or mm), acting in the assembled frame."""
    from build123d import Location
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    t = gp_Trsf()
    n = math.sqrt(sum(a * a for a in j.axis))
    ax = [a / n for a in j.axis]
    if j.kind == "hinge":
        t.SetRotation(gp_Ax1(gp_Pnt(*j.origin), gp_Dir(*ax)), math.radians(value))
    else:
        t.SetTranslation(gp_Vec(*(a * value for a in ax)))
    return Location(t)


def _placement_public(loc) -> dict:
    t = loc.wrapped.Transformation()
    q = t.GetRotation()
    m = [[t.Value(r, c) for c in range(1, 5)] for r in range(1, 4)]
    return {"t": [m[0][3], m[1][3], m[2][3]], "q": [q.W(), q.X(), q.Y(), q.Z()], "m": m}


def _bbox(shape):
    b = shape.bounding_box()
    return [[b.min.X, b.min.Y, b.min.Z], [b.max.X, b.max.Y, b.max.Z]]


def _ordered_solids(shape):
    def key(s):
        b = s.bounding_box()
        return (round((b.min.X + b.max.X) / 2, 2), round((b.min.Y + b.max.Y) / 2, 2))
    return sorted(shape.solids(), key=key)


def get(model):
    """The design's assembly resolved against the built solid, cached on the model. None if it declares none."""
    if "_asm" in model:
        return model["_asm"]
    recipe, v = model["recipe"], model["values"]
    spec = recipe.assembly(v) if hasattr(recipe, "assembly") else None
    solids = _ordered_solids(model["shape"])
    if spec is None and len(solids) > 1:               # several bodies, no declaration: still give them a view
        from .recipes.assembly import from_solids
        spec = from_solids([_bbox(s) for s in solids])
    if spec is None:
        model["_asm"] = None
        return None
    problems = spec.validate(len(solids))
    if problems:
        model["_asm"] = {"spec": spec, "error": " ".join(problems)}
        return model["_asm"]
    locs = [_loc_part(p) for p in spec.parts]
    printed = [solids[p.solid] for p in spec.parts]
    placed = [loc * s for loc, s in zip(locs, printed)]
    owner = {}
    for i, s in enumerate(printed):
        for f in s.faces():
            owner[hash(f)] = i
    face_part = [owner.get(hash(f["face"]), -1) for f in model["faces"]]
    model["_asm"] = {"spec": spec, "error": None, "printed": printed, "placed": placed, "locs": locs, "face_part": face_part}
    return model["_asm"]


# ---- view payload ----------------------------------------------------------------------------------------
def mesh(model, b64) -> list:
    """Feature meshes split by part (print frame), each entry tagged with its part id."""
    a = get(model)
    ids = [p.id for p in a["spec"].parts]
    groups = {}
    for f, k in zip(model["faces"], a["face_part"]):
        g = groups.setdefault((f["feature"], k), {"P": [], "T": [], "n": 0})
        g["T"].append(f["T"] + g["n"])
        g["P"].append(f["P"])
        g["n"] += len(f["P"])
    return [{"feature": feat, "part": ids[k] if k >= 0 else "",
             "positions": b64(np.concatenate(g["P"]).astype(np.float32)),
             "indices": b64(np.concatenate(g["T"]).astype(np.uint32))} for (feat, k), g in groups.items()]


def view(model, b64, edges_fn) -> dict:
    a = get(model)
    if a["error"]:
        return {"error": a["error"], "parts": []}
    spec, parts = a["spec"], []
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    elo, ehi = lo.copy(), hi.copy()
    for p, loc, printed, placed in zip(spec.parts, a["locs"], a["printed"], a["placed"]):
        bb = _bbox(placed)
        lo, hi = np.minimum(lo, bb[0]), np.maximum(hi, bb[1])
        elo, ehi = np.minimum(elo, np.add(bb[0], p.explode)), np.maximum(ehi, np.add(bb[1], p.explode))
        parts.append({"id": p.id, "label": p.label, "solid": p.solid, "note": p.note, "material": p.material,
                      "placement": _placement_public(loc), "explode": list(p.explode), "bbox": bb,
                      "print_bbox": _bbox(printed), "volume_mm3": float(printed.volume), "edges": b64(edges_fn(printed))})
    out = spec.public()
    out.update({"error": None, "parts": parts, "bbox": [lo.tolist(), hi.tolist()],
                "bbox_exploded": [np.minimum(lo, elo).tolist(), np.maximum(hi, ehi).tolist()]})
    return out


# ---- geometry checks ----------------------------------------------------------------------------------
def _boxes_touch(a, b, pad=0.0) -> bool:
    A, B = a.bounding_box(), b.bounding_box()
    return not (A.max.X + pad < B.min.X or B.max.X + pad < A.min.X or A.max.Y + pad < B.min.Y or
                B.max.Y + pad < A.min.Y or A.max.Z + pad < B.min.Z or B.max.Z + pad < A.min.Z)


def overlap(a, b):
    """Volume (mm³) and bounding box of the boolean intersection of two solids."""
    if not _boxes_touch(a, b, 1e-6):
        return 0.0, None
    r = a.intersect(b)
    if r is None:
        return 0.0, None
    shapes = [s for s in (r if isinstance(r, list) else [r]) if s is not None]
    solids = [x for s in shapes for x in s.solids()]
    vol = float(sum(x.volume for x in solids))
    if vol <= VOL_TOL:
        return vol, None
    lo = np.min([_bbox(x)[0] for x in solids], axis=0).tolist()
    hi = np.max([_bbox(x)[1] for x in solids], axis=0).tolist()
    return vol, (lo, hi)


def clearance(a, b):
    d, p, q = a.distance_to_with_closest_points(b)
    return float(d), [p.X, p.Y, p.Z], [q.X, q.Y, q.Z]


def _check(id, label, status, value, detail, **kw):
    return {"id": id, "label": label, "status": status, "value": value, "detail": detail, "evidence": "computed",
            "frame": "assembled", **kw}


def analyse(model) -> list:
    """Assembly checks as check rows (form/checks.py format). Empty when the design has no assembly."""
    a = get(model)
    if a is None or a["spec"].derived:                 # a derived view says nothing about how the parts meet
        return []
    if a["error"]:
        return [_check("asm_valid", "Assembly can be checked", "FAIL", "invalid", a["error"] +
                       " Fix assembly() in the design source.", frame=None)]
    spec, placed = a["spec"], a["placed"]
    parts = spec.parts
    out = []

    # interference and clearance in the assembled state
    worst, rows, close = None, [], None
    for i in range(len(parts)):
        for k in range(i + 1, len(parts)):
            vol, box = overlap(placed[i], placed[k])
            d, p, q = clearance(placed[i], placed[k])
            pair = f"{parts[i].label} / {parts[k].label}"
            rows.append({"pair": pair, "overlap_mm3": round(vol, 4), "clearance_mm": round(d, 4)})
            if box and (worst is None or vol > worst[0]):
                worst = (vol, box, pair)
            if vol <= VOL_TOL and d > 1e-6 and (close is None or d < close[0]):
                close = (d, p, q, pair)
    n_pairs = len(rows)
    if worst:
        out.append(_check("asm_interference", "Parts do not overlap when assembled", "FAIL", f"{worst[0]:.2f} mm³",
                          f"{worst[2]} overlap by {worst[0]:.2f} mm³ (boolean intersection of the solids). The marker spans the overlap.",
                          at=worst[1][0], to=worst[1][1], pairs=rows))
    else:
        out.append(_check("asm_interference", "Parts do not overlap when assembled", "PASS", "0 mm³",
                          f"Boolean intersection of every pair of parts ({n_pairs} pair{'s' if n_pairs != 1 else ''}) in the assembled state is empty.",
                          pairs=rows))
    touching = [r["pair"] for r in rows if r["overlap_mm3"] <= VOL_TOL and r["clearance_mm"] <= 1e-6]
    if close:
        warn = close[0] < spec.clearance_warn
        out.append(_check("asm_clearance", "Smallest gap between parts", "WARN" if warn else "PASS", f"{close[0]:.2f} mm",
                          f"Closest approach: {close[3]}, {close[0]:.3f} mm (B-rep distance)."
                          + (f" Under {spec.clearance_warn:g} mm a printed gap may fuse or bind." if warn else "")
                          + (f" Resting contact (0 mm): {', '.join(touching)}." if touching else ""),
                          at=close[1], to=close[2]))
    elif touching:
        out.append(_check("asm_clearance", "Smallest gap between parts", "PASS", "contact only",
                          f"Parts rest on each other without overlap: {', '.join(touching)}.", pairs=rows))

    # joints: discrete sweep
    ids = [p.id for p in parts]
    for j in spec.joints:
        m = ids.index(j.part)
        lo, hi = j.range
        unit = "°" if j.kind == "hinge" else " mm"
        samples, bad, near = [], None, None
        for val in np.linspace(lo, hi, j.samples):
            moved = _trsf_joint(j, float(val)) * placed[m]
            row = {"value": round(float(val), 3), "overlap_mm3": 0.0, "clearance_mm": None, "with": ""}
            for k in range(len(parts)):
                if k == m:
                    continue
                vol, box = overlap(moved, placed[k])
                d, cp, cq = clearance(moved, placed[k]) if vol <= VOL_TOL else (0.0, None, None)
                if vol > row["overlap_mm3"]:
                    row["overlap_mm3"], row["with"] = round(vol, 4), parts[k].label
                    if bad is None or vol > bad[0]:
                        bad = (vol, float(val), box, parts[k].label)
                row["clearance_mm"] = d if row["clearance_mm"] is None else min(row["clearance_mm"], d)
                if vol <= VOL_TOL and abs(val) > 1e-9 and d > 1e-6 and (near is None or d < near[0]):
                    near = (d, float(val), cp, cq)
            row["clearance_mm"] = round(row["clearance_mm"], 4) if row["clearance_mm"] is not None else None
            samples.append(row)
        how = (f"{parts[m].label} swept {lo:g}–{hi:g}{unit} about its {'hinge axis' if j.kind == 'hinge' else 'slide direction'}, "
               f"sampled at {j.samples} positions; does not prove continuous freedom between samples.")
        if bad:
            out.append(_check(f"asm_motion_{j.id}", f"{j.label} moves freely", "FAIL", f"{bad[0]:.2f} mm³ at {bad[1]:g}{unit}",
                              f"{parts[m].label} hits {bad[3]} at {bad[1]:g}{unit} (worst sampled overlap {bad[0]:.2f} mm³). " + how,
                              at=bad[2][0], to=bad[2][1], pose={"joint": j.id, "value": bad[1]}, samples=samples, joint=j.id))
        else:
            tight = bool(near) and near[0] < spec.clearance_warn
            out.append(_check(f"asm_motion_{j.id}", f"{j.label} moves freely", "WARN" if tight else "PASS",
                              f"{near[0]:.2f} mm at {near[1]:g}{unit}" if tight else f"0 mm³ at {j.samples} positions",
                              "No overlap at any sampled position"
                              + (f"; closest approach {near[0]:.2f} mm at {near[1]:g}{unit}" if near else "")
                              + (f", under {spec.clearance_warn:g} mm: printed parts may rub there. " if tight else ". ") + how,
                              samples=samples, joint=j.id,
                              **({"pose": {"joint": j.id, "value": near[1]}, "at": near[2], "to": near[3]} if tight else {})))

    # hardware: straight tool access
    n = 0
    for h in spec.hardware:
        upto = ids.index(h.after) + 1 if h.after else len(parts)
        for acc in h.access:
            n += 1
            cyl = _tool(acc)
            hits = []
            for k in range(upto):
                vol, box = overlap(cyl, placed[k])
                if box:
                    hits.append((vol, box, parts[k].label))
            where = ", ".join(parts[k].label for k in range(upto))
            what = f"straight Ø{acc.tool_d:g} mm tool, {acc.length:g} mm along the {h.name} axis"
            if hits:
                vol, box, who = max(hits)
                out.append(_check(f"asm_access_{n}", f"Tool reaches {h.name}", "FAIL", f"blocked by {who}",
                                  f"A {what} intersects {who} ({vol:.1f} mm³). Checked against the parts in place when it is fitted: {where}. "
                                  "Does not model the handle or the hand.", at=box[0], to=box[1], pose={}))
            else:
                end = np.subtract(acc.at, np.multiply(_unit(acc.axis), acc.length)).tolist()
                out.append(_check(f"asm_access_{n}", f"Tool reaches {h.name}", "PASS", "clear",
                                  f"A {what} is clear of {where} (the parts in place when it is fitted). "
                                  "Does not model the handle or the hand.", at=list(acc.at), to=end))
    return out


def _unit(v):
    n = math.sqrt(sum(a * a for a in v)) or 1.0
    return [a / n for a in v]


def _tool(acc):
    from build123d import Align, Cylinder, Location, Plane
    d = [-a for a in _unit(acc.axis)]                 # the tool comes from the side opposite to the driving direction
    start = np.add(acc.at, np.multiply(d, 0.05))       # stop just short of the head seat
    pl = Plane(origin=tuple(start), z_dir=tuple(d))
    return Location(pl) * Cylinder(acc.tool_d / 2, acc.length, align=(Align.CENTER, Align.CENTER, Align.MIN))


def check_build(recipe, values):
    """Raise a RecipeError for an assembly whose declaration is unusable (called by tests and tools)."""
    spec = recipe.assembly(values)
    if spec is None:
        return None
    probs = spec.validate(recipe.solids)
    if probs:
        raise RecipeError(" ".join(probs), "", "Fix assembly() in the design source.")
    return spec
