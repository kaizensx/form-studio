"""Assemblies in the kernel worker: placed parts, per-part meshes, and checks computed from the geometry.

Runs inside the worker only (imports OCCT). The contract a design declares is in form/recipes/assembly.py; the
mesh proximity and sweep engine is form/collide.py.

How the checks stay fast and bounded:
  * Every pair is compared on the kernel's tessellation first (bounding boxes, then a k-d tree of triangles, then
    exact triangle tests only where the parts come within a cutoff). The exact B-rep boolean runs only where the
    mesh says two parts touch or overlap, to measure the overlap volume.
  * Pairs that never move relative to each other in a sweep (both moving, or both still) are not compared again.
  * Pairs joined by design (``Mate``: a pin in its hole, a thread in a thread) are not booleaned; their gap is
    measured once and compared with the declared clearance.
  * A joint is swept coarsely at its declared samples, then bisected: until the clearance bound proves the motion
    free between samples, or until the first contact is located.
  * Everything runs against a time budget. What the budget did not reach is reported as not checked, by range.

Evidence class ``computed`` throughout: distances and overlaps measured on the model's tessellation (within the
stated mesh tolerance of the B-rep) and, where they overlap, by boolean intersection of the B-rep solids.
"""
from __future__ import annotations

import math
import time

import numpy as np

from .recipes import RecipeError
from .recipes.assembly import ROTARY

VOL_TOL = 0.01          # mm³; boolean noise on touching faces stays far below this
DEFAULT_BUDGET_S = 45.0
ASSEMBLY_VERSION = 2    # the method; part of the checks key (form/checks.py CHECKS_VERSION)


class Budget:
    def __init__(self, seconds: float):
        self.seconds = float(seconds)
        self.t0 = time.perf_counter()
        self.end = self.t0 + self.seconds

    def left(self) -> float:
        return self.end - time.perf_counter()

    def used(self) -> float:
        return time.perf_counter() - self.t0

    def over(self) -> bool:
        return self.left() <= 0


# ---- placement -----------------------------------------------------------------------------------------
def _loc_part(p):
    from build123d import Pos, Rot
    return Pos(*p.move) * Rot(*p.rotate)


def _loc_matrix(M):
    from build123d import Location
    from OCP.gp import gp_Trsf
    t = gp_Trsf()
    t.SetValues(*[float(M[r][c]) for r in range(3) for c in range(4)])
    return Location(t)


def _trsf_joint(j, value: float):
    """Location of a joint at `value` (degrees or mm), acting in the assembled frame."""
    from .recipes.assembly import joint_matrix
    return _loc_matrix(joint_matrix(j, value))


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
        # X, then Y, then Z: parts modelled in place on one axis (a gearbox's housing, suns and carriers) still get a
        # stable, documented order (bottom to top)
        return (round((b.min.X + b.max.X) / 2, 2), round((b.min.Y + b.max.Y) / 2, 2), round((b.min.Z + b.max.Z) / 2, 2))
    return sorted(shape.solids(), key=key)


def _resolve_points(spec, solids):
    """Parts given by a point (Part(solid=(x, y, z))) get the index of the solid that holds the point, else the
    nearest one."""
    if not any(isinstance(p.solid, (tuple, list)) for p in spec.parts):
        return spec
    from dataclasses import replace
    from build123d import Vector
    parts = []
    for p in spec.parts:
        if isinstance(p.solid, (tuple, list)) and len(p.solid) == 3:
            pt = Vector(*map(float, p.solid))
            inside = [i for i, s in enumerate(solids) if s.is_inside(pt)]
            if inside:
                idx = inside[0]
            else:
                from build123d import Vertex
                v = Vertex(pt)
                idx = min(range(len(solids)), key=lambda i: solids[i].distance_to(v))
            p = replace(p, solid=idx)
        parts.append(p)
    return replace(spec, parts=parts)


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
    spec = _resolve_points(spec, solids)
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
    if spec.derived:                                   # name each body after the feature that makes most of it
        spec = _name_derived(spec, model, face_part)
    model["_asm"] = {"spec": spec, "error": None, "printed": printed, "placed": placed, "locs": locs, "face_part": face_part}
    return model["_asm"]


