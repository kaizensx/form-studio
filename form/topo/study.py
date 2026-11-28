"""Topology optimisation of a design, written back as features: define, run in the background, read, apply.

    job = start(st, pid, {"volfrac": 0.5})                 # a job in Studio.jobs: progress, cancel
    r = latest(st, p)                                      # the stored run with its state
    apply(st, pid, r["id"])                                # the pockets become features of the design: one revision

What a run does, and what each step is evidence of:

1. The loads, supports and material are the design's static strength study (form/fea/study.py): nothing is entered
   twice. The solid of the head revision goes to the FEA engine's Python (form/topo/run.py), which optimises the
   layout (SIMP, form/topo/simp.py) on the study's own kind of mesh and reads it (form/topo/recon.py).
2. **Reconstruction as features.** The pockets become edit ops (form/topo/emit.py) and the edited design is built
   by the kernel without being saved. The built solid's volume is computed (B-rep).
3. **Verification.** The strength study is solved on that built solid with the refining solver, the same as any
   strength study: safety factor with its stated error, displacement, strain energy. These are set beside the
   density result's own numbers and beside the part as it was. Evidence: simulated (FEA), on real CAD.
4. When the features cannot be written, built or studied (no pockets found, an OpenSCAD or built-in design, a build
   that fails, a study that does not converge), the run says why and offers the smoothed dense region as a mesh
   body, labelled as one. Nothing is presented as editable CAD that is not.

A target can be a volume fraction, a mass (grams, turned into a fraction of the solid's mass) or a safety factor:
with `safety_factor` the run is repeated at a higher fraction, up to `tries` times, until the rebuilt part's
studied safety factor (its lower value) meets it; every try is in the record.

Bounded: the mesh size, the iteration limit and the time limit are stated in the record, with the solves used.
The record is stored beside the revision (artifacts/studies/topology/<run>/) with the density field of every
iteration (frames.json) for the window to play.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from ..fea import HOW_TO_GET, python
from ..fea import study as fea_study

VERSION = 1
SETTINGS = {
    # key: (default, low, high, what it is)
    "volfrac": (0.5, 0.08, 0.95, "the fraction of the solid's volume that stays"),
    "h": (0.0, 0.0, 1e4, "element size in mm (0: the part's diagonal / 40)"),
    "rmin": (0.0, 0.0, 1e4, "the smallest member in mm (0: 2 elements)"),
    "penal": (3.0, 1.0, 6.0, "the SIMP penalty"),
    "max_iter": (80, 5, 400, "the iteration limit"),
    "budget_s": (240.0, 10.0, 3600.0, "the optimisation's time limit in seconds"),
    "elements_max": (60000, 1000, 400000, "the mesh is made coarser until it has at most this many elements"),
    "keep": (None, 0.0, 1e4, "millimetres kept solid around the faces that carry supports and loads (default: rmin)"),
    "rim": (None, 0.0, 1e4, "millimetres kept solid along the side walls (default: half of rmin, at least h; pockets only)"),
    "min_pocket": (0.0, 0.0, 1e4, "the smallest pocket in mm (0: 1.5 rmin)"),
    "tol": (0.02, 0.001, 0.2, "stop when no density changes by more than this"),
    "smooth": (8, 0, 40, "smoothing passes of the mesh body"),
}
MODES = ("pockets", "free")
VERIFY_S = 300.0             # the strength study of the rebuilt part: many small faces, so a larger mesh than usual
VERIFY_MESH = {"dof_max": 1_500_000, "budget_s": VERIFY_S}
TRIES = 3
TIMEOUT_S = 3900
SF_BAND = (0.5, 2.0)         # the rebuilt part's studied safety factor against the density result's: outside this
                             # band the two disagree and the record says so (docs/OPTIMISATION.md)


def _err(msg: str, hint: str = "", status: int = 400, **kw):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status, **kw)


def clean(body: dict | None) -> dict:
    """The settings of a run, checked: unknown keys and values outside their range are refused with the range."""
    body = dict(body or {})
    out = {}
    for k in ("study", "mode", "pull", "mass_g", "safety_factor", "tries", "filter"):
        if body.get(k) not in (None, ""):
            out[k] = body.pop(k)
        else:
            body.pop(k, None)
    bad = [k for k in body if k not in SETTINGS]
    if bad:
        raise _err(f"Unknown topology setting {', '.join(sorted(bad))}.",
                   "Settings: " + ", ".join(f"{k} ({v[3]})" for k, v in SETTINGS.items()) +
                   "; and study, mode, pull, mass_g, safety_factor, tries, filter.")
    for k, (dflt, lo, hi, what) in SETTINGS.items():
        v = body.get(k, dflt)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise _err(f"{k} must be a number ({what}).") from None
        if not lo <= v <= hi:
            raise _err(f"{k} = {v:g} is outside {lo:g} to {hi:g} ({what}).")
        out[k] = int(v) if isinstance(dflt, int) and not isinstance(dflt, bool) else v
    out["mode"] = str(out.get("mode") or "pockets")
    if out["mode"] not in MODES:
        raise _err(f"Unknown mode “{out['mode']}”.", "pockets: a 2.5D layout along a pull direction, written as "
                   "features. free: a 3D layout, offered as a mesh body.")
    if out.get("filter", "density") not in ("density", "sensitivity"):
        raise _err("filter is \"density\" or \"sensitivity\".")
    if out.get("pull") is not None:
        out["pull"] = _axis(out["pull"])
    for k in ("mass_g", "safety_factor"):
        if k in out:
            out[k] = float(out[k])
            if out[k] <= 0:
                raise _err(f"{k} must be above 0.")
    out["tries"] = int(max(1, min(int(out.get("tries", TRIES)), 5)))
    return out


def _axis(a) -> list:
    if isinstance(a, str) and a.lower().lstrip("-+") in ("x", "y", "z"):
        return [1.0 if a.lower().lstrip("-+") == k else 0.0 for k in "xyz"]
    try:
        v = [float(x) for x in a]
    except (TypeError, ValueError):
        raise _err("The pull direction is x, y, z or three numbers.") from None
    n = sum(x * x for x in v) ** 0.5
    if len(v) != 3 or n < 1e-9:
        raise _err("The pull direction is x, y, z or three numbers that are not all 0.")
    return [x / n for x in v]


# ---- the store ---------------------------------------------------------------------------------------------------------

def _dir(st, p: dict) -> Path:
    return st.dir(p["id"]) / "artifacts" / "studies" / "topology"


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


def runs(st, p: dict) -> list:
    """Stored runs, newest first: {"id", "rev", "ts", "stale", "headline", ...}."""
    out = []
    base = _dir(st, p)
    for f in sorted(base.glob("*/record.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        r = _read(f)
        if r:
            out.append({k: r.get(k) for k in ("id", "rev", "ts", "headline", "evidence", "outcome", "mode", "seconds")}
                       | {"stale": _stale(st, p, r)})
    return out


def _stale(st, p: dict, r: dict) -> bool:
    try:
        return r.get("geometry_key") != st.keys(p)["geometry"]
    except Exception:                                    # noqa: BLE001
        return True


def get(st, p: dict, run: str = "") -> dict | None:
    """One stored run (the newest when run is empty), with "stale" when the design moved on."""
    base = _dir(st, p)
    if run:
        r = _read(base / run / "record.json")
        if r is None:
            raise _err(f"No topology run “{run}”.", "get_topology lists the runs.", status=404)
    else:
        fs = sorted(base.glob("*/record.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        r = _read(fs[0]) if fs else None
    if r is not None:
        r["stale"] = _stale(st, p, r)
        if r["stale"]:
            r["stale_why"] = (f"This run describes revision {r.get('rev')}; the design changed since, so its pockets "
                              "were fitted to another solid. Run it again.")
    return r


def frames_path(st, p: dict, run: str) -> Path | None:
    f = _dir(st, p) / run / "frames.json"
    return f if f.is_file() else None


def running_job(st, pid: str):
    for j in st.jobs.values():
        if j.get("kind") == "topology" and j.get("project") == pid and j.get("state") == "running":
            return j
    return None


def live(st, p: dict, job: dict) -> dict | None:
    """The newest density picture of a running job."""
    w = job.get("work")
    return _read(Path(w) / "live.json") if w else None


# ---- one run -----------------------------------------------------------------------------------------------------------

def _auto_pull(bbox) -> list:
    size = [b - a for a, b in zip(bbox[0], bbox[1])]
    k = size.index(min(size))
    return [1.0 if i == k else 0.0 for i in range(3)]


def _fea_numbers(res: dict, volume_mm3: float | None, rho) -> dict:
    """What is compared of a strength study's result."""
    sf = res.get("safety_factor") if res.get("converged") else None
    lv = ((res.get("convergence") or {}).get("levels") or [{}])[-1]
    out = {"converged": bool(res.get("converged")), "evidence": res.get("evidence"),
           "safety_factor": round(sf["value"], 4) if sf else None, "safety_factor_low": round(sf["low"], 4) if sf else None,
           "peak_von_mises_MPa": res.get("peak_von_mises_MPa"), "max_displacement_mm": res.get("max_displacement_mm"),
           "compliance_N_mm": round(2 * lv["strain_energy_mJ"], 6) if lv.get("strain_energy_mJ") is not None else None,
           "discretisation_error": res.get("discretisation_error"), "volume_mm3": round(volume_mm3, 2) if volume_mm3 else None,
           "mesh": {k: (res.get("mesh") or {}).get(k) for k in ("tets", "unknowns", "h_mean_mm")},
           "refinements": len((res.get("convergence") or {}).get("levels") or []), "seconds": res.get("seconds")}
    if not res.get("converged"):
        out["not_converged_because"] = res.get("not_converged_because")
    if sf is None and res.get("safety_factor_withheld"):
        out["safety_factor_withheld"] = res["safety_factor_withheld"]
    if volume_mm3 and rho:
        out["mass_g"] = round(volume_mm3 * rho * 1e-6, 4)
    return out


