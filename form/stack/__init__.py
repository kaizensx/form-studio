"""Tolerance stack-up from the assembly (wave Z): pick a gap, get its loop, its spread and what to tighten.

    from form import stack
    r = stack.compute(st, p, a={"at": [x, y, z]}, b={"at": [x, y, z]})       # nothing saved
    s = stack.define(st, pid, {"name": "Screw tip to hole floor", "a": ..., "b": ..., "spec": [0.3, None]})
    stack.run(st, pid, s["id"])                                               # computed and stored for the head
    stack.listing(st, p)                                                      # every stack with its state

What it does, in order (each step's evidence is in the result):

1. **The loop** (form/stack/kernel.py, in the kernel worker): the two faces, the direction, the chain of parts
   through the mate graph, each part's link and each interface, closure to the measured gap, and d(link)/d(parameter)
   for every part by central differences on the rebuilt CAD.
2. **Contributors.** One per (part, parameter) that moves the gap, one per radial fit on the loop (its float), and one
   per declared position or profile tolerance on a face of the loop. Each gets a tolerance from the first of:
   the request (``tolerances``), an ISO 286 class the drawing states for that size, the parameter's own provenance
   when it carries a sigma (a measured or specified value), the drawing's stated ISO 2768 class, the process
   (a printed part: the printer's calibration when it has one, else FDM ±0.2 mm, assumed), and otherwise ISO 2768-m,
   assumed. A stated tolerance is normal with ±3 sigma = the tolerance; an assumed one is uniform over its range.
3. **The stack** (form/stack/analysis.py): worst case, RSS and Monte Carlo (seeded), Cpk and the share out of spec,
   each contributor's share of the variance, and the tolerances whose tightening shrinks the spread most, with cost
   hints that are labelled assumed.
4. **Temperature.** Over ``t_min``..``t_max`` every part's link grows by its material's sourced expansion
   (form/material_library.py); a part with no sourced coefficient leaves the thermal result out and says what to give.
5. **Drawing data** (``draw``): the faces of the loop by model face index and part, each link and interface as a
   segment along the direction, for the viewport to light the loop on the parts.
"""
from __future__ import annotations

import json
import math
import time
import uuid

from . import analysis as AN

VERSION = 1
STACKS_FILE = "stacks.json"
EVIDENCE = "computed (linearised on the CAD rebuild; tolerances as labelled)"
FDM_TOL = 0.2                 # mm, assumed spread of a printed size without a calibration
FDM_ANGLE = 0.5               # degrees, assumed for a printed angle
STEP = {"mm": 0.01, "deg": 0.01}
T_REF = 20.0
SENS_ZERO = 1e-6
CONVERTED_GDT = ("position", "profile_surface", "profile_line")


class StackError(ValueError):
    def __init__(self, message: str, hint: str = "", status: int = 422):
        super().__init__(message)
        self.hint = hint
        self.status = status


def _serr(e):
    from ..studio import StudioError
    return StudioError(str(e), getattr(e, "hint", ""), status=getattr(e, "status", 422))


# ---- tolerances: where each one comes from ---------------------------------------------------------------------
def _given(tol, nominal_unit: str) -> tuple:
    """(lower, upper) from a request value: ±t, [lower, upper], or {"lower", "upper"}."""
    if isinstance(tol, (int, float)):
        t = abs(float(tol))
        return -t, t
    if isinstance(tol, (list, tuple)) and len(tol) == 2:
        lo, hi = float(tol[0]), float(tol[1])
        return min(lo, hi), max(lo, hi)
    if isinstance(tol, dict) and "lower" in tol and "upper" in tol:
        return float(tol["lower"]), float(tol["upper"])
    raise StackError(f"A tolerance is ±t, [lower, upper] or {{lower, upper}} (got {tol!r}).")


def _fit_for(param: str, spec_obj, value: float, drawing: dict):
    """An ISO 286 class the drawing states for this size: at={"param": key}, or a cylinder of the parameter's feature
    whose diameter is the value (or twice it, for a radius)."""
    for f in drawing.get("fits") or []:
        at = f.get("at") or {}
        cls = f.get("class")
        if not cls:
            continue
        if at.get("param") == param:
            return cls, 1.0
        if at.get("cylinder") and spec_obj is not None and at.get("feature") and at.get("feature") == spec_obj.feature:
            d = at.get("d")
            if d is None or abs(float(d) - value) < 1e-6:
                return cls, 1.0
            if abs(float(d) - 2 * value) < 1e-6:
                return cls, 0.5
    return None


