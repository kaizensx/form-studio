"""Layer 2, the mixed result: what was recognised becomes features, what was not stays frozen. Beta.

Every other route answers all or nothing per part: the program route gives up below MIN_EXPLAINED of its walls, or
when one boolean of its kept slices fails; the feature tree gives up when a fillet or chamfer will not rebuild or its
time runs out; and then the result is Layer 1 or Layer 0, a solid with no Params at all, 0 % editable however much of
its surface was recognised (docs/RECON_EDITABILITY.md). This route never throws the
recognised part away:

1. Base: the verified solid (Layer 1 when it is within the tolerance, else Layer 0, whose coplanar facets are merged
   into real planes), kept exactly as a reference the recipe reads. It is the frozen patches.
2. Patterns first (patterns.py): teeth repeated round an axis become one tooth sketch extruded over the levels where
   it holds and a polar pattern of it; their band is cut from the base. The pattern's angle and phase are then fitted
   to the mesh (form.remodel.fitparams), and when it still is not within the tolerance it is dropped (the teeth stay
   frozen) and the residual (form.remodel.residual) is reported as the work that is left.
3. Faces: the base's planar faces, grouped by plane, become dimensions, largest first: a thickness to the nearest
   opposite face, a width between two mirrored faces (both move), or a level. A group is kept when moving it
   DIMENSION_MOVE builds one valid solid that changed (ops.push: the faces swept out or in).
4. Budget by predicted gain: each step's gain is the share of the surface it would make editable, its cost the time
   the steps so far took; spending stops when gain per second falls below MIN_RATE, at MAX_PARAMS, or at the deadline.
5. The recipe is built as the Studio builds it and compared with the mesh (two-sided Hausdorff). Editable (the share
   of the surface the kept Params move) is reported beside the share of Params that are dimensions that move.

Kernel worker only (build123d). Returns the same shape of result as program.recipe.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

MIN_RATE = 0.05            # % of the surface made editable per second of work below which spending stops
MIN_GAIN = 0.1             # % of the surface below which a face group is not worth a Param
MAX_PARAMS = 24            # face Params at most (each is rebuilt once to check that it moves)
DIMENSION_MOVE = 0.5       # mm: a Param is kept when it moves this far and the part still builds (program.py)
PATTERN_FIT_S = 20.0       # seconds the pattern's angle and phase may be fitted
AXES = "XYZ"


def _f(x: float) -> str:
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _vec(n) -> str:
    return "(" + ", ".join(_f(x) for x in n) + ")"


def face_groups(shape, tol) -> tuple[list, float]:
    """The planar faces of a solid grouped by plane: [{"n", "off", "area", "eps", "box" (2D bbox in the plane),
    "faces"}], largest first, and the solid's whole surface area."""
    from build123d import Shape
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_REVERSED
    sh = Shape.cast(shape) if not hasattr(shape, "faces") else shape
    groups, total = {}, 0.0
    snap = max(tol / 8, 1e-4)
    for f in sh.faces():
        a = float(f.area)
        total += a
        ad = BRepAdaptor_Surface(f.wrapped)
        if ad.GetType() != GeomAbs_Plane:
            continue
        pl = ad.Plane()
        d, o = pl.Axis().Direction(), pl.Location()
        n = np.array([d.X(), d.Y(), d.Z()])
        if f.wrapped.Orientation() == TopAbs_REVERSED:
            n = -n
        n[np.abs(n) < 1e-9] = 0.0
        off = float(n @ np.array([o.X(), o.Y(), o.Z()]))
        key = (tuple(np.round(n, 4)), int(round(off / snap)))
        bb = f.bounding_box()
        g = groups.setdefault(key, {"n": n, "offs": [], "area": 0.0, "faces": 0, "lo": None, "hi": None})
        g["offs"].append(off)
        g["area"] += a
        g["faces"] += 1
        lo, hi = np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])
        g["lo"] = lo if g["lo"] is None else np.minimum(g["lo"], lo)
        g["hi"] = hi if g["hi"] is None else np.maximum(g["hi"], hi)
    out = []
    for g in groups.values():
        offs = np.array(g["offs"])
        g["off"] = float(offs.mean())
        g["eps"] = float(max(1e-4, np.ptp(offs) + 1e-5))
        del g["offs"]
        out.append(g)
    out.sort(key=lambda g: -g["area"])
    return out, total