def _reconstruct(st, p: dict, sid: str, res: dict, cancelled) -> dict:
    """Layout -> ops -> a built solid -> a strength study of it. Returns the "reconstruction" block."""
    from .. import edits, modelling
    from . import emit
    layout = res.get("layout")
    out = {"status": "failed"}
    if res.get("mode") != "pockets":
        out["why"] = ("A free 3D layout has no single pull direction, so it is not written as pockets. It is offered as "
                      "a mesh body.")
        return out
    if not layout or not layout.get("pockets"):
        out["why"] = ("No pocket was found: at this volume fraction and member size the material that can go is "
                      "thinner than the smallest pocket, or all of it lies in the regions that must stay.")
        out["hint"] = "Lower volfrac, lower rmin or keep, or use a finer h."
        return out
    c = edits.canonical(st, p)
    if c["mode"] == "none":
        out["why"] = f"The design's source cannot take feature edits ({c.get('why') or 'it has no feature form'})."
        out["hint"] = "Write the design as code with features (design_as_recipe turns a building block into one)."
        return out
    if emit.already(c["source"]):
        out["why"] = "The design already has lightening pockets from an earlier topology optimisation."
        out["hint"] = ("Change them with their parameters (topo_inset, topo_fillet, topo_web), or go back to the "
                       "revision before they were added and optimise that.")
        return out
    s = res["settings"]
    # a generous corner radius: a sharp or tight pocket corner raises the stress there and takes the strength study
    # many refinements (measured: at a fifth of this radius it did not converge inside its limits)
    fillet = round(max(0.5, min(0.4 * s["rmin_mm"], 4.0)), 2)
    ops, summary = emit.ops_for(layout, layout["grid"], fillet, s["rmin_mm"])
    out.update({"ops": ops, "summary": summary, "features": [o["feature"] for o in ops if "feature" in o],
                "parameters": {o["param"]["key"]: o["param"]["default"] for o in ops if "param" in o},
                "canonical": c["mode"]})
    try:
        pv = modelling.preview(st, p, ops)
    except Exception as e:                               # noqa: BLE001 - a fit that does not build is a failed fit
        out["why"] = f"The pockets could not be built: {e}"
        return out
    if not pv.get("ok"):
        out["why"] = f"The pockets could not be built: {pv.get('refused')}"
        out["build_log"] = pv.get("build_log")
        return out
    vol0, vol1 = pv["volume_mm3"]["before"], pv["volume_mm3"]["after"]
    out["built"] = {"volume_mm3": vol1, "volume_fraction": round(vol1 / vol0, 4), "volume_before_mm3": vol0,
                    "faces": pv.get("faces"), "evidence": "computed (B-rep)"}
    cut = [e for e in pv.get("build_log") or [] if str(e.get("feature", "")).startswith(emit.PREFIX)]
    idle = [e["feature"] for e in cut if abs(e.get("dvol") or 0) < 1e-6]
    if idle:
        out["built"]["pockets_that_cut_nothing"] = idle
    if vol1 >= vol0 * 0.999:
        out["why"] = "The pockets cut nothing from the solid."
        return out
    rid = pv["rid"]
    rec = st.recipes[rid]
    head = st.rev(p)["values"]
    vals = st._validate(rid, {**rec.defaults(), **{k: v for k, v in head.items() if k in {q.key for q in rec.params}}})
    # the study starts from a mesh of the part's diagonal / 12; between pockets that can be too coarse for the mesher,
    # so a start that fails to mesh is tried again at the member size and at half of it (said in the record)
    fr, starts = None, []
    for h0 in (None, s["rmin_mm"], 0.5 * s["rmin_mm"]):
        try:
            fr = fea_study.evaluate(st, p, sid, vals, budget_s=VERIFY_S, rid=rid, cancelled=cancelled,
                                    mesh={**VERIFY_MESH, **({"h0": round(h0, 4)} if h0 else {})})
            starts.append({"h0_mm": h0, "ok": True})
            break
        except Exception as e:                           # noqa: BLE001
            kind = getattr(e, "extra", {}).get("kind")
            if kind in ("cancelled", "unavailable"):
                raise
            starts.append({"h0_mm": h0, "ok": False, "why": str(e)})
            if kind != "mesh":
                break
    if len(starts) > 1:
        out["mesh_starts"] = starts
    if fr is None:
        out["why"] = f"The rebuilt part could not be studied: {starts[-1]['why']}"
        out["status"] = "built, not verified"
        return out
    rho = res.get("density_kg_m3")
    out["verified"] = _fea_numbers(fr, vol1, rho)
    out["status"] = "verified" if fr.get("converged") else "built, study not converged"
    if not fr.get("converged"):
        out["why"] = ("The strength study of the rebuilt part did not converge, so it gives no safety factor: "
                      + str(fr.get("not_converged_because") or ""))
    return out