def tolerance_of(param: str, part: str, value: float, unit: str, spec_obj, ctx: dict) -> dict:
    """{lower, upper, dist, evidence, source, rule} for one parameter of one part. ctx: request, drawing, provenance,
    purpose, calibration."""
    req = ctx.get("tolerances") or {}
    dists = ctx.get("dist") or {}
    key = f"{part}:{param}"
    dist_req = dists.get(key, dists.get(param))
    if key in req or param in req:
        lo, hi = _given(req.get(key, req.get(param)), unit)
        return {"lower": lo, "upper": hi, "dist": dist_req or "normal", "evidence": "specified",
                "source": "given in the request", "rule": "as given"}
    drawing = ctx.get("drawing") or {}
    fit = _fit_for(param, spec_obj, value, drawing) if unit == "mm" else None
    if fit:
        from .. import iso286 as I
        cls, scale = fit
        d = value / scale
        try:
            lim = I.limits(cls, d)
        except I.FitError as e:
            raise StackError(f"The drawing's fit {cls} on {param} cannot be used: {e}",
                             "Give the size its own tolerance (tolerances=) or a class ISO 286 tabulates here.") from None
        return {"lower": lim["lower_um"] / 1000 * scale, "upper": lim["upper_um"] / 1000 * scale,
                "dist": dist_req or "normal", "evidence": "specified", "source": lim["source"],
                "rule": f"ISO 286 {lim['class']} at Ø{d:g} stated on the drawing" + (" (half: the parameter is a radius)" if scale != 1 else "")}
    prov = (ctx.get("provenance") or {}).get(param) or {}
    if isinstance(prov.get("sigma"), (int, float)) and prov["sigma"] > 0:
        s = float(prov["sigma"])
        return {"lower": -3 * s, "upper": 3 * s, "dist": dist_req or "normal", "evidence": prov.get("source", "specified"),
                "source": "the parameter's provenance" + (f" ({prov['instrument']})" if prov.get("instrument") else ""),
                "rule": f"±3 sigma with the provenance's sigma {s:g}"}
    general = drawing.get("general")
    if general and unit in ("mm", "deg"):
        return _iso2768(value, unit, general, dist_req, stated=True)
    if ctx.get("purpose") == "print":
        cal = ctx.get("calibration") or {}
        if unit == "mm" and cal.get("source") == "calibrated":
            s = float(cal["sigma"])
            return {"lower": -3 * s, "upper": 3 * s, "dist": dist_req or "normal", "evidence": "calibrated",
                    "source": f"printer calibration, {cal.get('n')} measured widths ({cal.get('profile', '')})",
                    "rule": "±3 sigma of the printer's measured spread"}
        t = FDM_TOL if unit == "mm" else FDM_ANGLE
        return {"lower": -t, "upper": t, "dist": dist_req or "uniform", "evidence": "assumed",
                "source": "process capability, FDM",
                "rule": f"FDM ±{t:g} {unit} assumed (no calibration for this printer; a fit coupon measures it)"}
    return _iso2768(value, unit, "m", dist_req, stated=False)


def _iso2768(value: float, unit: str, cls: str, dist_req, stated: bool) -> dict:
    from ..drawing import standards as STD
    try:
        if unit == "deg":
            t = STD.general_angle(0.0, cls)
            how = f"ISO 2768-{cls} angle, the shortest-side band (the largest: the side length is not known here)"
        else:
            t = STD.general_linear(abs(value), cls)
            how = f"ISO 2768-{cls} linear, {abs(value):g} mm"
    except STD.StandardError as e:
        return {"lower": 0.0, "upper": 0.0, "dist": "normal", "evidence": "assumed", "source": "ISO 2768-1",
                "rule": f"no general tolerance: {e}; give this size its own tolerance"}
    return {"lower": -t, "upper": t, "dist": dist_req or ("normal" if stated else "uniform"),
            "evidence": "specified" if stated else "assumed", "source": "ISO 2768-1:1989 general tolerances",
            "rule": how + (" (stated on the drawing)" if stated else " (the drawing states no class: m assumed)")}


# ---- materials ---------------------------------------------------------------------------------------------------
def _material(p: dict, part: dict) -> tuple:
    from .. import materials
    own = ((p.get("parts") or {}).get(part["id"]) or {}).get("material") if part["id"] != "design" else None
    for m, how in ((own, "chosen for this part"), (part.get("material"), "declared in the design's code"),
                   (p.get("material"), "chosen for the design")):
        k = materials._key(m) if m else None
        if k:
            return k, how
    return None, None