def _axis(n):
    k = int(np.argmax(np.abs(n)))
    return k if abs(abs(n[k]) - 1) < 1e-6 else None


def _overlap(a, b, n) -> float:
    """Overlap of two groups' bounding boxes seen along n (their extents across it), as a share of the smaller."""
    k = _axis(n)
    idx = [i for i in range(3) if i != k] if k is not None else [0, 1, 2]
    lo, hi = np.maximum(a["lo"][idx], b["lo"][idx]), np.minimum(a["hi"][idx], b["hi"][idx])
    inter = float(np.prod(np.clip(hi - lo, 0, None)))
    sa = float(np.prod(np.clip(a["hi"][idx] - a["lo"][idx], 1e-9, None)))
    sb = float(np.prod(np.clip(b["hi"][idx] - b["lo"][idx], 1e-9, None)))
    return inter / min(sa, sb)


def plan_faces(groups, total, centre, tol) -> list:
    """One Param per face group worth one (largest first): ("width", A, B) when B mirrors A about the part's centre,
    ("thickness", A, B) when B is the nearest opposite face across A, else ("level", A). Values are rounded to 0.1 µm
    here, once: the recipe's Param default and the value its code subtracts are then the same number, and at the
    defaults no face moves."""
    plans, moved = [], set()
    for i, a in enumerate(groups):
        if 100.0 * a["area"] / total < MIN_GAIN:
            break
        if i in moved:
            continue
        best = None
        for j, b in enumerate(groups):
            if j == i or float(a["n"] @ b["n"]) > -0.99999:
                continue
            dist = a["off"] + b["off"]
            if dist <= tol or _overlap(a, b, a["n"]) < 0.2:
                continue
            if best is None or dist < best[0]:
                best = (dist, j)
        if best is not None:
            j = best[1]
            b = groups[j]
            ca, cb = a["off"] - float(a["n"] @ centre), b["off"] - float(b["n"] @ centre)
            if j not in moved and abs(ca - cb) <= tol / 4 and abs(a["area"] - b["area"]) <= 0.25 * max(a["area"], b["area"]):
                plans.append({"kind": "width", "groups": [i, j], "value": round(best[0], 4)})
                moved |= {i, j}
                continue
            if j not in moved:
                plans.append({"kind": "thickness", "groups": [i], "value": round(best[0], 4), "to": j})
                moved.add(i)
                continue
        k = _axis(a["n"])
        sgn = float(np.sign(a["n"][k])) if k is not None else 1.0
        plans.append({"kind": "level", "groups": [i], "value": round(a["off"] * sgn, 4), "sign": sgn})
        moved.add(i)
    return plans


def _label(p, groups, k):
    a = groups[p["groups"][0]]
    ax = _axis(a["n"])
    along = f"along {AXES[ax]}" if ax is not None else "across the face " + _vec(np.round(a["n"], 3))
    if p["kind"] == "width":
        return f"Width {_f(round(p['value'], 4))} {along} · faces {k}"
    if p["kind"] == "thickness":
        return f"Thickness {_f(round(p['value'], 4))} {along} · face {k}"
    if ax is not None:
        return f"Level {AXES[ax]} {_f(round(p['value'], 4))} · face {k} ({'+' if a['n'][ax] > 0 else '-'}{AXES[ax]} side)"
    return f"Offset {_f(round(a['off'], 4))} · face {k}"