def _compare(res: dict, recon: dict, before: dict | None) -> dict:
    """The rebuilt part beside the density result and beside the part as it was."""
    raw, ver = res.get("density_result") or {}, recon.get("verified") or {}
    out = {"density_result": {k: raw.get(k) for k in ("volume_fraction", "mass_g", "compliance_N_mm", "max_displacement_mm",
                                                       "peak_von_mises_MPa", "safety_factor", "how") if k in raw},
           "rebuilt_cad": ver or None, "solid_part": before}

    def ratio(a, b):
        return round(a / b, 4) if a and b else None
    if ver:
        out["rebuilt_over_density"] = {
            "safety_factor": ratio(ver.get("safety_factor"), raw.get("safety_factor")),
            "compliance": ratio(ver.get("compliance_N_mm"), raw.get("compliance_N_mm")),
            "max_displacement": ratio(ver.get("max_displacement_mm"), raw.get("max_displacement_mm")),
            "mass": ratio(ver.get("mass_g"), raw.get("mass_g")) or ratio((recon.get("built") or {}).get("volume_fraction"),
                                                                         raw.get("volume_fraction"))}
        r = out["rebuilt_over_density"]["safety_factor"]
        if r is not None:
            out["safety_factor_band"] = {"band": list(SF_BAND), "inside": SF_BAND[0] <= r <= SF_BAND[1],
                                         "meaning": "the rebuilt part's studied safety factor over the density result's. "
                                                    "The density result is one coarse mesh with a jagged boundary; the "
                                                    "study of the rebuilt part is the one to rely on."}
    if ver and before:
        out["rebuilt_over_solid_part"] = {"mass": ratio(ver.get("mass_g"), before.get("mass_g")) or
                                          ratio(ver.get("volume_mm3"), before.get("volume_mm3")),
                                          "safety_factor": ratio(ver.get("safety_factor"), before.get("safety_factor")),
                                          "max_displacement": ratio(ver.get("max_displacement_mm"), before.get("max_displacement_mm"))}
    return out