def _alpha(p: dict, part: dict, given: dict) -> dict:
    from .. import material_library as ml
    if part["id"] in given or "*" in given:
        return {"value": float(given.get(part["id"], given.get("*"))), "evidence": "specified",
                "source": "given in the request"}
    k, how = _material(p, part)
    if not k:
        return {"value": None, "why": f"{part['id']} has no material; give alpha={{'{part['id']}': 1/K}} or choose one"}
    try:
        pr = ml.prop(k, "cte")
    except KeyError:
        return {"value": None, "material": k, "why": f"unknown material {k}"}
    if pr.get("status") or pr.get("value") is None:
        return {"value": None, "material": k,
                "why": f"no source in the library gives the expansion of {k}; give alpha={{'{part['id']}': 1/K}} "
                       "from its datasheet (it is not assumed)"}
    return {"value": float(pr["value"]), "material": k, "material_from": how, "evidence": "specified",
            "source": pr["source"], "url": pr.get("url"), "condition": pr.get("condition", "")}


# ---- the computation -----------------------------------------------------------------------------------------
def _num(x, name):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise StackError(f"{name} must be a number (got {x!r}).") from None
    if v != v or abs(v) == math.inf:
        raise StackError(f"{name} must be finite.")
    return v


def _calibration(st, p) -> dict:
    try:
        prof = st.profile(p)
        return {**st.calibration.correction(prof), "profile": prof}
    except Exception:                       # noqa: BLE001 - no slicer here: no calibration to read
        return {"source": "assumed", "n": 0}


def _ctx(st, p: dict, r: dict, d: dict) -> dict:
    from .. import drawing as D
    try:
        dspec = D.merged_spec(st, p, r["n"])
    except Exception:                       # noqa: BLE001 - a drawing() that raises declares nothing
        dspec = {}
    purpose = p.get("purpose") or "model"
    return {"tolerances": d.get("tolerances") or {}, "dist": d.get("dist") or {}, "drawing": dspec,
            "provenance": r.get("provenance") or {}, "purpose": purpose,
            "calibration": _calibration(st, p) if purpose == "print" else {}}


def _params(recipe, values: dict, include=None, exclude=None) -> dict:
    out = {}
    for s in getattr(recipe, "params", []) or []:
        unit = "deg" if s.unit in ("deg", "°", "degrees") else s.unit
        if unit not in STEP or not isinstance(values.get(s.key), (int, float)):
            continue
        if exclude and s.key in exclude:
            continue
        if include and s.key not in include:
            continue
        out[s.key] = STEP[unit]
    return out