def _push_lines(p, groups, key, var="body"):
    """Code that applies Param `key` of plan p to `var`."""
    if p["kind"] == "width":
        out = []
        for gi in p["groups"]:
            g = groups[gi]
            out.append(f"{var} = push({var}, {_vec(g['n'])}, {_f(g['off'])}, (v[{key!r}] - {_f(p['value'])}) / 2, "
                       f"{g['eps']:.6g})")
        return out
    g = groups[p["groups"][0]]
    d = f"v[{key!r}] - {_f(p['value'])}" if p.get("sign", 1.0) > 0 else f"{_f(p['value'])} - v[{key!r}]"
    return [f"{var} = push({var}, {_vec(g['n'])}, {_f(g['off'])}, {d}, {g['eps']:.6g})"]


def _apply(body, p, groups, delta):
    from .ops import push
    if p["kind"] == "width":
        for gi in p["groups"]:
            g = groups[gi]
            body = push(body, g["n"], g["off"], delta / 2, g["eps"])
        return body
    g = groups[p["groups"][0]]
    return push(body, g["n"], g["off"], delta * p.get("sign", 1.0), g["eps"])


def _ok(sh, vol0) -> bool:
    try:
        return bool(sh.is_valid and len(sh.solids()) == 1 and abs(sh.volume - vol0) > 1e-6)
    except Exception:                                   # noqa: BLE001
        return False


# ---- the pattern ------------------------------------------------------------------------------------------------------

def _plane_code(k):
    from .patterns import frame
    x, z, _ = frame(k)
    return f"Plane(origin=(0, 0, 0), x_dir={_vec(x)}, z_dir={_vec(z)})"


def _tooth_sketch(pat, tol):
    """The tooth outline as lines and arcs (sketch.fit), in the plane's own coordinates, its middle on +x."""
    from . import sketch as sk
    from .patterns import frame
    _, _, sgn = frame(pat["axis"])
    T = np.asarray(pat["tooth"], dtype=np.float64).copy()
    T[:, 1] *= sgn
    lp = None
    for ft in (tol / 4, tol / 8, tol / 16, tol / 32):       # the fit's own error can exceed what it was asked for
        lp = sk.fit(T, ft, float(np.ptp(T, axis=0).max()))
        if lp is not None and lp.kind == "path" and lp.err <= tol / 4:
            break
        lp = None
    if lp is None:
        return None
    nodes = [(float(n.p[0]), float(n.p[1]), float(n.r)) for n in lp.nodes]
    edges = [None if e.kind == "line" else (float(e.R), bool(e.ccw), bool(e.large)) for e in lp.edges]
    return nodes, edges, float(lp.err)