def _headline(rec: dict) -> str:
    rc = rec.get("reconstruction") or {}
    ver, built = rc.get("verified") or {}, rc.get("built") or {}
    if rc.get("status") == "verified":
        bits = [f"{len(rc.get('features') or [])} pockets, {100 * (1 - built.get('volume_fraction', 1)):.0f} % lighter"]
        if ver.get("mass_g"):
            bits.append(f"{ver['mass_g']:g} g")
        if ver.get("safety_factor") is not None:
            bits.append(f"safety factor {ver['safety_factor']:.2f} (at least {ver['safety_factor_low']:.2f})")
        return ", ".join(bits)
    if rc.get("features") and built:
        return f"{len(rc['features'])} pockets built, not verified: {rc.get('why', '')}"[:200]
    body = rec.get("body") or {}
    if body:
        return f"no editable features ({(rc.get('why') or '')[:90]}); mesh body offered at {100 * body.get('volume_fraction', 0):.0f} % of the volume"
    return f"no result: {rc.get('why', '')}"[:200]


def run(st, pid: str, opts: dict | None = None, on_progress=None, cancelled=None, job: dict | None = None) -> dict:
    """Run now, in this thread, and store the record. Returns it."""
    o = clean(opts)
    on_progress = on_progress or (lambda ev: None)
    cancelled = cancelled or (lambda: False)
    p = st.load(pid)
    sid = fea_study.pick_static(p, o.get("study", ""))
    d = fea_study.get(p, sid)
    mats = fea_study.materials_for(st, p, d)
    if len(mats) != 1:
        raise _err("Topology optimisation works on a design of one solid; this one has several parts.",
                   "Optimise each part as its own design.")
    py = python(st.cfg)
    if py is None:
        raise _err("The strength solver is not installed, so nothing was optimised. No result was made up.", HOW_TO_GET,
                   status=409, kind="unavailable")
    rev = st.rev(p)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    base = _dir(st, p) / run_id
    t0 = time.time()
    tries, rec = [], None
    volfrac = o["volfrac"]
    before = None
    try:
        for attempt in range(o["tries"] if o.get("safety_factor") else 1):
            work = base / f"try{attempt + 1}.work"
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True, exist_ok=True)
            if job is not None:
                job["work"] = str(work)
            on_progress({"progress": "Preparing the solid", "fraction": 0.0})
            prep = st._k("fea_prepare", timeout=300, key=st.keys(p)["geometry"], recipe_id=st.rid(p), values=rev["values"],
                         out_step=str(work / "solid.step"), picks=fea_study._picks(d), p=p)
            if prep.get("error"):
                raise _err(prep["error"])
            spec = fea_study._engine_spec(d, prep, mats)
            m = next(iter(mats.values()))
            rho = m.get("density")
            if o.get("mass_g") and attempt == 0:
                if not rho:
                    raise _err("A mass target needs the material's density.", "Give the study a material with a density.")
                mass0 = prep["volume_mm3"] * rho * 1e-6
                volfrac = o["mass_g"] / mass0
                if not SETTINGS["volfrac"][1] <= volfrac <= SETTINGS["volfrac"][2]:
                    raise _err(f"{o['mass_g']:g} g is {volfrac * 100:.0f} % of the solid's {mass0:.4g} g, outside what "
                               "can be optimised (8 % to 95 %).")
            topo = {k: o[k] for k in SETTINGS if k in o and k != "volfrac"}
            topo.update({"volfrac": volfrac, "mode": o["mode"], "filter": o.get("filter", "density"),
                         "pull": (o.get("pull") or _auto_pull(prep["bbox"])) if o["mode"] == "pockets" else None})
            _write(work / "job.json", {"step": prep["step"], "spec": spec, "topology": topo})
            code = fea_study._spawn(py, work, on_progress, cancelled, module="form.topo.run", timeout_s=TIMEOUT_S)
            if code == -1:
                raise _err("Cancelled. No result was stored.", status=409, kind="cancelled")
            if code == -2:
                raise _err(f"The optimisation did not finish in {TIMEOUT_S} s and was stopped.", "Use a larger h.")
            res = _read(work / "result.json")
            if res is None:
                tail = (fea_study._read_text(work / "stderr.txt") or "")[-800:]
                raise _err("The engine stopped without a result." + (f" Its last words: {tail}" if tail else ""),
                           status=500, kind="engine")
            if res.get("error"):
                e = res["error"]
                if e.get("kind") == "cancelled":
                    raise _err("Cancelled. No result was stored.", status=409, kind="cancelled")
                raise _err(e.get("message", "The optimisation failed."), e.get("hint", ""), status=422, kind=e.get("kind"))
            on_progress({"progress": "Rebuilding as features and studying the result", "fraction": 0.93})
            recon = _reconstruct(st, st.load(pid), sid, res, cancelled)
            if before is None:
                try:                                     # the part as it was, by the same study
                    cur = fea_study.result(st, p, sid, stale_ok=False).get("result")
                    if cur is None:
                        cur = fea_study.evaluate(st, p, sid, {}, budget_s=VERIFY_S, cancelled=cancelled)
                    before = _fea_numbers(cur, prep["volume_mm3"], rho)
                except Exception as e:                   # noqa: BLE001 - the comparison is then without it, and says so
                    if getattr(e, "extra", {}).get("kind") == "cancelled":
                        raise
                    before = {"error": str(e), "volume_mm3": round(prep["volume_mm3"], 2)}
            for name in ("frames.json", "body.stl"):
                if (work / name).is_file():
                    shutil.move(str(work / name), str(base / name))
            if res.get("body"):
                res["body"]["path"] = str(base / "body.stl")
            rec = {**res, "id": run_id, "version": VERSION, "project": pid, "rev": rev["n"], "study": sid,
                   "geometry_key": st.keys(p)["geometry"], "ts": time.time(), "reconstruction": recon,
                   "comparison": _compare(res, recon, before if "error" not in (before or {}) else None),
                   "material": {k: m.get(k) for k in ("name", "key", "E", "nu", "density", "yield", "sources")},
                   "frames_file": str(base / "frames.json")}
            sf_low = (recon.get("verified") or {}).get("safety_factor_low")
            tries.append({"try": attempt + 1, "volfrac": round(volfrac, 4), "status": recon.get("status"),
                          "safety_factor_low": sf_low, "mass_g": (recon.get("verified") or {}).get("mass_g"),
                          "why": recon.get("why")})
            shutil.rmtree(work, ignore_errors=True)
            target = o.get("safety_factor")
            if not target or (sf_low is not None and sf_low >= target):
                break
            if volfrac >= 0.9 or attempt + 1 >= o["tries"]:
                break
            volfrac = min(0.9, volfrac + max(0.08, 0.5 * (1 - volfrac) * (1 - (sf_low or 0) / target)))
    except Exception:
        shutil.rmtree(base, ignore_errors=True)
        raise
    rc = rec["reconstruction"]
    rec["tries"] = tries
    rec["targets"] = {k: o.get(k) for k in ("volfrac", "mass_g", "safety_factor") if o.get(k) is not None}
    if o.get("safety_factor"):
        low = (rc.get("verified") or {}).get("safety_factor_low")
        rec["target_met"] = bool(low is not None and low >= o["safety_factor"])
        if not rec["target_met"]:
            rec["target_why"] = (f"After {len(tries)} tr{'y' if len(tries) == 1 else 'ies'} the rebuilt part's safety factor is "
                                 f"{low if low is not None else 'not available'}, below the {o['safety_factor']:g} asked for.")
    rec["outcome"] = "features" if rc.get("status") == "verified" else \
        "features, not verified" if rc.get("built") and rc.get("features") else "mesh body" if rec.get("body") else "none"
    if rec["outcome"] != "features":
        rec["fallback"] = ({"offer": "mesh body", **rec["body"]} if rec.get("body") else None)
    rec["wall_seconds"] = round(time.time() - t0, 1)
    rec["budget"] = {"wall_seconds": rec["wall_seconds"], "optimisation_solves": rec["mesh"]["solves"],
                     "strength_studies": len(tries) + (1 if before and "error" not in before else 0),
                     "tries": len(tries), "resolution": rec.get("resolution")}
    rec["evidence"] = ("simulated (FEA) on the rebuilt CAD" if rc.get("status") == "verified" else
                       "computed (B-rep), strength not verified" if rc.get("built") else "simulated (density field, one mesh)")
    rec["headline"] = _headline(rec)
    _write(base / "record.json", rec)
    for old in sorted(_dir(st, p).glob("*/record.json"), key=lambda x: x.stat().st_mtime, reverse=True)[4:]:
        shutil.rmtree(old.parent, ignore_errors=True)     # the newest few runs are kept
    try:
        st.activity(pid, "study", f"Topology optimisation: {rec['headline']} [{rec['evidence']}]", by="engine")
    except Exception:                                    # noqa: BLE001 - the feed is not the record
        pass
    return rec