def _name_derived(spec, model, face_part):
    """"Pebble base", "Thumb bolts 1", "Thumb bolts 2" instead of "Part 1"…: the label of the feature with the most
    surface on each body. The ids stay part1, part2… (they are what other tools store per part)."""
    from dataclasses import replace
    labels = {f.id: f.label for f in getattr(model["recipe"], "features", [])}
    area = {}
    for f, k in zip(model["faces"], face_part):
        if k >= 0:
            area.setdefault(k, {}).setdefault(f["feature"], 0.0)
            area[k][f["feature"]] += f.get("area", 0.0)
    names = [labels.get(max(area[k], key=area[k].get), "") if area.get(k) else "" for k in range(len(spec.parts))]
    seen = {n: names.count(n) for n in names}
    count, parts = {}, []
    for p, n in zip(spec.parts, names):
        if not n:
            parts.append(p)
            continue
        count[n] = count.get(n, 0) + 1
        parts.append(replace(p, label=f"{n} {count[n]}" if seen[n] > 1 else n))
    return replace(spec, parts=parts)


# ---- view payload ----------------------------------------------------------------------------------------
def mesh(model, b64, smooth=None) -> list:
    """Feature meshes split by part (print frame), each entry tagged with its part id. smooth(P, T) -> (P, T) shares
    vertices across gentle edges of a faceted solid (kernel.smooth_facets)."""
    a = get(model)
    ids = [p.id for p in a["spec"].parts]
    groups = {}
    for f, k in zip(model["faces"], a["face_part"]):
        g = groups.setdefault((f["feature"], k), {"P": [], "T": [], "n": 0})
        g["T"].append(f["T"] + g["n"])
        g["P"].append(f["P"])
        g["n"] += len(f["P"])
    out = []
    for (feat, k), g in groups.items():
        P, T = np.concatenate(g["P"]), np.concatenate(g["T"])
        if smooth is not None:
            P, T = smooth(P, T)
        out.append({"feature": feat, "part": ids[k] if k >= 0 else "",
                    "positions": b64(P.astype(np.float32)), "indices": b64(T.astype(np.uint32))})
    return out


def view(model, b64, edges_fn) -> dict:
    a = get(model)
    if a["error"]:
        return {"error": a["error"], "parts": []}
    spec, parts = a["spec"], []
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    elo, ehi = lo.copy(), hi.copy()
    for p, loc, printed, placed in zip(spec.parts, a["locs"], a["printed"], a["placed"]):
        bb = _bbox(placed)
        ex = spec.explode_total(p.id)
        lo, hi = np.minimum(lo, bb[0]), np.maximum(hi, bb[1])
        elo, ehi = np.minimum(elo, np.add(bb[0], ex)), np.maximum(ehi, np.add(bb[1], ex))
        parent, j = spec.link(p.id)
        parts.append({"id": p.id, "label": p.label, "solid": p.solid, "note": p.note, "material": p.material,
                      "placement": _placement_public(loc), "explode": list(p.explode), "explode_total": list(ex),
                      "parent": parent, "joint": j.id if j is not None else "", "attach": p.attach,
                      "chain": [x.id for x in spec.chain(p.id)], "bbox": bb,
                      "print_bbox": _bbox(printed), "volume_mm3": float(printed.volume), "edges": b64(edges_fn(printed))})
    out = spec.public()
    from .poses import anchor_of                      # the part that stays put when the set is pulled apart
    out.update({"error": None, "parts": parts, "anchor": anchor_of(parts), "bbox": [lo.tolist(), hi.tolist()],
                "bbox_exploded": [np.minimum(lo, elo).tolist(), np.maximum(hi, ehi).tolist()]})
    return out


# ---- exact B-rep measures (refinement) ------------------------------------------------------------------
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


# ---- meshes per part --------------------------------------------------------------------------------------
def bodies(model):
    """One collide.Body per part, in the print frame, from the model's tessellation (cached on the model)."""
    a = get(model)
    if "bodies" in a:
        return a["bodies"]
    from . import collide
    from .kernel import _tessellate
    tol = float(model.get("tol") or 0.05)
    out = {}
    for p, s in zip(a["spec"].parts, a["printed"]):
        P, T = _tessellate(s, tol)                     # reuses the model's triangulation when the solid is meshed
        out[p.id] = collide.Body(P, T, tol)
    a["bodies"] = out
    return out