def _pattern_lines(pat, sketch, S):
    """Code (and Params) of the pattern: the band cut from the base, then the tooth extruded and turned into place."""
    from .patterns import frame
    k = pat["axis"]
    _, _, sgn = frame(k)
    cx, cy = pat["centre"][0], pat["centre"][1] * sgn
    nodes, edges, _ = sketch
    first = pat["first_deg"] * sgn
    pitch = pat["pitch_deg"] * sgn
    a0 = min(first - pitch / 2, first + (pat["count"] - 0.5) * pitch)
    a1 = max(first - pitch / 2, first + (pat["count"] - 0.5) * pitch)
    za, zb = pat["za"], pat["zb"]
    ax = AXES[k]
    S["params"] += [
        ("teeth", pat["count"], 1, 2 * pat["count"] + 4, 1, "", f"Teeth {pat['count']} · pattern",
         "computed from the mesh: the run of equal teeth"),
        ("pitch", round(abs(pat["pitch_deg"]), 4), 1.0, 120.0, 0.05, "°", f"Pitch angle {_f(round(abs(pat['pitch_deg']), 3))}° · pattern",
         "computed from the mesh: the turn that lays each tooth onto the next"),
        ("phase", round(first % 360.0, 4), -360.0, 720.0, 0.05, "°", f"First tooth at {_f(round(first % 360.0, 3))}° · pattern",
         "computed from the mesh: the middle of the first tooth"),
        ("tooth_from", round(za, 4), round(za - 5, 4), round(zb - 0.1, 4), 0.01, "mm", f"Level {ax} {_f(round(za, 3))} · teeth from",
         "computed from the mesh: the lowest slab every tooth holds in"),
        ("tooth_to", round(zb, 4), round(za + 0.1, 4), round(zb + 5, 4), 0.01, "mm", f"Level {ax} {_f(round(zb, 3))} · teeth to",
         "computed from the mesh: the highest slab every tooth holds in"),
    ]
    nd = ", ".join(f"({_f(x)}, {_f(y)}, {_f(r)})" for x, y, r in nodes)
    ed = ", ".join("None" if e is None else f"({_f(e[0])}, {e[1]}, {e[2]})" for e in edges)
    sg = "1" if pitch > 0 else "-1"
    return [
        f"pl = {_plane_code(k)}",
        "_f = 'pattern'",
        f"# Teeth: the band they stand in is cut from the base, then one tooth sketch, extruded from {ax} levels "
        "tooth_from to tooth_to and turned into place once per pitch",
        f"body = body - slab(sector(pl.offset(v['tooth_from']), {_f(cx)}, {_f(cy)}, {_f(pat['r_cut'])}, "
        f"{_f(pat['r_out'] + 0.5)}, {_f(a0)}, {_f(a1)}), v['tooth_from'], v['tooth_to'])",
        f"tooth = slab(profile(Plane(origin=pl.from_local_coords(({_f(cx)}, {_f(cy)})) + pl.z_dir * v['tooth_from'], "
        f"x_dir=pl.x_dir, z_dir=pl.z_dir), [{nd}], [{ed}]), v['tooth_from'], v['tooth_to'])",
        "for _i in range(int(round(v['teeth']))):",
        f"    body = body + spin(tooth, pl, {_f(cx)}, {_f(cy)}, v['phase'] + {sg} * _i * v['pitch'])",
        "stages.append(Stage('pattern', body))",
    ]


# ---- the recipe -------------------------------------------------------------------------------------------------------

def source(name, ref, groups, plans, keys, pat_lines, pat_params, base_doc) -> str:
    params, feats, body = [], [], []
    feats.append(("base", "Kept as reconstructed", "structure",
                  base_doc + " Frozen: not driven by Params, except where the features below move its faces."))
    body += [f"body = self.reference({ref!r})", "stages.append(Stage('base', body))"]
    if pat_lines:
        feats.append(("pattern", "Tooth pattern", "structure",
                      "One tooth sketch extruded and repeated round its axis (a polar pattern); its band is cut from "
                      "the base first."))
        body += pat_lines
        for key, val, lo, hi, step, unit, label, note in pat_params:
            params.append(f"        Param({key!r}, {label!r}, {_f(val)}, {_f(lo)}, {_f(hi)}, {step}, {unit!r}, 'form', "
                          f"'pattern', {note!r}, provenance='mesh'),")
    for i, (p, key) in enumerate(zip(plans, keys)):
        fid = f"face{i + 1}"
        val = p["value"]
        if p["kind"] in ("width", "thickness"):
            lo, hi = max(0.05, 0.5 * val), val + max(2.0, 0.5 * val)
        else:
            lo, hi = val - max(2.0, 0.25 * abs(val)), val + max(2.0, 0.25 * abs(val))
        g = groups[p["groups"][0]]
        ax = _axis(g["n"])
        label = _label(p, groups, i + 1)
        note = "computed from the mesh: the plane of the base's faces" + (
            " on both sides, mirrored about the part's centre" if p["kind"] == "width" else "")
        params.append(f"        Param({key!r}, {label!r}, {_f(round(val, 4))}, {_f(round(lo, 4))}, {_f(round(hi, 4))}, 0.01, "
                      f"'mm', 'form', {fid!r}, {note!r}, provenance='mesh'),")
        what = {"width": "the faces on both sides move apart or together", "thickness": "the face moves, its opposite "
                "face stays", "level": "the face moves along its normal"}[p["kind"]]
        feats.append((fid, label.split(" · ")[0], "structure",
                      f"Faces of the base on one plane{' (' + AXES[ax] + ')' if ax is not None else ''}, pushed or pulled: "
                      f"{what}. Planes the Param moves are editable; their neighbours are not reshaped."))
        body.append(f"_f = {fid!r}")
        body += _push_lines(p, groups, key)
        body.append(f"stages.append(Stage({fid!r}, body))")
    doc = (f"{name}: reconstructed from a mesh by Form Studio (Layer 2, the mixed result, beta).\n\n"
           "What was recognised is a feature with Params: a pattern of teeth (one sketch, repeated) and planes moved "
           "by thickness, width and level dimensions. What was not stays the reconstructed solid's own faces, kept "
           "exactly (feature “base”).")
    return "\n".join([
        '"""' + doc + '\n"""',
        "from build123d import Plane",
        "",
        "from form.recipes.base import Feature, Param, Recipe, Stage",
        "from form.recon.ops import profile, push, sector, slab, spin",
        "",
        "",
        "class Design(Recipe):",
        f"    title = {(name + ' (reconstructed)')!r}",
        "    summary = 'Rebuilt from a mesh: recognised faces and patterns as features, the rest kept exactly.'",
        "    params = [",
        *params,
        "    ]",
        "    features = [",
        *[f"        Feature({fid!r}, {label!r}, {role!r}, {d!r})," for fid, label, role, d in feats],
        "    ]",
        "",
        "    def build(self, v):",
        "        stages = []",
        *["        " + x for x in body],
        "        return stages",
    ]) + "\n"