def compute(st, p: dict, a: dict, b: dict, direction=None, tolerances: dict | None = None, dist: dict | None = None,
            spec=None, t_min=None, t_max=None, alpha: dict | None = None, samples: int = AN.DEFAULT_SAMPLES,
            seed: int = AN.DEFAULT_SEED, params: list | None = None, exclude: list | None = None,
            rev: int | None = None, name: str = "", budget_s: float = 120.0) -> dict:
    """The stack of the gap between faces a and b of a revision (head by default). Nothing is saved."""
    r = st.rev(p, rev)
    n = r["n"]
    recipe = st.recipe(p, n)
    values = r["values"]
    specs = {s.key: s for s in recipe.params}
    d = {"tolerances": tolerances, "dist": dist}
    for k, v in (dist or {}).items():
        if v not in AN.DISTS:
            raise StackError(f"dist[{k}] is normal or uniform (got {v!r}).")
    ctx = _ctx(st, p, r, d)
    steps = _params(recipe, values, params, exclude)
    gk = st.keys(p, n)["geometry"]
    t0 = time.perf_counter()
    raw = st._k("stack_loop", timeout=max(120.0, budget_s * 2 + 60), key=gk, recipe_id=st.rid(p, n), values=values,
                p=p, rev=n, a=a, b=b, direction=list(direction) if direction is not None else None, params=steps,
                budget_s=budget_s)
    if raw.get("error"):
        raise StackError(raw["error"], raw.get("hint", ""))
    # each face's triangles go to `draw` only (the viewport lights the faces of the loop); the rest stays plain numbers
    meshes = {}
    for f in [raw["a"], raw["b"]] + [L[k] for L in raw["links"] for k in ("entry", "exit")] \
            + [it[k] for it in raw["interfaces"] for k in ("x", "e")]:
        m = f.pop("mesh", None)
        if m:
            meshes[(f["part"], f["model_face"])] = m
    nominal = float(raw["gap"])
    # contributors -------------------------------------------------------------------------------------------
    contributors, flat = [], []
    unit_of = {k: ("deg" if specs[k].unit in ("deg", "°", "degrees") else specs[k].unit) for k in steps if k in specs}
    loop_params = set()
    for k, row in raw["sensitivity"].items():
        for part, s in row["by_part"].items():
            if abs(s) < SENS_ZERO:
                flat.append({"param": k, "part": part})
                continue
            loop_params.add(k)
            u = unit_of.get(k, "mm")
            tol = tolerance_of(k, part, float(values[k]), u, specs.get(k), ctx)
            sp = specs.get(k)
            contributors.append({"id": f"{part}:{k}", "label": f"{sp.label if sp else k} ({part})", "kind": "dimension",
                                 "part": part, "param": k, "nominal": float(values[k]), "unit": u,
                                 "sensitivity": float(s), "fd": row["how"], **tol})
    for it in raw["interfaces"]:
        if it["kind"] != "fit":
            continue
        decl = it["mate"].get("clearance")
        fl = abs(float(decl)) if isinstance(decl, (int, float)) else float(it["float"])
        contributors.append({"id": f"float:{it['from']}/{it['to']}", "label": f"Float of the fit {it['from']}/{it['to']}",
                             "kind": "float", "part": it["to"], "param": None, "nominal": 0.0, "unit": "mm",
                             "sensitivity": 1.0, "lower": -fl, "upper": fl, "dist": (dist or {}).get(f"float:{it['from']}/{it['to']}", "uniform"),
                             "evidence": "specified" if isinstance(decl, (int, float)) else "computed",
                             "source": "the Mate's declared clearance" if isinstance(decl, (int, float)) else "radii measured on the model",
                             "rule": "the part can sit anywhere in the radial clearance, square to the gap: ± the clearance "
                                     "per side, uniform (where it sits is not known); the radii's own tolerances are not added"})
    gdt_rows = _gdt(ctx["drawing"], raw, loop_params)
    contributors += [g for g in gdt_rows if g.get("sensitivity")]
    # the stack --------------------------------------------------------------------------------------------------
    lsl, usl, spec_ev = _spec(spec, nominal)
    wc = AN.worst_case(nominal, contributors)
    rs = AN.rss(nominal, contributors)
    mc = AN.monte_carlo(nominal, contributors, samples=samples, seed=seed, lsl=lsl, usl=usl)
    cap = AN.capability(rs["mean"], rs["sigma"], lsl, usl)
    cap_mc = AN.capability(mc["mean"], mc["sigma"], lsl, usl)
    shares = AN.contributions(contributors)
    out = {"version": VERSION, "name": name, "project": p["id"], "rev": n, "evidence": EVIDENCE,
           "gap": {"nominal": nominal, "direction": raw["n"], "direction_from": raw["direction_from"],
                   "closure": raw["closure"], "a": raw["a"], "b": raw["b"]},
           "loop": {"chain": raw["chain"], "links": raw["links"], "interfaces": raw["interfaces"], "mates": raw["mates"],
                    "parts": raw["parts"]},
           "contributors": contributors, "not_moving": sorted({f["param"] for f in flat} - loop_params),
           "skipped": raw["skipped"],
           "gdt": [g for g in gdt_rows if not g.get("sensitivity")],
           "spec": {"lsl": lsl, "usl": usl, "evidence": spec_ev},
           "worst_case": wc, "rss": rs, "monte_carlo": mc,
           "capability": {"rss": cap, "monte_carlo": {k: v for k, v in cap_mc.items() if k != "assumes"}},
           "contributions": shares, "chart": [{"id": x["id"], "label": x["label"], "percent": round(100 * x["variance_share"], 2)}
                                               for x in shares],
           "t_fd_s": raw.get("t_fd"), "t_s": round(time.perf_counter() - t0, 3)}
    out["thermal"] = _thermal(p, raw, nominal, wc, rs, _num(t_min, "t_min"), _num(t_max, "t_max"), alpha or {})
    out["suggestions"] = _suggest(nominal, contributors, shares, rs, wc, lsl, usl, ctx, raw)
    out["draw"] = _draw(raw, meshes)
    out["headline"] = headline(out)
    out["caveats"] = _caveats(out, ctx)
    return out