def _frames(spec, pose=None) -> dict:
    return {p.id: spec.world(p.id, pose) for p in spec.parts}


def _placed_at(spec, a, pid, pose):
    """The B-rep of a part at a pose (assembled frame), for exact refinement."""
    k = [p.id for p in spec.parts].index(pid)
    if not pose or not spec.chain(pid):
        return a["placed"][k]
    return _loc_matrix(spec.motion(pid, pose)) * a["placed"][k]


def _w(M, p):
    return (np.asarray(M)[:3, :3] @ np.asarray(p, float) + np.asarray(M)[:3, 3]).tolist()


# ---- analysis ---------------------------------------------------------------------------------------------
def analyse(model, budget_s: float | None = None, progress=None) -> list:
    """Assembly checks as check rows (form/checks.py format). Empty when the design has no assembly.

    budget_s: seconds for everything here (the design's Assembly.budget_s wins, else DEFAULT_BUDGET_S).
    progress: called with {"phase", "label", "done", "total"} as the work goes."""
    a = get(model)
    if a is None or a["spec"].derived:                 # a derived view says nothing about how the parts meet
        return []
    if a["error"]:
        return [_check("asm_valid", "Assembly can be checked", "FAIL", "invalid", a["error"] +
                       " Fix assembly() in the design source.", frame=None)]
    from . import collide
    spec = a["spec"]
    bud = Budget(spec.budget_s or budget_s or DEFAULT_BUDGET_S)
    note = progress or (lambda _: None)
    parts, ids = spec.parts, [p.id for p in spec.parts]
    lab = {p.id: p.label for p in parts}
    out, timings = [], {}
    t = time.perf_counter()
    B = bodies(model)
    timings["mesh"] = time.perf_counter() - t
    tol2 = 2 * max((b.tol for b in B.values()), default=0.05)
    warn = spec.clearance_warn
    F0 = _frames(spec)
    skipped = []

    # ---- 1. at rest: every pair that is not joined by design --------------------------------------------------
    t = time.perf_counter()
    pairs = [(ids[i], ids[k]) for i in range(len(ids)) for k in range(i + 1, len(ids))]
    free = [(x, y) for x, y in pairs if spec.mate(x, y) is None]
    rows, worst, close, touching = [], None, None, []
    cutoff = max(1.0, 4 * warn)
    for n, (x, y) in enumerate(free):
        note({"phase": "rest", "label": "Parts at rest", "done": n, "total": len(free)})
        pair = f"{lab[x]} / {lab[y]}"
        if bud.over():
            skipped.append(pair)
            continue
        try:
            r = collide.query(B[x], B[y], np.linalg.inv(F0[y]) @ F0[x], cutoff, bud.end)
        except collide.OutOfTime:
            skipped.append(pair)
            continue
        st = r.state(tol2)
        row = {"pair": pair, "overlap_mm3": 0.0, "clearance_mm": round(r.d, 4) if r.exact else None,
               "clearance_at_least_mm": None if r.exact else round(r.d, 3), "state": st, "method": "mesh"}
        if (st in ("overlap", "contact") or (st == "gap" and r.d < tol2)) and not bud.over():
            vol, box = overlap(a["placed"][ids.index(x)], a["placed"][ids.index(y)])      # exact, where it matters
            row.update(overlap_mm3=round(vol, 4), method="mesh + B-rep boolean")
            row["state"] = st = "overlap" if box else ("contact" if st != "gap" else "gap")
            if box and (worst is None or vol > worst[0]):
                worst = (vol, box, pair, "B-rep boolean")
        elif st == "overlap":                          # out of time for the boolean: the mesh says so
            box = tuple(_w(F0[y], p) for p in r.box) if r.box else None
            if worst is None or worst[3] != "B-rep boolean":
                worst = (None, box, pair, f"mesh, penetration at least {r.depth:.2f} mm")
        if st == "contact":
            touching.append(pair)
            row["clearance_mm"] = 0.0
        if st == "gap" and (close is None or r.d < close[0]):
            close = (r.d, _w(F0[y], r.pa), _w(F0[y], r.pb), pair, x, y)
        rows.append(row)
    if close and close[0] < warn + tol2 and not bud.over():     # a tight gap: measure it on the B-rep
        d, p, q = clearance(a["placed"][ids.index(close[4])], a["placed"][ids.index(close[5])])
        close = (d, p, q, close[3], close[4], close[5])
        for row in rows:
            if row["pair"] == close[3]:
                row.update(clearance_mm=round(d, 4), method=row["method"] + " + B-rep distance")
    timings["rest"] = time.perf_counter() - t
    n_pairs, n_mated = len(pairs), len(pairs) - len(free)
    joined = f" {n_mated} pair{'s' if n_mated != 1 else ''} joined by design (see the fit checks) not booleaned." if n_mated else ""
    unreached = f" Not checked in the time budget: {', '.join(skipped)}." if skipped else ""
    if worst:
        v = f"{worst[0]:.2f} mm³" if worst[0] is not None else "overlap"
        out.append(_check("asm_interference", "Parts do not overlap when assembled", "FAIL", v,
                          f"{worst[2]} overlap" + (f" by {worst[0]:.2f} mm³ (boolean intersection of the solids)" if worst[0] is not None
                                                   else f" ({worst[3]})") + ". The marker spans the overlap." + joined + unreached,
                          at=worst[1][0] if worst[1] else None, to=worst[1][1] if worst[1] else None, pairs=rows))
    elif skipped:
        out.append(_check("asm_interference", "Parts do not overlap when assembled", "WARN", "partial",
                          f"No overlap in the {len(rows)} pair{'s' if len(rows) != 1 else ''} checked." + unreached + joined, pairs=rows))
    else:
        out.append(_check("asm_interference", "Parts do not overlap when assembled", "PASS", "0 mm³",
                          f"No overlap between any pair of parts ({len(rows)} pair{'s' if len(rows) != 1 else ''}) in the assembled state: "
                          f"compared on the mesh (±{tol2:.2f} mm), touching or overlapping pairs by boolean intersection of the solids."
                          + joined, pairs=rows))
    if close:
        tight = close[0] < warn
        out.append(_check("asm_clearance", "Smallest gap between parts", "WARN" if tight else "PASS", f"{close[0]:.2f} mm",
                          f"Closest approach: {close[3]}, {close[0]:.3f} mm"
                          + (" (B-rep distance)." if close[0] < warn + tol2 else f" (mesh distance, ±{tol2:.2f} mm).")
                          + (f" Under {warn:g} mm a printed gap may fuse or bind." if tight else "")
                          + (f" Resting contact (0 mm): {', '.join(touching)}." if touching else ""),
                          at=close[1], to=close[2]))
    elif touching:
        out.append(_check("asm_clearance", "Smallest gap between parts", "PASS", "contact only",
                          f"Parts rest on each other without overlap: {', '.join(touching)}.", pairs=rows))

    # ---- 2. pairs joined by design: their gap against the declared clearance ----------------------------------
    t = time.perf_counter()
    for n, m in enumerate(spec.mates):
        note({"phase": "fits", "label": "Joined parts", "done": n, "total": len(spec.mates)})
        out.append(_mate_row(m, lab, B, F0, tol2, warn, bud))
        fn = _function_row(m, a, ids, lab, bud)          # does it work: a thread engages, a ratchet locks
        if fn:
            out.append(fn)
    timings["fits"] = time.perf_counter() - t

    # ---- 3. joints: sweep each through its range, everything attached moving with it -------------------------
    moving_joints = [j for j in spec.joints if j.kind != "fixed"]
    for n, j in enumerate(moving_joints):
        t = time.perf_counter()
        share = Budget(max(0.0, bud.left()) / (len(moving_joints) - n))
        out.append(_sweep_row(j, spec, a, B, tol2, warn, share, lab, note, n, len(moving_joints)))
        timings[f"joint {j.id}"] = time.perf_counter() - t

    # ---- 4. hardware: straight tool access ---------------------------------------------------------------------
    t = time.perf_counter()
    k = 0
    for h in spec.hardware:
        upto = ids.index(h.after) + 1 if h.after else len(parts)
        for acc in h.access:
            k += 1
            cyl = _tool(acc)
            hits = []
            for i in range(upto):
                vol, box = overlap(cyl, a["placed"][i])
                if box:
                    hits.append((vol, box, parts[i].label))
            where = ", ".join(parts[i].label for i in range(upto))
            what = f"straight Ø{acc.tool_d:g} mm tool, {acc.length:g} mm along the {h.name} axis"
            if hits:
                vol, box, who = max(hits)
                out.append(_check(f"asm_access_{k}", f"Tool reaches {h.name}", "FAIL", f"blocked by {who}",
                                  f"A {what} intersects {who} ({vol:.1f} mm³). Checked against the parts in place when it is fitted: {where}. "
                                  "Does not model the handle or the hand.", at=box[0], to=box[1], pose={}))
            else:
                end = np.subtract(acc.at, np.multiply(_unit(acc.axis), acc.length)).tolist()
                out.append(_check(f"asm_access_{k}", f"Tool reaches {h.name}", "PASS", "clear",
                                  f"A {what} is clear of {where} (the parts in place when it is fitted). "
                                  "Does not model the handle or the hand.", at=list(acc.at), to=end))
    timings["access"] = time.perf_counter() - t

    # ---- 5. what the budget allowed ------------------------------------------------------------------------------
    partial = bool(skipped) or any(r.get("partial") for r in out)
    secs = {k: round(v, 2) for k, v in timings.items()}
    out.append(_check("asm_budget", "Assembly checks finished in their time budget", "WARN" if partial else "PASS",
                      f"{bud.used():.1f} s of {bud.seconds:g} s",
                      ("Stopped at the time budget: the rows marked partial say which ranges were not reached. "
                       "Raise [assembly].budget_s in studio.toml, or Assembly(budget_s=...) in the design, to check further. "
                       if partial else "Every check above ran to the end. ")
                      + "Time per stage: " + ", ".join(f"{k} {v:g} s" for k, v in secs.items()) + ".",
                      frame=None, seconds=secs, budget_s=bud.seconds, partial=partial))
    note({"phase": "done", "label": "Assembly checks", "done": 1, "total": 1})
    return out