def recipe(V, F, base, tol, name="part", limit=None, out_dir=None, progress=None, deadline=None,
           base_doc="The reconstructed solid.") -> dict:
    """The mixed recipe on `base` (a TopoDS_Shape within the limit of the mesh). Returns {"report", "source",
    "verified", "shape", "P", "T", "cmp", "refs", "params", "dimensions"}."""
    from build123d import import_step
    from . import program, solid, verify
    from .pipeline import _step
    say = progress or (lambda d: None)
    t0 = time.perf_counter()
    limit = tol if limit is None else limit
    out = Path(out_dir or ".")
    out.mkdir(parents=True, exist_ok=True)
    rep = {"beta": True, "method": "mixed: recognised features on the kept solid", "kind": "program"}
    ref = f"{name}_mixed_base.step"
    _step(base, out / ref)
    refs = {ref: str(out / ref)}
    B = import_step(str(out / ref))
    B = B.solids()[0] if len(B.solids()) == 1 else B
    steps = []                                          # (what, gain %, seconds, kept)

    def left():
        return math.inf if deadline is None else deadline - time.perf_counter()

    # 2. patterns first
    pat, pat_lines, pat_params, body = None, [], [], B
    say({"stage": "layer2", "text": "Looking for repeated teeth (patterns first)", "fraction": 0.05})
    try:
        from . import patterns
        ts = time.perf_counter()
        pat = patterns.find(V, F, tol, deadline=None if deadline is None else min(deadline, ts + 20.0))
        if pat is not None:
            zz = patterns.levels(V, F, pat, tol, deadline)
            if zz is None:
                rep["pattern"] = {"found": True, "kept": False, "why": "no slab where every tooth holds"}
                pat = None
            else:
                pat["za"], pat["zb"] = zz
        if pat is not None:
            sk_ = _tooth_sketch(pat, tol)
            if sk_ is None:
                rep["pattern"] = {"found": True, "kept": False, "why": "the tooth does not read as lines and arcs"}
                pat = None
        if pat is not None:
            got = _fit_pattern(V, F, B, pat, sk_, tol, limit, refs, deadline)
            steps.append(("pattern", None, round(time.perf_counter() - ts, 2), got["ok"]))
            rep["pattern"] = got["report"]
            if got["ok"]:
                pat, pat_lines, pat_params, body = got["pat"], got["lines"], got["params"], got["body"]
            else:
                pat = None
    except Exception as e:                              # noqa: BLE001
        rep["pattern"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        pat = None

    # 3. faces, 4. budget by predicted gain
    say({"stage": "layer2", "text": "Turning recognised planes into dimensions", "fraction": 0.4})
    groups, total = face_groups(B, tol)
    centre = (np.min(V, axis=0) + np.max(V, axis=0)) / 2
    plans = plan_faces(groups, total, centre, tol)
    kept, keys, per = [], [], []
    vol_b = float(body.volume)
    for p in plans:
        gain = 100.0 * sum(groups[i]["area"] for i in p["groups"]) / total
        cost = float(np.median(per)) if per else 1.0
        why = None
        if len(kept) >= MAX_PARAMS:
            why = f"{MAX_PARAMS} face Params already"
        elif gain / max(cost, 1e-3) < MIN_RATE:
            why = f"predicted gain {gain:.2g}% in about {cost:.2g} s is below {MIN_RATE:g}% per second"
        elif left() < 2 * cost + 5.0:
            why = "the time budget ran out"
        if why:
            rep["stopped"] = why
            break
        ts = time.perf_counter()
        good = False
        for d in (DIMENSION_MOVE, -DIMENSION_MOVE):
            if p["value"] + d <= 0.05 and p["kind"] != "level":
                continue
            try:
                good = _ok(_apply(body, p, groups, d), vol_b)
            except Exception:                           # noqa: BLE001
                good = False
            p["move"] = d
            break
        dt = time.perf_counter() - ts
        per.append(dt)
        steps.append((p["kind"], round(gain, 3), round(dt, 2), good))
        if good:
            kept.append(p)
            keys.append(f"{p['kind'][0]}{len(kept)}")
    rep["budget"] = {"min_rate_pct_per_s": MIN_RATE, "steps": len(steps), "kept": len(kept),
                     "seconds": round(sum(s[2] for s in steps), 2)}

    if not kept and not pat_lines:                      # nothing recognised (or no time to check it): no recipe
        rep.update({"verified": False, "editable_pct": 0.0, "driven_by_params_pct": 0.0, "params": 0,
                    "face_groups": len(groups), "face_params": 0, "seconds": round(time.perf_counter() - t0, 2),
                    "error": "No face or pattern became a Param: " + rep.get("stopped", "none was recognised") + "."})
        return {"report": rep, "verified": False}

    # 5. build as the Studio does and verify
    say({"stage": "layer2", "text": f"Building {len(kept)} face features" + (" and a tooth pattern" if pat else "")
         + " and comparing with the mesh", "fraction": 0.85})
    def build(pl, pp):
        src_ = source(name, ref, groups, kept, keys, pl, pp, base_doc)
        stages, rec_ = program.build_stages(src_, refs)
        shape_ = stages[-1].shape
        ck_ = solid.check(shape_.wrapped)
        fl = []
        P_, T_ = solid.tessellate(shape_, max(tol / 10, 1e-4), faces_out=fl)
        cmp_ = verify.compare(V, F, P_, T_, shape=shape_.wrapped, check_above=limit, faces=fl)
        return src_, rec_, shape_, ck_, P_, T_, cmp_, bool(ck_["valid"] and ck_["solids"] == 1 and cmp_["hausdorff_mm"] <= limit)

    src, rec, shape, ck, P, T, cmp, ok = build(pat_lines, pat_params)
    if not ok and pat_lines:                            # measured in full the teeth are out: they stay in the base
        rep["pattern"] = {**rep.get("pattern", {}), "kept": False,
                          "why": f"measured in full the part is {cmp['hausdorff_mm']:.4f} mm from the mesh with the "
                                 "pattern"}
        pat, pat_lines, pat_params = None, [], []
        src, rec, shape, ck, P, T, cmp, ok = build(pat_lines, pat_params)
    area = sum(groups[i]["area"] for p in kept for i in p["groups"])
    pat_area = 0.0
    if pat is not None:
        pat_area = _pattern_area(shape, pat)
    final_area = float(sum(f.area for f in shape.faces())) or total
    edit = round(min(100.0, 100.0 * (area + pat_area) / final_area), 2)
    # the dimensions that move: each face Param was rebuilt above; the pattern's are rebuilt here, as the Studio does
    dims = _dimensions(rec, kept, keys, pat_params, refs)
    rep.update({"base": "kept solid", "valid": ck["valid"], "solids": ck["solids"],
                "volume_mm3": round(ck["volume_mm3"], 4),
                "verified": ok, "editable_pct": edit, "driven_by_params_pct": edit, "params": len(rec.params),
                "param_table": [{"key": q.key, "label": q.label, "value": q.default, "unit": q.unit}
                                for q in rec.params],
                "features": [{"id": f.id, "label": f.label} for f in rec.features],
                "face_groups": len(groups), "face_params": len(kept),
                "steps": [{"what": a, "gain_pct": g, "seconds": s, "kept": k} for a, g, s, k in steps][:60],
                **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")}})
    if not ok:
        rep["error"] = (f"The mixed recipe builds, but it is {cmp['hausdorff_mm']:.4f} mm from the mesh "
                        f"(limit {limit:.4f} mm)"
                        if ck["valid"] else "The mixed recipe builds an invalid solid.")
        rep["residual"] = _residual(V, F, P, T)
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    return {"report": rep, "source": src, "verified": ok, "shape": shape.wrapped, "P": P, "T": T, "cmp": cmp,
            "refs": refs, "params": rep["param_table"], "dimensions": dims}


def _pattern_area(shape, pat) -> float:
    """Area of the final solid's faces that the teeth make: inside the band, between their levels."""
    from .patterns import PLANE_UV
    k = pat["axis"]
    u, w = PLANE_UV[k]
    c = np.asarray(pat["centre"])
    tot = 0.0
    for f in shape.faces():
        m = f.center()
        p = np.array([m.X, m.Y, m.Z])
        if not (pat["za"] - 1e-6 <= p[k] <= pat["zb"] + 1e-6):
            continue
        r = float(np.hypot(p[u] - c[0], p[w] - c[1]))
        if pat["r_cut"] - 1e-6 <= r <= pat["r_out"] + 1e-3:
            a = math.degrees(math.atan2(p[w] - c[1], p[u] - c[0]))
            a0, a1 = pat["span_deg"]
            if (a - a0) % 360.0 <= (a1 - a0) % 360.0 + 1e-6:
                tot += float(f.area)
    return tot


def _fit_pattern(V, F, B, pat, sketch, tol, limit, refs, deadline) -> dict:
    """The pattern on the base, built and measured against the mesh where the teeth are; its angle and phase fitted
    (form.remodel.fitparams) when the first build is not within the limit. {"ok", "body", "lines", "params", "pat",
    "report"}."""
    from build123d import Plane  # noqa: F401
    from . import solid, verify
    from .ops import profile, sector, slab, spin                    # noqa: F401
    rep = {"found": True, "count": pat["count"], "pitch_deg": round(pat["pitch_deg"], 4), "axis": AXES[pat["axis"]],
           "levels": [round(pat["za"], 4), round(pat["zb"], 4)], "tooth_sketch_err_mm": round(sketch[2], 5),
           "matched_pct": float(pat.get("matched_pct", 0.0))}

    def build(p):
        S = {"params": []}
        lines = _pattern_lines(p, sketch, S)
        v = {key: val for key, val, *_ in S["params"]}
        env = {"Plane": Plane, "profile": profile, "sector": sector, "slab": slab, "spin": spin, "body": B, "v": v,
               "stages": [], "Stage": lambda *a: None}
        exec("\n".join(lines), env)                     # noqa: S102 - our own generated lines, as the recipe runs them
        return env["body"], lines, S["params"]

    diag = float(np.linalg.norm(np.ptp(V, axis=0)))

    def measure(body, full=False):                      # a quick look while fitting; the recipe is measured in full
        fl = []
        P, T = solid.tessellate(body, max(tol / 10, 1e-4), faces_out=fl)
        return verify.compare(V, F, P, T, spacing=None if full else max(diag / 80, 1e-3), shape=body.wrapped,
                              check_above=limit, faces=fl)["hausdorff_mm"]

    body, lines, params = build(pat)
    h = measure(body)
    rep["hausdorff_mm"] = round(h, 6)
    if h > limit and (deadline is None or time.perf_counter() < deadline - PATTERN_FIT_S):
        from ..remodel.fitparams import fit
        best = {"h": h, "p": pat}

        def evaluate(x):
            q = {**pat, "pitch_deg": float(x[0]), "first_deg": float(x[1])}
            try:
                hh = measure(build(q)[0])
            except Exception:                           # noqa: BLE001
                return None
            if hh < best["h"]:
                best.update(h=hh, p=q)
            return [hh]
        x0 = [pat["pitch_deg"], pat["first_deg"]]
        got = fit(evaluate, x0, [x0[0] - 0.5, x0[1] - 2.0], [x0[0] + 0.5, x0[1] + 2.0], [0.02, 0.05],
                  max_evals=16, budget_s=PATTERN_FIT_S)
        rep["fit"] = {"evals": got["evals"], "stopped": got["stopped"] or "converged",
                      "hausdorff_mm": round(best["h"], 6)}
        if best["h"] < h:
            pat = best["p"]
            body, lines, params = build(pat)
            h = best["h"]
    ok = bool(h <= limit)
    rep["kept"] = ok
    if not ok:
        rep["why"] = (f"with the pattern the part is {h:.4f} mm from the mesh (limit {limit:.4f} mm): the teeth stay "
                      "in the base")
    return {"ok": ok, "body": body, "lines": lines, "params": params, "pat": pat, "report": rep}


def _dimensions(rec, kept, keys, pat_params, refs) -> dict:
    """program.movable_dimensions' answer: the face Params were each rebuilt once above (only those that moved were
    kept); the pattern's dimensions (angles and levels) are rebuilt here from the recipe."""
    from .program import is_dimension
    from ..recipes import meshsolid
    out = {"params": len(rec.params), "dimensions": 0, "movable": 0, "checked": 0, "unchecked": 0, "keys": [],
           "move": DIMENSION_MOVE}
    face = {k: p for k, p in zip(keys, kept)}
    base = rec.defaults()
    meshsolid.set_paths(refs)
    try:
        for prm in rec.params:
            if not is_dimension(prm.key, prm.label, prm.unit):
                continue
            out["dimensions"] += 1
            out["checked"] += 1
            if prm.key in face:
                out["movable"] += 1
                out["keys"].append(prm.key)
                continue
            up = prm.max - prm.default >= DIMENSION_MOVE
            x = prm.default + DIMENSION_MOVE if up else prm.default - DIMENSION_MOVE
            try:
                sh = rec.build(rec.validate({**base, prm.key: x}))[-1].shape
                good = sh.is_valid and len(sh.solids()) == 1
            except Exception:                           # noqa: BLE001
                good = False
            if good:
                out["movable"] += 1
                out["keys"].append(prm.key)
    finally:
        meshsolid.set_paths({})
    return out


def _residual(V, F, P, T) -> dict:
    """What is left between the result and the mesh as a work list (form.remodel.residual). Never raises."""
    try:
        from ..remodel.residual import residual
        r = residual(V, F, P, T)
        return {k: r.get(k) for k in ("missing", "extra", "work", "summary") if r.get(k) is not None}
    except Exception as e:                              # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}