def _spec(spec, nominal):
    if spec is None:
        if nominal >= 0:
            return 0.0, None, "assumed (a gap must not close; give spec=[LSL, USL])"
        return None, None, "none (the gap is an interference by design; give spec=[LSL, USL])"
    if not isinstance(spec, (list, tuple)) or len(spec) != 2:
        raise StackError("spec is [LSL, USL]; either may be null.")
    lsl, usl = _num(spec[0], "LSL"), _num(spec[1], "USL")
    if lsl is not None and usl is not None and lsl > usl:
        raise StackError("LSL is above USL.")
    return lsl, usl, "specified (given in the request)"


def _gdt(drawing: dict, raw: dict, loop_params: set) -> list:
    """Declared GD&T on a face of the loop, converted: a zone of width t (position Ø t, profile t) lets the face sit
    ±t/2 along its own normal (planes) or square to its axis (cylinders); its effect on the gap is that times how much
    of the gap's direction is along it. Datum shifts and the bonus tolerance of a material condition are not credited."""
    import numpy as np
    n = np.array(raw["n"])
    faces = [raw["a"], raw["b"]] + [f for L in raw["links"] for f in (L["entry"], L["exit"])]
    out = []
    for i, g in enumerate(drawing.get("gdt") or []):
        at = g.get("at") or {}
        t = g.get("type")
        row = {"id": f"gdt:{g.get('id') or i + 1}", "type": t, "value": g.get("value"), "at": at}
        hit = None
        if at.get("feature"):
            for f in faces:
                if f["feature"] != at["feature"]:
                    continue
                if at.get("normal") is not None and ("normal" not in f or float(np.dot(f["normal"], at["normal"])) < 0.999):
                    continue
                if at.get("cylinder") and f["geom"] != "CYLINDER":
                    continue
                hit = f
                break
        if hit is None:
            row["why"] = "not on a face of this loop"
            out.append(row)
            continue
        if t not in CONVERTED_GDT:
            row["why"] = f"{t} is not converted into a stack (only position and profile are; it bounds form or " \
                         "orientation, not where the face is)"
            out.append(row)
            continue
        if "axis" in hit:
            u = np.array(hit["axis"])
            factor = math.sqrt(max(0.0, 1 - float(np.dot(u, n)) ** 2))
        else:
            factor = abs(float(np.dot(hit.get("normal", n), n)))
        half = float(g["value"]) / 2
        out.append({**row, "label": f"{t} {g['value']} on {hit['feature']} ({hit['part']})", "kind": "gdt",
                    "part": hit["part"], "param": None, "nominal": 0.0, "unit": "mm", "sensitivity": factor,
                    "lower": -half, "upper": half, "dist": "normal", "evidence": "specified",
                    "source": "the drawing's GD&T (ISO 1101)",
                    "rule": f"zone {g['value']} → ±{half:g} along the face, × {factor:.3f} for the gap's direction; "
                            "datum shift and bonus tolerance not credited"})
    return out


def _thermal(p, raw, nominal, wc, rs, t_min, t_max, alpha) -> dict | None:
    if t_min is None and t_max is None:
        return None
    t_min = T_REF if t_min is None else t_min
    t_max = T_REF if t_max is None else t_max
    if t_min > t_max:
        raise StackError("t_min is above t_max.")
    parts = {x["id"]: x for x in raw["parts"]}
    links, alphas = [], {}
    for L in raw["links"]:
        a = _alpha(p, parts[L["part"]], alpha)
        alphas[L["part"]] = a
        links.append({"part": L["part"], "length": L["length"], "alpha": a["value"]})
    rows = [AN.thermal_shift(links, t, T_REF) for t in (t_min, t_max)]
    out = {"t_ref": T_REF, "t_min": t_min, "t_max": t_max, "alpha": alphas,
           "equation": "gap(T) = gap(20 °C) + (T − 20) · Σ αᵢ dᵢ  (dᵢ: each part's signed link along the gap)",
           "assumes": "each part at one uniform temperature, free to grow, linear expansion with a constant α; the "
                      "tolerance zones' own growth (α · t · ΔT) is left out"}
    if any(r["shift"] is None for r in rows):
        out["not_computed"] = [a["why"] for a in alphas.values() if a.get("value") is None]
        return out
    out["at"] = []
    for r in rows:
        out["at"].append({"t": r["t"], "shift": r["shift"], "nominal": nominal + r["shift"], "terms": r["terms"],
                          "worst_case": [wc["min"] + r["shift"], wc["max"] + r["shift"]],
                          "rss": [rs["min"] + r["shift"], rs["max"] + r["shift"]]})
    sh = [0.0] + [r["shift"] for r in rows]
    out["worst_case_span"] = [wc["min"] + min(sh), wc["max"] + max(sh)]
    out["per_kelvin"] = sum(x["alpha"] * x["length"] for x in links)
    return out