def _function_row(m, a, ids, lab, bud):
    """A declared thread or ratchet, checked for what it is for (form/function_checks.py). None for other kinds, a
    mate without an axis, or when the budget is spent."""
    if m.kind not in ("thread", "ratchet") or m.axis is None or bud.over():
        return None
    from . import function_checks as fc
    sa, sb = a["placed"][ids.index(m.a)], a["placed"][ids.index(m.b)]
    pair = f"{lab[m.a]} / {lab[m.b]}"
    try:
        if m.kind == "thread":
            ra = fc._radial(sa, m.axis, m.origin)[0].min()
            rb = fc._radial(sb, m.axis, m.origin)[0].min()
            rod, nut = (sa, sb) if ra <= rb else (sb, sa)          # the screw is the one with material on the axis
            row = fc.thread_engagement(rod, nut, m.axis, m.origin, label=f"{m.label or pair}: thread engages",
                                       id_=f"fn_thread_{m.a}_{m.b}")
        else:
            row = fc.ratchet_engagement(sa, sb, m.axis, m.origin, 0.3 if m.clearance is None else max(0.0, m.clearance),
                                        label=f"{m.label or pair}: ratchet locks", id_=f"fn_ratchet_{m.a}_{m.b}")
            if m.clearance is None:
                row["detail"] += " Clearance not declared: 0.3 mm per side assumed (FDM)."
    except Exception as e:                             # noqa: BLE001 - a function check that cannot run says so
        return _check(f"fn_{m.kind}_{m.a}_{m.b}", f"{m.label or pair}: {m.kind} works", "WARN", "not measured",
                      f"The function check could not run: {type(e).__name__}: {e}", pose={})
    return dict(row, frame="assembled", pose={})