def start(st, pid: str, opts: dict | None = None) -> dict:
    """Run in the background. Returns the job (Studio.jobs: progress, cancel). One run per design at a time."""
    from .. import taskstore
    o = clean(opts)
    p = st.load(pid)
    busy = running_job(st, pid)
    if busy is not None:
        return busy
    sid = fea_study.pick_static(p, o.get("study", ""))   # refuse now what cannot run
    fea_study.materials_for(st, p, fea_study.get(p, sid))
    if python(st.cfg) is None:
        raise _err("The strength solver is not installed, so nothing was optimised. No result was made up.", HOW_TO_GET,
                   status=409, kind="unavailable")
    step = {"node": "topology", "label": "Topology optimisation", "state": "running",
            "progress": {"label": "Queued", "value": 0.0}}
    job = {"id": uuid.uuid4().hex[:10], "project": pid, "kind": "topology", "state": "running", "started": time.time(),
           "steps": [step]}
    st.jobs[job["id"]] = job
    jid = job["id"]

    def on_progress(ev):
        step["progress"] = {"label": ev.get("progress"), "value": ev.get("fraction"), "seconds": ev.get("seconds"),
                            **{k: ev[k] for k in ("iteration", "compliance", "volume") if k in ev}}
        st.jobs.save(job)

    def work():
        try:
            r = run(st, pid, o, on_progress=on_progress, cancelled=lambda: st.jobs.cancel_requested(jid), job=job)
            step["state"] = "done"
            job["state"] = "done"
            job["result"] = {"run": r["id"], "headline": r["headline"], "evidence": r["evidence"], "outcome": r["outcome"]}
        except Exception as e:                           # noqa: BLE001 - the job carries the failure
            was = getattr(e, "extra", {}).get("kind") == "cancelled"
            step["state"] = job["state"] = "cancelled" if was else "failed"
            job["error"] = e.public() if hasattr(e, "public") else {"message": f"{type(e).__name__}: {e}"}
        step.pop("progress", None)
        job.pop("work", None)
        job["finished"] = time.time()
        st.jobs.save(job)
        st.jobs.clear_cancel(jid)
    taskstore.child("topology", jid, pid, lambda: st.jobs.request_cancel(jid), lambda: job["state"] != "running",
                    lambda: (step.get("progress") or {}).get("label") or step["label"])
    threading.Thread(target=work, daemon=True, name=f"topology-{jid}").start()
    return job