_COST = {
    "ISO 286": "one IT grade finer usually means a finer process (reaming, fine boring or grinding)",
    "ISO 2768": "a finer general class (m to f) is the same process with more care, or this size toleranced on its own",
    "FDM": "calibrate the printer (print and measure the fit coupon) before buying precision: no machining",
    "calibration": "a better printer or slower, finer printing; or ream or machine this size after printing",
    "provenance": "measure the bought part with a better instrument, or buy a tighter grade",
    "request": "a tighter tolerance on this size, by the process that makes it",
    "float": "a tighter fit class, or a locating feature (a dowel, a shoulder) that removes the float",
    "gdt": "a smaller position or profile zone, which costs inspection as well as making",
}


def _cost_hint(c: dict) -> str:
    src = c.get("source", "") + " " + c.get("rule", "")
    for k in ("ISO 286", "ISO 2768", "FDM"):
        if k in src:
            return _COST[k]
    if c.get("kind") in ("float", "gdt"):
        return _COST[c["kind"]]
    if c.get("evidence") == "calibrated":
        return _COST["calibration"]
    if "provenance" in src:
        return _COST["provenance"]
    return _COST["request"]


def _suggest(nominal, cs, shares, rs, wc, lsl, usl, ctx, raw) -> list:
    out = []
    by = {c["id"]: c for c in cs}
    for sh in shares:
        if sh["variance_share"] < 0.01 and sh["worst_case_share"] < 0.05:
            continue
        w = AN.what_if(nominal, cs, sh["id"], 0.5)
        cap = AN.capability(w["rss"]["mean"], w["rss"]["sigma"], lsl, usl)
        c = by[sh["id"]]
        out.append({"id": sh["id"], "label": sh["label"], "action": "halve its tolerance",
                    "sigma_after": w["rss"]["sigma"], "sigma_cut": rs["sigma"] - w["rss"]["sigma"],
                    "worst_case_after": [w["worst_case"]["min"], w["worst_case"]["max"]],
                    "cpk_after": cap.get("cpk"), "evidence": "computed",
                    "cost": _cost_hint(c), "cost_evidence": "assumed (a rule of thumb, not a quote)"})
    out.sort(key=lambda x: -x["sigma_cut"])
    # centring: the parameter that moves the gap most, changed in the design (all parts it sizes move together)
    tot = {}
    for k, row in raw["sensitivity"].items():
        s = sum(row["by_part"].values())
        if abs(s) > SENS_ZERO:
            tot[k] = s
    if tot and (lsl is not None or usl is not None):
        if lsl is not None and usl is not None:
            need = (lsl + usl) / 2 - rs["mean"]
            why = "centres the mean in the specification"
        elif lsl is not None and wc["min"] < lsl:
            need, why = lsl - wc["min"], "lifts the worst case to the lower limit"
        elif usl is not None and wc["max"] > usl:
            need, why = usl - wc["max"], "brings the worst case down to the upper limit"
        else:
            need = 0.0
        if abs(need) > 1e-6:
            k = max(tot, key=lambda q: abs(tot[q]))
            out.append({"id": f"nominal:{k}", "label": f"Change {k}", "action": f"change {k} by {need / tot[k]:+.4g}",
                        "param": k, "delta": need / tot[k], "why": why + f" (d gap / d {k} = {tot[k]:+.4g}, summed "
                        "over the parts it sizes)", "evidence": "computed", "cost": "no cost to make: a design change",
                        "cost_evidence": "assumed"})
    return out