def _mate_row(m, lab, B, F0, tol2, warn, bud):
    from . import collide
    pair = f"{lab[m.a]} / {lab[m.b]}"
    rid, label = f"asm_fit_{m.a}_{m.b}", f"{m.label or pair}: {m.kind} fit"
    decl = "" if m.clearance is None else f" Declared clearance {m.clearance:g} mm per side."
    if bud.over():
        return _check(rid, label, "WARN", "not checked", f"Not reached in the time budget.{decl}", partial=True, pose={})
    cut = max(0.6, 3 * abs(m.clearance or 0.0) + tol2)
    try:
        r = collide.query(B[m.a], B[m.b], np.linalg.inv(F0[m.b]) @ F0[m.a], cut, bud.end)
    except collide.OutOfTime:
        return _check(rid, label, "WARN", "not checked", f"Not finished in the time budget.{decl}", partial=True, pose={})
    st = r.state(tol2)
    how = (f"{pair} are joined by design ({m.kind}), so they are not booleaned against each other; their gap is measured "
           f"once, at rest, on the mesh (±{tol2:.2f} mm).")
    if m.kind == "thread" and st == "overlap" and m.axis is not None:
        # a thread's phase in the model is arbitrary: turn it through a revolution and keep the phase that fits best
        from .recipes.assembly import Joint, joint_matrix
        turn = Joint("phase", "", m.a, "hinge", tuple(m.axis), tuple(m.origin))
        best = (r.depth, 0.0, r, st)
        for k in range(1, 36):
            if bud.over():
                break
            try:
                rk = collide.query(B[m.a], B[m.b], np.linalg.inv(F0[m.b]) @ joint_matrix(turn, 10.0 * k) @ F0[m.a], cut, bud.end)
            except collide.OutOfTime:
                break
            sk = rk.state(tol2)
            dk = rk.depth if sk == "overlap" else -rk.d
            if dk < best[0]:
                best = (dk, 10.0 * k, rk, sk)
        r, st = best[2], best[3]
        how += (" The modelled threads cross as placed; a thread's phase is arbitrary in the model, so the part was turned "
                f"about the thread axis through a revolution in 10° steps: the best phase is {best[1]:g}°"
                + (" (as placed)." if not best[1] else "."))
    at = {"at": _w(F0[m.b], r.pa), "to": _w(F0[m.b], r.pb)} if r.pa and not r.cross else {}
    if r.box and not at:                               # surfaces that cross: mark the region where they do
        at = {"at": _w(F0[m.b], r.box[0]), "to": _w(F0[m.b], r.box[1])}
    if m.kind == "press":
        v = f"{r.depth:.2f} mm" if st == "overlap" else (f"{r.d:.2f} mm gap" if r.exact else "loose")
        status = "PASS" if st in ("overlap", "contact") else "WARN"
        return _check(rid, label, status, v, how + (f" Interference at least {r.depth:.2f} mm." if st == "overlap" else
                                                     " The parts do not interfere: a press fit would be loose.") + decl, pose={}, **at)
    if st == "overlap" and m.kind == "thread" and m.axis is None:
        return _check(rid, label, "WARN", f"{r.depth:.2f} mm crossing", how + f" The modelled threads cross (at least "
                      f"{r.depth:.2f} mm). A thread's phase is arbitrary in the model, so this does not prove a clash; declare "
                      "Mate(..., axis=, origin=) to have the phase searched." + decl, pose={}, **at)
    if st == "overlap":
        return _check(rid, label, "FAIL", f"{r.depth:.2f} mm overlap", how + f" They overlap: at least {r.depth:.2f} mm deep. "
                      "The fit has no clearance left; enlarge the hole or shrink the pin/thread." + decl, pose={}, **at)
    if st == "contact":
        status = "WARN" if m.kind not in ("contact",) else "PASS"
        return _check(rid, label, status, "0 mm", how + f" They touch: no gap, or a crossing shallower than the mesh "
                      f"tolerance (±{tol2:.2f} mm), at the marker." +
                      ("" if m.kind == "contact" else " A head seating on its face touches by design; if the marker is on "
                       "the thread or the bore instead, that fit has no clearance and will bind when printed.") + decl,
                      pose={}, **at)
    if not r.exact:
        return _check(rid, label, "WARN", f"> {r.d:.2f} mm", how + f" No surfaces within {r.d:.2f} mm of each other: "
                      "check that they are placed where they meet." + decl, pose={})
    status, extra = "PASS", ""
    if r.d < warn:
        status, extra = "WARN", f" Under {warn:g} mm a printed fit may fuse or bind."
    elif m.clearance is not None and abs(r.d - m.clearance) > max(0.05, tol2):
        status, extra = "WARN", f" The model's gap differs from the declared {m.clearance:g} mm by more than the mesh tolerance."
    return _check(rid, label, status, f"{r.d:.2f} mm", how + f" Smallest gap {r.d:.3f} mm.{extra}{decl}", pose={}, **at)