# ---- keep it ------------------------------------------------------------------------------------------------------------

def apply(st, pid: str, run: str = "", expect_head: int | None = None, as_new: str | bool = False,
          mesh_body: bool = False, origin: str = "agent") -> dict:
    """Keep a run. Default: its pockets become features of the design, one revision. as_new: in a copy of the design
    instead (a name, or True), the original untouched. mesh_body: the smoothed body is added to the design's
    references as an STL, labelled; the design itself does not change."""
    from .. import modelling
    p = st.load(pid)
    rec = get(st, p, run)
    if rec is None:
        raise _err("This design has no topology run to keep.", "Run topology_optimise first.", status=404)
    if rec.get("stale"):
        raise _err("The design changed since this run, so its pockets were fitted to another solid.",
                   "Run topology_optimise again on the current revision.", status=409)
    if mesh_body:
        body = rec.get("body")
        if not body or not Path(body.get("path", "")).is_file():
            raise _err("This run has no mesh body.")
        name = f"topology-{rec['id']}.stl"
        ref = st.import_reference(p, Path(body["path"]), name=name)
        return {"kept": "mesh body", "reference": name, "label": body["label"], "volume_fraction": body["volume_fraction"],
                "note": "A mesh, not editable CAD: it sits beside the design as a reference. The design is unchanged.",
                "import": {k: ref.get(k) for k in ("name", "volume_mm3", "bbox") if isinstance(ref, dict) and k in ref}}
    rc = rec.get("reconstruction") or {}
    if not rc.get("ops") or not rc.get("built"):
        raise _err("This run has no features to keep: " + (rc.get("why") or "the reconstruction failed."),
                   "mesh_body=True keeps the smoothed body as a labelled mesh instead.", status=409)
    target = pid
    if as_new:
        copy = st.duplicate_project(pid, as_new if isinstance(as_new, str) else f"{p['name']} (topology)")
        target = copy["id"]
        expect_head = None
    ver = rc.get("verified") or {}
    note = "Topology optimisation: " + rc["summary"] + (
        f"; studied safety factor {ver['safety_factor']:.2f}" if ver.get("safety_factor") is not None else "; strength not verified")
    r = modelling.commit(st, st.load(target), rc["ops"], expect_head, origin, note)
    return {"kept": "features", "project": target, "head": r["head"], "copy_of": pid if as_new else None,
            "features": rc["features"], "parameters": rc["parameters"], "said": note,
            "verified": ver or None, "status": rc.get("status"),
            "next": "The strength study is stale on the new revision: run it again to store its result there. The "
                    "pockets are features (suppress, delete or reshape them) and topo_inset, topo_fillet and "
                    "topo_web are parameters."}
