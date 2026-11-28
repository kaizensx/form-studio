"""Inverse design: say what the part must do, and get the designs that do it, each one built and studied for real.

    job = start(st, pid, {"minimize": ["mass_g"], "require": ["fea.safety_factor >= 3"],
                          "vary": [{"key": "t", "min": 3, "max": 10}, {"key": "rib_h", "min": 0, "max": 20}]})
    r = get(st, p)                                    # the stored run: every point, the front, the chart, the budget

"Survive 250 N at this face with a safety factor of 3, as light as possible" is: a static strength study on the
design (the faces, the force, the material: strength_study), the requirement `fea.safety_factor >= 3` and the
objective `mass_g`. Two or three objectives give a Pareto front: the variants among which one can only gain on one
count by losing on another (lighter but less stiff, stiffer but heavier).

The search is over the design's own parameters (form/inverse/search.py: Gaussian-process surrogates, NSGA-II on
them, infill by predicted hypervolume improvement). What makes the result honest:

* **Every reported point is real.** Each candidate is built by the kernel and, when a strength metric is asked
  for, its strength study is solved (form/fea/constraint.py: the study's own settings, a time limit per solve).
  The surrogate only chooses what to evaluate next; no predicted number is ever reported.
* **The front is of verified points only.** A candidate whose build failed, whose study did not converge or that
  misses a requirement is kept in the record with the reason, and is not on the front. `fea.safety_factor` is the
  lower value (the stated discretisation error applied); a point whose central value passes while its lower value
  does not is marked "close", not passing.
* **The budget is stated.** Solves, builds and seconds used against their limits, why the search stopped, and that
  the front is approximate: a better design may exist between the evaluated points.

Metrics. From the kernel, per candidate: mass_g (volume x the density of the study's material, or of the design's;
labelled assumed at 1.24 g/cm3 when neither is known), volume_cm3, width, depth, height, overhang_mm2 and
contact_mm2 (the support the best orientation needs: a proxy for print support), min_wall_mm, derived.<key>,
statics.<key>. From the strength study: fea.safety_factor, fea.peak_von_mises_MPa, fea.max_displacement_mm. From a
modal study (modal_study=): modal.frequency_Hz, the first natural frequency. cost: mass x a price per kg, only when
a price is known (rates={"per_kg": x} with the search, labelled assumed; or the person's own price for the
material, labelled specified); no price is made up. Print time and sliced support come from a slice, which a
search does not run per candidate: slice the variant you keep.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path

VERSION = 1
SOLVES = 24                 # strength solves per search (each candidate: one static, one modal when asked)
SECONDS = 900.0             # wall time
SOLVES_MAX, SECONDS_MAX = 200, 7200.0
VARY_MAX = 6
KERNEL_ONLY_EVALS = 80      # without a strength metric a candidate costs a build, so more are afforded
DENSITY_ASSUMED = 1.24      # g/cm3, as form/optimize.py solid_mass_g
LABELS = {"mass_g": ("Mass", "g"), "volume_cm3": ("Volume", "cm³"), "solid_mass_g": ("Mass at 1.24 g/cm³", "g"),
          "fea.safety_factor": ("Safety factor (lower value)", ""), "fea.peak_von_mises_MPa": ("Peak von Mises stress", "MPa"),
          "fea.max_displacement_mm": ("Largest displacement", "mm"), "modal.frequency_Hz": ("First natural frequency", "Hz"),
          "cost": ("Material cost", ""), "overhang_mm2": ("Overhang needing support", "mm²"),
          "contact_mm2": ("Bed contact", "mm²"), "min_wall_mm": ("Thinnest wall", "mm"),
          "width": ("Width", "mm"), "depth": ("Depth", "mm"), "height": ("Height", "mm")}


def _err(msg: str, hint: str = "", status: int = 400, **kw):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status, **kw)


# ---- the request --------------------------------------------------------------------------------------------------------

def knobs(recipe, values: dict) -> list:
    """The parameters a search may vary when none are named: lengths that are not interfaces, with room to move."""
    out = []
    for sp in recipe.params:
        if sp.group in ("interface", "brief") or sp.unit not in ("mm", "") or sp.key not in values:
            continue
        if sp.max - sp.min <= max(sp.step or 0.0, 1e-9) or sp.key.startswith("_"):
            continue
        out.append({"key": sp.key, "min": sp.min, "max": sp.max})
    return out


def clean(st, p: dict, body: dict | None) -> dict:
    """The request, checked against the design: axes inside the parameters' ranges, metrics that exist, a study
    for every strength metric."""
    from .. import optimize as opt
    from ..fea import constraint as fea_con
    from ..fea import study as fea_study
    body = dict(body or {})
    known = ("vary", "minimize", "maximize", "require", "study", "modal_study", "budget", "rates", "seed", "batch")
    bad = [k for k in body if k not in known]
    if bad:
        raise _err(f"Unknown field {', '.join(sorted(bad))}.", "Fields: " + ", ".join(known) + ".")
    recipe = st.recipe(p)
    values = st.rev(p)["values"]

    def names(x):
        return [x] if isinstance(x, str) else [str(v) for v in (x or [])]
    objs = [(m, "minimize") for m in names(body.get("minimize"))] + [(m, "maximize") for m in names(body.get("maximize"))]
    if not 1 <= len(objs) <= 3:
        raise _err("Give one to three objectives.", 'For example minimize=["mass_g"], or minimize=["mass_g", '
                   '"fea.max_displacement_mm"] for a front of lighter against stiffer.')
    if len({m for m, _ in objs}) != len(objs):
        raise _err("An objective is named twice.")
    try:
        cons = opt.parse_constraints(body.get("require") or [])
    except opt.OptimizeError as e:
        raise _err(str(e)) from None
    used = [m for m, _ in objs] + [m for m, _, _ in cons]
    fea_used = [m for m in used if m.startswith("fea.")]
    out = {"objectives": [{"metric": m, "sense": s} for m, s in objs],
           "constraints": [{"metric": m, "op": op, "value": v} for m, op, v in cons]}
    if fea_used:
        fea_con.check_names([(m, None, None) for m in fea_used])
        out["study"] = fea_study.pick_static(p, body.get("study") or "")
        fea_study.materials_for(st, p, fea_study.get(p, out["study"]))
    elif body.get("study"):
        out["study"] = fea_study.pick_static(p, body["study"])
    if any(m.startswith("modal.") for m in used):
        if any(m != "modal.frequency_Hz" for m in used if m.startswith("modal.")):
            raise _err("The modal metric is modal.frequency_Hz (the first natural frequency).")
        sid = body.get("modal_study") or ""
        modal = [d for d in fea_study.definitions(p) if d["kind"] == "modal"]
        if sid:
            if fea_study.get(p, sid)["kind"] != "modal":
                raise _err(f"Study “{sid}” is not a modal study.")
        elif len(modal) == 1:
            sid = modal[0]["id"]
        else:
            raise _err("modal.frequency_Hz needs the design's modal study.", "Define one with strength_study(kind=\"modal\") "
                       "and name it with modal_study when the design has several.")
        out["modal_study"] = sid
    if "cost" in used:
        out["rates"] = _rates(st, p, body.get("rates"), out.get("study"))
    vary = body.get("vary") or []
    auto = not vary
    if auto:
        vary = knobs(recipe, values)[:4]
        if not vary:
            raise _err("This design has no parameter a search can vary.", "Name them: vary=[{\"key\", \"min\", \"max\"}].")
    if not 1 <= len(vary) <= VARY_MAX:
        raise _err(f"Vary one to {VARY_MAX} parameters.")
    axes = []
    for ax in vary:
        if isinstance(ax, str):
            ax = {"key": ax}
        try:
            sp = recipe.spec(ax["key"])
        except Exception:                                # noqa: BLE001
            raise _err(f"Unknown parameter “{ax.get('key')}”.", "Parameters: " + ", ".join(q.key for q in recipe.params) + ".") from None
        lo, hi = max(sp.min, float(ax.get("min", sp.min))), min(sp.max, float(ax.get("max", sp.max)))
        if hi <= lo:
            raise _err(f"{sp.key}: the range is empty ({lo:g} to {hi:g}; the parameter allows {sp.min:g} to {sp.max:g}).")
        axes.append({"key": sp.key, "label": sp.label, "lo": lo, "hi": hi, "step": sp.step or 0.0, "unit": sp.unit,
                     "integer": bool(sp.step and sp.step >= 1 and sp.unit in ("", "u"))})
    out["vary"] = axes
    out["vary_chosen_by"] = "the search (lengths that are not interfaces)" if auto else "the request"
    b = dict(body.get("budget") or {})
    strength = bool(fea_used) or "modal_study" in out
    out["budget"] = {"solves": int(max(4, min(float(b.get("solves", SOLVES)), SOLVES_MAX))),
                     "seconds": float(max(30.0, min(float(b.get("seconds", SECONDS)), SECONDS_MAX))),
                     "evaluations": int(max(6, min(float(b.get("evaluations", SOLVES if strength else KERNEL_ONLY_EVALS)), 400)))}
    out["seed"] = int(body.get("seed", 7))
    out["batch"] = int(max(1, min(int(body.get("batch", 4)), 8)))
    return out


def _rates(st, p, rates, sid) -> dict:
    if rates and rates.get("per_kg") is not None:
        v = float(rates["per_kg"])
        if v < 0:
            raise _err("The price per kg cannot be negative.")
        return {"per_kg": v, "currency": str(rates.get("currency") or ""), "evidence": "assumed (given with this search)"}
    try:
        from .. import cost
        prefs = cost.load_prefs(st.cfg)
        mat = (((p.get("print") or {}).get("filament_type")) or "").upper()
        if mat and prefs["prices"].get(mat) is not None:
            return {"per_kg": float(prefs["prices"][mat]), "currency": prefs.get("currency") or "",
                    "evidence": f"specified (your price for {mat})"}
    except Exception:                                    # noqa: BLE001
        pass
    raise _err("No price per kg is known, so cost cannot be an objective. No rate is made up.",
               'Give rates={"per_kg": 25} with the search (it is then labelled assumed). With one material, cost '
               "orders the designs exactly as mass does.")


def _source_text(m: dict, fallback: str) -> str:
    s = (m.get("sources") or {}).get("density")
    if isinstance(s, dict):
        s = ", ".join(str(s[k]) for k in ("source", "evidence") if s.get(k))
    return f"{m.get('name')}: {s or fallback}"


def _density(st, p, sid) -> tuple:
    """(g/cm3, where it is from)."""
    from ..fea import study as fea_study
    try:
        if sid:
            m = next(iter(fea_study.materials_for(st, p, fea_study.get(p, sid)).values()))
            if m.get("density"):
                return m["density"] / 1000.0, _source_text(m, "the study's material")
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from .. import materials as app
        from ..fea import material as material_mod
        key = app.resolved(p, "").get("material")
        if key:
            m = material_mod.resolve(key, ())
            if m.get("density"):
                return m["density"] / 1000.0, _source_text(m, "the design's material")
    except Exception:                                    # noqa: BLE001
        pass
    return DENSITY_ASSUMED, "assumed (1.24 g/cm³: no material with a density is set)"


# ---- the store -----------------------------------------------------------------------------------------------------------

def _dir(st, p: dict) -> Path:
    return st.dir(p["id"]) / "artifacts" / "studies" / "inverse"


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, default=float), encoding="utf-8")
    tmp.replace(path)


def _stale(st, p, r) -> bool:
    try:
        return r.get("source") != st.rid(p)
    except Exception:                                    # noqa: BLE001
        return True


def runs(st, p: dict) -> list:
    out = []
    for f in sorted(_dir(st, p).glob("*/record.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        r = _read(f)
        if r:
            out.append({k: r.get(k) for k in ("id", "rev", "ts", "headline", "evidence", "wall_seconds")} | {"stale": _stale(st, p, r)})
    return out


def get(st, p: dict, run: str = "") -> dict | None:
    base = _dir(st, p)
    if run:
        r = _read(base / run / "record.json")
        if r is None:
            raise _err(f"No inverse design run “{run}”.", "get_inverse_design lists the runs.", status=404)
    else:
        fs = sorted(base.glob("*/record.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        r = _read(fs[0]) if fs else None
    if r is not None:
        r["stale"] = _stale(st, p, r)
        if r["stale"]:
            r["stale_why"] = ("The design's source changed since this search (features were added or edited), so "
                              "its points describe another design. Search again.")
    return r


def running_job(st, pid: str):
    for j in st.jobs.values():
        if j.get("kind") == "inverse" and j.get("project") == pid and j.get("state") == "running":
            return j
    return None


# ---- one search ------------------------------------------------------------------------------------------------------------

def run(st, pid: str, body: dict | None = None, on_progress=None, cancelled=None) -> dict:
    """Search now, in this thread, and store the record. Returns it."""
    import numpy as np

    from .. import optimize as opt
    from ..fea import constraint as fea_con
    from ..fea import study as fea_study
    from . import search
    on_progress = on_progress or (lambda ev: None)
    cancelled = cancelled or (lambda: False)
    p = st.load(pid)
    o = clean(st, p, body)
    rid, base = st.rid(p), st.rev(p)["values"]
    axes = o["vary"]
    objs, cons = o["objectives"], o["constraints"]
    sid, msid = o.get("study"), o.get("modal_study")
    used = [x["metric"] for x in objs] + [c["metric"] for c in cons]
    need_fea = any(m.startswith("fea.") for m in used)
    need_modal = bool(msid)
    need_wall = "min_wall_mm" in used
    dens, dens_src = _density(st, p, sid)
    if (need_fea or need_modal) and fea_study.python(st.cfg) is None:
        from ..fea import HOW_TO_GET
        raise _err("The strength solver is not installed, so no candidate can be studied. Nothing was made up.", HOW_TO_GET,
                   status=409, kind="unavailable")
    t0 = time.time()
    limit = o["budget"]
    used_b = {"solves": 0, "builds": 0, "failed_builds": 0}
    points: list = []
    stopped = [""]

    def snap(ax, u):
        x = ax["lo"] + float(min(1.0, max(0.0, u))) * (ax["hi"] - ax["lo"])
        if ax["step"]:
            x = ax["lo"] + round((x - ax["lo"]) / ax["step"]) * ax["step"]
        x = min(ax["hi"], max(ax["lo"], x))
        return float(round(x)) if ax["integer"] else round(x, 6)

    def unit(ax, x):
        return (x - ax["lo"]) / (ax["hi"] - ax["lo"])

    def out_of_budget() -> bool:
        if cancelled():
            stopped[0] = "cancelled"
        elif time.time() - t0 > limit["seconds"]:
            stopped[0] = f"the time limit of {limit['seconds']:.0f} s was reached"
        elif (need_fea or need_modal) and used_b["solves"] >= limit["solves"]:
            stopped[0] = f"the limit of {limit['solves']} strength solves was reached"
        return bool(stopped[0])

    def one(changes: dict, row: dict) -> dict:
        """A built candidate's metrics, violations and the vectors the search reads."""
        pt = {"values": changes, "ok": bool(row["ok"]), "metrics": {}, "violations": [], "close": []}
        if not row["ok"]:
            used_b["failed_builds"] += 1
            pt["violations"] = ["it does not build: " + row["error"]["message"]]
            return pt
        met = dict(row["metrics"])
        met["mass_g"] = met["volume_cm3"] * dens
        if o.get("rates"):
            met["cost"] = met["mass_g"] / 1000.0 * o["rates"]["per_kg"]
        if need_fea:
            fea_cons = [(c["metric"], c["op"], c["value"]) for c in cons if c["metric"].startswith("fea.")]
            used_b["solves"] += 1
            r = fea_con.solve(st, p, sid, {**base, **changes}, fea_cons, opt.OPS)
            met.update({k: v for k, v in (r.get("metrics") or {}).items()})
            pt["fea"] = {k: r.get(k) for k in ("evidence", "seconds", "converged", "safety_factor", "why") if r.get(k) is not None}
            if r.get("why"):                             # e.g. a picked point that is no longer on a face of this candidate
                pt["violations"].append(f"the strength study could not be solved on this candidate: {r['why']}")
            elif not r.get("converged"):
                pt["violations"].append("the strength study did not converge, so it gives no numbers to compare")
            sf = r.get("safety_factor")
            for m, op, v in fea_cons:
                if m == "fea.safety_factor" and sf and op in (">=", ">") and sf["low"] < v <= sf["value"]:
                    pt["close"].append(f"safety factor {sf['value']:.3g} passes {v:g} at its central value but its lower "
                                       f"value {sf['low']:.3g} (the stated error applied) does not")
        if need_modal:
            used_b["solves"] += 1
            try:
                mr = fea_study.evaluate(st, p, msid, changes, budget_s=fea_con.PER_SOLVE_S, cancelled=cancelled)
                fz = [f for f in (mr.get("frequencies_Hz") or []) if f and f > 1e-6]
                met["modal.frequency_Hz"] = fz[0] if (mr.get("converged") and fz) else None
                pt["modal"] = {"evidence": mr.get("evidence"), "converged": bool(mr.get("converged"))}
            except Exception as e:                       # noqa: BLE001
                if getattr(e, "extra", {}).get("kind") in ("cancelled", "unavailable"):
                    raise
                met["modal.frequency_Hz"] = None
                pt["modal"] = {"why": str(e)}
        missing = sorted({m for m in used if met.get(m) is None and not m.startswith(("fea.", "modal."))})
        if missing:
            raise _err(f"Unknown metric {', '.join(missing)}.", "Metrics: " + ", ".join(sorted(k for k in met if met[k] is not None))
                       + ", fea.safety_factor, fea.peak_von_mises_MPa, fea.max_displacement_mm, modal.frequency_Hz, cost.")
        for c in cons:
            x = met.get(c["metric"])
            if x is None:
                if not (c["metric"].startswith("fea.") and pt["violations"]):         # the reason is already there
                    pt["violations"].append(f"{c['metric']} is not available for this candidate")
            elif not opt.OPS[c["op"]](x, c["value"]):
                pt["violations"].append(f"{c['metric']} {c['op']} {c['value']:g} (is {x:.4g})")
        pt["metrics"] = {k: (round(float(v), 6) if isinstance(v, (int, float)) else v) for k, v in met.items()}
        return pt

    def evaluate(Z):
        cand, keys = [], []
        for z in np.atleast_2d(Z):
            ch = {ax["key"]: snap(ax, u) for ax, u in zip(axes, z)}
            k = tuple(ch.values())
            if k not in keys:
                keys.append(k)
                cand.append(ch)
        rows = []
        # the kernel builds the batch in one call; the studies then run one candidate at a time, inside the budget
        built = st._k("evaluate", timeout=max(240, 60 * len(cand)), recipe_id=rid, base=base, candidates=cand,
                      need_wall=need_wall, p=p)
        used_b["builds"] += len(built)
        for ch, row in zip(cand, built):
            if out_of_budget():
                break
            pt = one(ch, row)
            pt["index"] = len(points)
            points.append(pt)
            met = pt["metrics"]
            f = None
            if pt["ok"] and all(met.get(x["metric"]) is not None for x in objs):
                f = [(-1.0 if x["sense"] == "maximize" else 1.0) * float(met[x["metric"]]) for x in objs]
            g = []
            for c in cons:
                x = met.get(c["metric"])
                if x is None:
                    g.append(float("nan"))
                else:
                    d = (c["value"] - x) if c["op"] in (">=", ">") else (x - c["value"]) if c["op"] in ("<=", "<") else abs(x - c["value"])
                    g.append(d / max(abs(c["value"]), 1e-9))
            rows.append({"x": [unit(ax, ch[ax["key"]]) for ax in axes], "f": f, "g": g, "info": pt["index"]})
            on_progress({"progress": f"{len(points)} candidates evaluated" + (f", {used_b['solves']} strength solves" if need_fea or need_modal else ""),
                         "fraction": min(0.98, max(len(points) / limit["evaluations"], (time.time() - t0) / limit["seconds"],
                                                   used_b["solves"] / limit["solves"] if (need_fea or need_modal) else 0.0))})
        return rows
    start = [[unit(ax, snap(ax, unit(ax, float(base[ax["key"]])))) for ax in axes]]      # the design as it is, first
    res = search.run(evaluate, len(axes), len(objs), len(cons), evals=limit["evaluations"], batch=o["batch"], seed=o["seed"],
                     start=start, stop=out_of_budget)
    if stopped[0] == "cancelled":
        raise _err("Cancelled. No result was stored.", status=409, kind="cancelled")
    feas, front = res["feasible"], res["front"]
    by_info = {r["info"]: i for i, r in enumerate(res["rows"])}
    for pt in points:
        i = by_info.get(pt["index"])
        pt["feasible"] = bool(i is not None and feas[i]) and not pt["violations"]
        pt["on_front"] = bool(i is not None and front[i]) and pt["feasible"]
        pt["chosen_because"] = res["rows"][i].get("why") if i is not None else None
    head_key = tuple(snap(ax, unit(ax, float(base[ax["key"]]))) for ax in axes)
    current = next((pt for pt in points if tuple(pt["values"].values()) == head_key), None)
    fr = sorted((pt for pt in points if pt["on_front"]), key=lambda q: q["metrics"][objs[0]["metric"]])

    def label(m):
        return LABELS.get(m, (m, ""))
    ev_of = {m: ("simulated (FEA, each point's own study; evidence per point)" if m.startswith(("fea.", "modal."))
                 else f"computed (B-rep volume x density; density: {dens_src})" if m == "mass_g"
                 else o["rates"]["evidence"] + ", on computed mass" if m == "cost" else "computed (B-rep)")
             for m in used}
    axes_out = [{"metric": x["metric"], "sense": x["sense"], "label": label(x["metric"])[0], "unit": label(x["metric"])[1],
                 "evidence": ev_of[x["metric"]]} for x in objs]
    rec = {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4], "version": VERSION, "project": pid,
        "rev": st.rev(p)["n"], "source": rid, "ts": time.time(),
        "objectives": axes_out,
        "constraints": [{**c, "text": f"{c['metric']} {c['op']} {c['value']:g}", "evidence": ev_of[c["metric"]]} for c in cons],
        "vary": [{k: ax[k] for k in ("key", "label", "lo", "hi", "step", "unit")} for ax in axes],
        "vary_chosen_by": o["vary_chosen_by"], "study": sid, "modal_study": msid,
        "density": {"g_cm3": round(dens, 5), "source": dens_src}, "rates": o.get("rates"),
        "points": points, "front": [pt["index"] for pt in fr], "current": current["index"] if current else None,
        "history": res["history"],
        "budget": {"strength_solves": used_b["solves"], "strength_solves_limit": limit["solves"] if (need_fea or need_modal) else None,
                   "builds": used_b["builds"], "builds_failed": used_b["failed_builds"], "evaluations": len(points),
                   "evaluations_limit": limit["evaluations"], "wall_seconds": round(time.time() - t0, 1),
                   "seconds_limit": limit["seconds"], "stopped": stopped[0] or "the evaluations asked for were used"},
        "method": res["method"],
        "approximate": ("The front is approximate: it holds the best of the candidates that were evaluated, and a "
                        "better design may exist between them. Every point on it was built"
                        + (" and studied" if need_fea or need_modal else "") + " for real; nothing shown is a prediction."),
    }
    rec["wall_seconds"] = rec["budget"]["wall_seconds"]
    rec["chart"] = chart(rec)
    rec["evidence"] = "simulated (FEA) on every point" if (need_fea or need_modal) else "computed (B-rep) on every point"
    n_ok = sum(1 for pt in points if pt["feasible"])
    if fr:
        a = objs[0]
        best = fr[0] if a["sense"] == "minimize" else fr[-1]
        rec["headline"] = (f"{len(fr)} variant{'s' if len(fr) != 1 else ''} on the front of {n_ok} that meet the requirements "
                           f"({len(points)} evaluated); best {label(a['metric'])[0].lower()} "
                           f"{best['metrics'][a['metric']]:.4g} {label(a['metric'])[1]}".strip())
        for pt in fr:
            pt["keep"] = f"save_variant(project=\"{pid}\", name=..., values={json.dumps(pt['values'])})"
    else:
        why = sorted({v.split(" (is")[0] for pt in points for v in pt["violations"]})[:4]
        rec["headline"] = f"no candidate of {len(points)} met the requirements"
        rec["none_why"] = why
    base_dir = _dir(st, p) / rec["id"]
    _write(base_dir / "record.json", rec)
    for old in sorted(_dir(st, p).glob("*/record.json"), key=lambda x: x.stat().st_mtime, reverse=True)[6:]:
        shutil.rmtree(old.parent, ignore_errors=True)
    try:
        st.activity(pid, "search", f"Inverse design: {rec['headline']} [{rec['evidence']}]", by="engine")
    except Exception:                                    # noqa: BLE001
        pass
    return rec