def _sweep_row(j, spec, a, B, tol2, warn, bud, lab, note, n, total):
    from . import collide
    unit = "°" if j.kind in ROTARY else " mm"
    moving = spec.moved_by(j.id)
    still = [p.id for p in spec.parts if p.id not in moving]
    pairs = [(m, s) for m in moving for s in still if spec.mate(m, s) is None]
    mated = [(m, s) for m in moving for s in still if spec.mate(m, s) is not None]
    lo, hi = j.range
    detent = j.step > 0
    values = spec.detents(j) if detent else [float(x) for x in np.linspace(lo, hi, j.samples)]
    F0 = _frames(spec)
    travel = {m: collide.travel(B[m], F0[m], j.kind, j.axis, j.origin) for m in moving}
    others = {x.id: 0.0 for x in spec.joints}

    def frames(v):
        return _frames(spec, {**others, j.id: v})

    def tick(s):
        note({"phase": "joint", "label": j.label, "joint": j.id, "done": n, "total": total, "value": round(s.value, 3)})

    carried = [m for m in moving if m != j.part]
    who = lab[j.part] + (f" (carrying {', '.join(lab[m] for m in carried)})" if carried else "")
    if not pairs:
        return _check(f"asm_motion_{j.id}", f"{j.label} moves freely", "PASS", "nothing to hit",
                      f"{who} moves only relative to parts it is joined to by design; nothing else to check.",
                      samples=[], joint=j.id)
    res = collide.sweep(B, frames, pairs, values, lambda m, v1, v2: travel[m](v1, v2), tol=tol2, warn=warn,
                        cutoff=max(2.0, 4 * warn), deadline=bud.end, refine=not detent,
                        min_step=max(0.25, (hi - lo) / 240) if j.kind in ROTARY else max(0.1, (hi - lo) / 80),
                        max_evals=160, on_sample=tick)
    samples = []
    worst, near = None, None
    lifting = _lifting_off(res.samples)
    for s in res.samples:
        row = {"value": round(s.value, 3), "state": s.state, "overlap_mm3": 0.0,
               "depth_mm": round(s.depth, 3) if s.state == "overlap" and math.isfinite(s.depth) else None,
               "clearance_mm": round(s.clearance, 4) if s.exact else None,
               "clearance_at_least_mm": None if s.exact else round(s.clearance, 3),
               "with": (lab[s.pair[1]] if s.pair else ""), "refined": s.refined}
        samples.append(row)
        if s.state == "overlap" and (worst is None or s.depth > worst[0].depth):
            worst = (s, row)
        if s.state == "close" and abs(s.value) > 1e-9 and s.value not in lifting and (near is None or s.clearance < near.clearance):
            near = s
    method = (f"mesh proximity (±{tol2:.2f} mm)" + ("" if not worst else ", overlap volume by boolean intersection"))
    if detent:
        how = (f"{who} checked at the {len(spec.detents(j))} positions it can rest at (every {j.step:g}{unit} from "
               f"{lo:g} to {hi:g}{unit}); between them the detent rides over by design, so it is not swept.")
    else:
        how = f"{who} swept {lo:g}–{hi:g}{unit} " + ("about its axis" if j.kind in ROTARY else "along its slide direction")
        if res.unproven:
            iv = ", ".join(f"{x:g}–{y:g}{unit}" for x, y in res.unproven[:4]) + (" …" if len(res.unproven) > 4 else "")
            added = len(res.samples) - len(values)
            how += (f": {len(res.samples)} positions" + (f" ({len(values)} declared, {added} added where it matters)" if added > 0 else "")
                    + f"; between {iv} the "
                    "clearance was too small to prove freedom between samples (sampled only; does not prove continuous freedom there).")
        elif res.proven and not worst:
            how += (f": free over the whole range: at {len(res.samples)} positions the clearance exceeds how far any point can "
                    "travel between neighbouring positions, so no contact can hide between them.")
        else:
            how += f": sampled at {len(res.samples)} positions; does not prove continuous freedom between samples."
    if mated:
        how += " Not compared (joined by design): " + ", ".join(f"{lab[x]} / {lab[y]}" for x, y in mated) + "."
    if res.partial:
        cov = f"{res.covered[0]:g}–{res.covered[1]:g}{unit}" if res.covered else "nothing"
        how += f" PARTIAL: the time budget ran out; checked {cov}, not beyond."
    tail = {"samples": samples, "joint": j.id, "method": method, "moves": moving, "partial": res.partial,
            "checked": list(res.covered) if res.covered else None, "proven": [list(x) for x in res.proven],
            "unproven": [list(x) for x in res.unproven], "seconds": round(res.seconds, 2)}
    if worst:
        s, row = worst
        vol_txt = f"at least {s.depth:.2f} mm deep" if math.isfinite(s.depth) else "one part inside the other"
        if not bud.over():                         # the overlap volume at the worst position, on the B-rep
            x, y = s.pair
            pose = {**others, j.id: s.value}
            vol, box = overlap(_placed_at(spec, a, x, pose), _placed_at(spec, a, y, pose))
            if box:
                row["overlap_mm3"] = round(vol, 4)
                vol_txt = f"{vol:.2f} mm³"
                s.box = box
        first = res.contact_from
        loc = (f" First contact at {first:g}{unit}" + (f" (located to within {res.contact_res:.2f}{unit})" if res.contact_res else "") + "."
               if first is not None and not detent else "")
        return _check(f"asm_motion_{j.id}", f"{j.label} moves freely", "FAIL", f"{vol_txt} at {s.value:g}{unit}",
                      f"{lab[s.pair[0]]} hits {lab[s.pair[1]]} at {s.value:g}{unit} (worst overlap {vol_txt}).{loc} " + how,
                      at=s.box[0] if s.box else None, to=s.box[1] if s.box else None,
                      pose={"joint": j.id, "value": s.value}, first_contact=first, **tail)
    tight = near is not None and near.clearance < warn
    status = "WARN" if (tight or res.partial) else "PASS"
    if tight:
        value = f"{near.clearance:.2f} mm at {near.value:g}{unit}"
    elif res.partial:
        value = "partial"
    else:
        value = f"0 mm³ at {len(res.samples)} positions"
    closest = min((s for s in res.samples if s.exact and s.state in ("close", "clear") and abs(s.value) > 1e-9),
                  key=lambda s: s.clearance, default=None)
    detail = ("No overlap at any checked position"
              + (f"; closest approach {closest.clearance:.2f} mm at {closest.value:g}{unit} ({lab[closest.pair[0]]} / {lab[closest.pair[1]]})"
                 if closest else "")
              + (f", under {warn:g} mm: printed parts may rub there. " if tight else ". ") + how)
    extra = {"pose": {"joint": j.id, "value": near.value}, "at": near.pa, "to": near.pb} if tight else {}
    return _check(f"asm_motion_{j.id}", f"{j.label} moves freely", status, value, detail, **tail, **extra)


def _lifting_off(samples) -> set:
    """Values where a part that rests on another at 0 is just lifting off it: walking away from a resting contact at 0,
    the clearance only grows. A small gap there is the seat opening, not a rub."""
    by = sorted(samples, key=lambda s: s.value)
    vals = [s.value for s in by]
    if 0.0 not in vals or by[vals.index(0.0)].state != "contact":
        return set()
    out, k0 = set(), vals.index(0.0)
    for step in (1, -1):
        last, k = 0.0, k0 + step
        while 0 <= k < len(by) and by[k].exact and by[k].state in ("close", "clear") and by[k].clearance >= last - 1e-9:
            if by[k].state == "clear":
                break
            out.add(by[k].value)
            last, k = by[k].clearance, k + step
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