def _draw(raw: dict, meshes: dict | None = None) -> dict:
    """The loop for the viewport: faces to light (model face index, part, role) and the chain as segments along the
    direction. Points are in the assembled frame, at rest; each face also has its centre as built."""
    import numpy as np
    n = np.array(raw["n"])
    base = np.array(raw["a"]["center"])
    faces, segs = [], []

    def at(level):
        return [round(float(x), 6) for x in base + (level - float(base @ n)) * n]

    faces.append({**raw["a"], "role": "gap_a"})
    faces.append({**raw["b"], "role": "gap_b"})
    for L in raw["links"]:
        for end in ("entry", "exit"):
            f = L[end]
            if f["model_face"] not in (raw["a"]["model_face"], raw["b"]["model_face"]):
                faces.append({**f, "role": "interface"})
        segs.append({"kind": "link", "part": L["part"], "from": at(L["entry"]["level"]), "to": at(L["exit"]["level"]),
                     "length": L["length"]})
    for it in raw["interfaces"]:
        segs.append({"kind": it["kind"], "parts": [it["from"], it["to"]], "from": at(it["x"]["level"]),
                     "to": at(it["e"]["level"]), "length": it["offset"]})
    segs.append({"kind": "gap", "from": at(raw["a"]["level"]), "to": at(raw["b"]["level"]), "length": raw["gap"]})
    # the face itself, as triangles in the assembled frame (the kernel's tessellation), for the viewport to tint
    for f in faces:
        m = (meshes or {}).get((f["part"], f["model_face"]))
        if m:
            f["mesh"] = m
    return {"frame": "assembled, at rest", "direction": raw["n"], "faces": faces, "segments": segs,
            "parts": raw["chain"]}


def headline(r: dict) -> str:
    g, wc, rs = r["gap"]["nominal"], r["worst_case"], r["rss"]
    s = f"gap {g:.3f} mm; worst case {wc['min']:.3f} to {wc['max']:.3f}, RSS {rs['min']:.3f} to {rs['max']:.3f}"
    c = r["capability"]["rss"].get("cpk")
    if c is not None and math.isfinite(c):
        s += f"; Cpk {c:.2f}"
    return s


def _caveats(r: dict, ctx: dict) -> list:
    out = ["Linear: the gap is the nominal plus each contributor times its sensitivity, taken by finite differences "
           "on the rebuilt CAD at the nominal design. Large tolerances on angles bend the line."]
    ass = [c["id"] for c in r["contributors"] if c["evidence"] == "assumed"]
    if ass:
        out.append(f"{len(ass)} of {len(r['contributors'])} tolerances are assumed (uniform over the assumed range): "
                   + ", ".join(ass[:6]) + (" …" if len(ass) > 6 else "") + ". State them (tolerances=, or the drawing's "
                   "fits and general class) to replace them.")
    if r["skipped"]:
        out.append("Not differentiated: " + "; ".join(f"{k} ({v})" for k, v in list(r["skipped"].items())[:6]))
    if abs(r["gap"]["closure"]) > 1e-6:
        out.append(f"The loop closes to {r['gap']['closure']:.2e} mm, not zero: check the picked faces.")
    return out


def text(r: dict) -> str:
    lines = [r["headline"] + ".", "Loop: " + " → ".join(r["loop"]["chain"]) + "."]
    for x in r["chart"][:5]:
        lines.append(f"  {x['percent']:5.1f} %  {x['label']}")
    if r["suggestions"]:
        s = r["suggestions"][0]
        lines.append(f"Tighten first: {s['label']} ({s['action']}).")
    return "\n".join(lines)


# ---- stored stacks: definitions and results --------------------------------------------------------------------
FIELDS = ("name", "a", "b", "direction", "tolerances", "dist", "spec", "t_min", "t_max", "alpha", "samples", "seed",
          "params", "exclude")


def _file(st, pid):
    return st.dir(pid) / STACKS_FILE


def definitions(st, pid: str) -> list:
    f = _file(st, pid)
    if not f.is_file():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")).get("stacks") or [])
    except (OSError, ValueError):
        return []


def _clean_def(d: dict) -> dict:
    unknown = sorted(k for k in d if k not in FIELDS and k != "id")
    if unknown:
        raise StackError(f"Unknown stack field(s): {', '.join(unknown)}.", "Fields: " + ", ".join(FIELDS) + ".")
    if not d.get("a") or not d.get("b"):
        raise StackError("A stack needs the two faces of its gap: a and b.", '{"at": [x, y, z]} or {"face": i}.')
    return {k: d[k] for k in FIELDS if d.get(k) is not None}