def chart(rec: dict) -> dict:
    """What a Pareto chart draws: one entry per evaluated point with its place on each axis and its state."""
    objs = rec["objectives"]
    pts = []
    for pt in rec["points"]:
        m = pt.get("metrics") or {}
        pts.append({"index": pt["index"], "at": [m.get(x["metric"]) for x in objs], "values": pt["values"],
                    "state": "front" if pt.get("on_front") else "feasible" if pt.get("feasible") else
                             "failed" if not pt.get("ok") else "close" if pt.get("close") and len(pt["violations"]) <= len(pt["close"]) else "misses",
                    "why": (pt.get("violations") or [None])[0], "current": pt["index"] == rec.get("current")})
    return {"axes": [{"metric": x["metric"], "label": x["label"], "unit": x["unit"], "better": "lower" if x["sense"] == "minimize" else "higher"}
                     for x in objs],
            "points": pts, "front": rec["front"],
            "progress": [{"evaluations": h["evaluations"], "front": h["front"], "hypervolume": h["hypervolume"]} for h in rec["history"]],
            "note": "Points on the front are joined in the order of the first axis. Failed and missing points are shown, not dropped."}


def start(st, pid: str, body: dict | None = None) -> dict:
    """Search in the background. Returns the job (Studio.jobs: progress, cancel). One search per design at a time."""
    from .. import taskstore
    p = st.load(pid)
    busy = running_job(st, pid)
    if busy is not None:
        return busy
    clean(st, p, body)                                   # refuse now what cannot run
    step = {"node": "inverse", "label": "Inverse design", "state": "running", "progress": {"label": "Queued", "value": 0.0}}
    job = {"id": uuid.uuid4().hex[:10], "project": pid, "kind": "inverse", "state": "running", "started": time.time(),
           "steps": [step]}
    st.jobs[job["id"]] = job
    jid = job["id"]

    def on_progress(ev):
        step["progress"] = {"label": ev.get("progress"), "value": ev.get("fraction")}
        st.jobs.save(job)

    def work():
        try:
            r = run(st, pid, body, on_progress=on_progress, cancelled=lambda: st.jobs.cancel_requested(jid))
            step["state"] = job["state"] = "done"
            job["result"] = {"run": r["id"], "headline": r["headline"], "evidence": r["evidence"]}
        except Exception as e:                           # noqa: BLE001 - the job carries the failure
            was = getattr(e, "extra", {}).get("kind") == "cancelled"
            step["state"] = job["state"] = "cancelled" if was else "failed"
            job["error"] = e.public() if hasattr(e, "public") else {"message": f"{type(e).__name__}: {e}"}
        step.pop("progress", None)
        job["finished"] = time.time()
        st.jobs.save(job)
        st.jobs.clear_cancel(jid)
    taskstore.child("inverse", jid, pid, lambda: st.jobs.request_cancel(jid), lambda: job["state"] != "running",
                    lambda: (step.get("progress") or {}).get("label") or step["label"])
    threading.Thread(target=work, daemon=True, name=f"inverse-{jid}").start()
    return job


def save_point(st, pid: str, run: str, index: int, name: str = "", by: str = "agent") -> dict:
    """Keep one point of a search as a named variant of the design (form/variants.py)."""
    from .. import variants
    p = st.load(pid)
    rec = get(st, p, run)
    if rec is None:
        raise _err("This design has no inverse design run.", status=404)
    if rec.get("stale"):
        raise _err("The design's source changed since this search.", "Search again.", status=409)
    pt = next((q for q in rec["points"] if q["index"] == int(index)), None)
    if pt is None or not pt.get("ok"):
        raise _err(f"No built point {index} in this search.")
    m = pt["metrics"]
    bits = [f"{x['label']} {m.get(x['metric']):.4g} {x['unit']}".strip() for x in rec["objectives"] if m.get(x["metric"]) is not None]
    note = ("Inverse design " + rec["id"] + ": " + ", ".join(bits) + ("" if pt.get("feasible") else "; does not meet the requirements"))
    return variants.save(st, p, name or f"Front {index}", values=pt["values"], note=note, by=by, source="inverse design")