def define(st, pid: str, d: dict, sid: str = "") -> dict:
    """Add (or, with sid, replace) a stack of the design. Returns it with its id."""
    from .. import fsutil
    row = _clean_def(d)
    with st.lock(pid):
        rows = definitions(st, pid)
        if sid:
            if not any(x["id"] == sid for x in rows):
                raise StackError(f"No stack {sid}.", "get_tolerance_stack(project) lists them.", status=404)
            rows = [{**row, "id": sid} if x["id"] == sid else x for x in rows]
        else:
            sid = "s" + uuid.uuid4().hex[:6]
            rows.append({**row, "id": sid})
        f = _file(st, pid)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stacks": rows}, indent=1), encoding="utf-8")
        fsutil.replace(tmp, f)
    return {**row, "id": sid}


def remove(st, pid: str, sid: str) -> None:
    from .. import fsutil
    with st.lock(pid):
        rows = [x for x in definitions(st, pid) if x["id"] != sid]
        f = _file(st, pid)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stacks": rows}, indent=1), encoding="utf-8")
        fsutil.replace(tmp, f)


def key(st, p: dict, d: dict, rev: int | None = None) -> str:
    """Everything a stack result depends on: geometry, the definition, the drawing spec, the materials, the
    parameters' provenance and the printer calibration. Change any and the result is stale."""
    from .. import drawing as D
    from ..studio import H
    r = st.rev(p, rev)
    try:
        dspec = D.merged_spec(st, p, r["n"])
    except Exception:                       # noqa: BLE001
        dspec = {}
    mats = [p.get("material"), sorted(((k, (v or {}).get("material")) for k, v in (p.get("parts") or {}).items()
                                       if isinstance(v, dict)), key=str)]
    cal = st.calibration.fingerprint(st.profile(p)) if (p.get("purpose") == "print") else ""
    return H("stack", VERSION, st.keys(p, r["n"])["geometry"], {k: v for k, v in d.items() if k not in ("id", "name")},
             dspec, mats, r.get("provenance") or {}, cal)


def _rdir(st, pid, sid):
    return st.dir(pid) / "artifacts" / "stack" / sid


def stored(st, p: dict, sid: str) -> tuple:
    """(result for the head's key or None, newest result of any key or None)."""
    d = next((x for x in definitions(st, p["id"]) if x["id"] == sid), None)
    if d is None:
        raise StackError(f"No stack {sid}.", "get_tolerance_stack(project) lists them.", status=404)
    k = key(st, p, d)
    f = _rdir(st, p["id"], sid) / f"{k}.json"
    cur = None
    if f.is_file():
        try:
            cur = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            cur = None
    newest = None
    rd = _rdir(st, p["id"], sid)
    if rd.is_dir():
        fs = sorted(rd.glob("*.json"), key=lambda x: x.stat().st_mtime)
        if fs:
            try:
                newest = json.loads(fs[-1].read_text(encoding="utf-8"))
            except ValueError:
                newest = None
    return cur, newest


def run(st, pid: str, sid: str) -> dict:
    """Compute a stored stack for the head revision and keep the result under its key."""
    from .. import fsutil
    p = st.load(pid)
    d = next((x for x in definitions(st, pid) if x["id"] == sid), None)
    if d is None:
        raise StackError(f"No stack {sid}.", "get_tolerance_stack(project) lists them.", status=404)
    k = key(st, p, d)
    res = compute(st, p, **{f: d[f] for f in FIELDS if f in d})
    res.update({"stack": sid, "key": k, "computed_at": time.time()})
    rd = _rdir(st, pid, sid)
    rd.mkdir(parents=True, exist_ok=True)
    tmp = rd / f"{k}.tmp"
    tmp.write_text(json.dumps(res, default=_json), encoding="utf-8")
    fsutil.replace(tmp, rd / f"{k}.json")
    return res


def _json(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return str(x)


def listing(st, p: dict) -> list:
    rows = []
    for d in definitions(st, p["id"]):
        cur, newest = stored(st, p, d["id"])
        if cur is not None:
            rows.append({"id": d["id"], "name": d.get("name", ""), "state": "current", "rev": cur.get("rev"),
                         "headline": cur.get("headline")})
        elif newest is not None:
            rows.append({"id": d["id"], "name": d.get("name", ""), "state": "stale", "last_rev": newest.get("rev"),
                         "headline": newest.get("headline"),
                         "why": f"computed for r{newest.get('rev')}; the geometry, a tolerance source or the definition changed since"})
        else:
            rows.append({"id": d["id"], "name": d.get("name", ""), "state": "never", "headline": ""})
    return rows
