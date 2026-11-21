"""Mesh to editable CAD, end to end. Kernel worker only (form/kernel.py runs `op_reconstruct`).

    Layer 2  first: the program route (program.py), sketches extruded and lofted between levels read straight off
             the mesh, the rest kept as the mesh's own slices. When it verifies and the Params drive most of the
             surface, it is the result and the slower layers below are not built.
    Layer 0  the mesh as an exact solid                              solid.layer0
    Layer 1  analytic faces where they fit, frozen facets elsewhere segment.segment + brep.build
    Layer 2  a feature recipe on the Layer 1 solid (tree.py, features.py), compared with the program route

Each layer is verified against the mesh before it is offered; the result is the verified layer whose Params drive the
most of the surface ("editable"), and every result says how far it is from the mesh and whether that is within the
tolerance asked for. Nothing is decimated, nothing is repaired without being listed under "repairs". While it runs it
reports progress about every second (a heartbeat repeats the last step while a long one runs).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from . import bounded
from . import mesh as meshmod
from . import verify

LIMITS = [
    "Units are taken as millimetres unless the file says otherwise (3MF does).",
    "Accuracy is measured against the mesh, not against the object it was made from: the mesh's own chord error "
    "and any scan noise are part of the input.",
    "Planes, cylinders, cones, spheres and tori are recognised as such. Smooth regions none of them explains are fitted "
    "with B-spline patches (freeform: smooth CAD within the tolerance, not a dimension you can change); what neither "
    "explains stays as frozen facets.",
    "Layer 2 rebuilds a base (extrusion stack, revolution, or the reconstructed solid kept exactly) and puts holes, "
    "fillets and chamfers back as operations; a feature that does not verify stays in the base and is listed.",
    "A curved surface is accepted when every mesh vertex on it is within the tolerance; a freeform surface that a "
    "simple one approximates within the tolerance is reported as that simple surface.",
    "Editable is the share of the result's surface that its Params make (sketches, extrusions, holes, fillets): "
    "what the mesh's own facets or a kept slice of the mesh make is not editable, however exact it is.",
]

PROGRAM_ENOUGH = 80.0      # % of the surface from its features at which the program route's result is taken alone
PROGRAM_SHARE = 0.25       # of the budget the program route may use; the layers below then get their own full budget
LEARNED = True             # ask the optional learned engine (learned/) for a candidate when it is installed
PROGRAM_SLACK = 25.0       # seconds the program route may run past its share before it is stopped (bounded.py)
LAYER1_SHARE = 0.55        # of the time left after Layer 0 that Layer 1 may use; Layer 2 has the rest
LEARNED_SHARE = 0.3        # of the time left that the optional learned engine may use
FINISH_S = 15.0            # seconds kept back for writing the result (STEP, deviation map, dimension check)


class Heartbeat:
    """Progress at least every `every` seconds: the last message is sent again (with the time so far) while a long
    step runs, so the app and the agent always see that work goes on. Thread-safe: one lock round every send."""

    def __init__(self, progress, every: float = 1.0):
        self.progress, self.every = progress, every
        self.lock = threading.Lock()
        self.last = None
        self.t0 = self.sent = time.perf_counter()
        self.done = threading.Event()
        self.thread = None
        if progress is not None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def say(self, d):
        if self.progress is None:
            return
        with self.lock:
            self.last = dict(d)
            self.sent = time.perf_counter()
            self.progress(d)

    def _run(self):
        while not self.done.wait(0.25):
            with self.lock:
                if self.last is None or time.perf_counter() - self.sent < self.every:
                    continue
                d = dict(self.last)
                d["text"] = f"{self.last.get('text', '')} ({time.perf_counter() - self.t0:.0f} s)"
                d["heartbeat"] = True
                self.sent = time.perf_counter()
                try:
                    self.progress(d)
                except Exception:                       # noqa: BLE001
                    pass

    def stop(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _step(shape, path: Path) -> None:
    from build123d import Shape, export_step
    export_step(Shape.cast(shape) if not hasattr(shape, "wrapped") else shape, str(path))


def _round(d, n=6):
    return {k: (round(v, n) if isinstance(v, float) else v) for k, v in d.items() if not k.startswith("_")}


def load(path: Path, fill: bool = True, weld_tol: float = 1e-6):
    """Read, weld, inspect. Returns (V, F, input_report, repairs)."""
    T, info = meshmod.read_triangles(path)
    V, F, w = meshmod.weld(T, weld_tol)
    top = meshmod.topology(V, F)
    repairs = []
    if w["dropped_collapsed"] or w["dropped_zero_area"] or w["dropped_duplicate"]:
        repairs.append({"repair": "dropped triangles", "collapsed": w["dropped_collapsed"], "zero_area": w["dropped_zero_area"],
                        "duplicate": w["dropped_duplicate"]})
    if w["merged_near_vertices"]:
        repairs.append({"repair": "welded near vertices", "count": w["merged_near_vertices"], "within_mm": weld_tol})
    if top["boundary_loops"] and fill and not top["non_manifold_edges"]:
        V, F, rec = meshmod.fill_holes(V, F, top["_loops"])
        repairs += rec
        top2 = meshmod.topology(V, F)
        top = {**top2, "before_repair": _round({k: v for k, v in top.items() if k in ("boundary_edges", "boundary_loops")})}
    if top["volume_mm3"] < 0:                          # inside out as a whole
        F = F[:, [0, 2, 1]]
        repairs.append({"repair": "turned the whole mesh outside in (its volume was negative)"})
        top = meshmod.topology(V, F)
    report = {**info, "weld": w, "topology": _round(top)}
    if top["_non_manifold_at"]:
        report["topology"]["non_manifold_at"] = top["_non_manifold_at"]
    return V, F, report, repairs


def reconstruct(path, out_dir, name: str | None = None, tolerance: float = 0.02, layer: int = 2,
                budget_s: float = 240.0, progress=None, fill_holes: bool = True) -> dict:
    """Reconstruct a mesh file as CAD. Writes <name>.step (the best verified layer), <name>_layer0.step (when Layer 0
    is built), <name>_report.json, <name>_deviation.json and, when Layer 2 succeeds, <name>_recipe.py (and the kept
    slices it reads, <name>_kept*.step). Returns the report."""
    beat = Heartbeat(progress)
    try:
        with bounded.session():                         # one warm helper for the bounded steps, started now
            return _reconstruct(path, out_dir, name, tolerance, layer, budget_s, beat.say if progress else None,
                                fill_holes)
    finally:
        beat.stop()


def _reconstruct(path, out_dir, name, tolerance, layer, budget_s, progress, fill_holes) -> dict:
    from . import solid
    t0 = time.perf_counter()
    hard = t0 + float(budget_s)                         # nothing runs past this: the steps that can are bounded
    fin = min(FINISH_S, 0.15 * float(budget_s))         # kept back for writing the result
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = Path(path)
    name = name or path.stem
    say = progress or (lambda d: None)
    say({"stage": "read", "text": f"Reading {path.name}", "fraction": 0.0})
    V, F, inp, repairs = load(path, fill=fill_holes)
    n = len(F)
    if n > 200_000:
        say({"stage": "read", "text": f"{n:,} triangles: this takes a while; nothing is decimated", "fraction": 0.01})
    tol = float(tolerance)
    rep = {"version": 1, "evidence": "computed", "input": inp, "repairs": repairs, "tolerance_mm": tol,
           "budget_s": float(budget_s),
           "layer_requested": int(layer), "layers": {}, "limits": list(LIMITS)}
    mvol = verify.mesh_volume(V, F)
    if not inp["topology"]["closed"]:
        rep["error"] = ("The mesh is not closed (" + f"{inp['topology']['boundary_loops']} open boundaries, "
                        f"{inp['topology']['non_manifold_edges']} non-manifold edges), so it does not bound a solid.")
        rep["hint"] = "Close it in the program that made it, or reconstruct with hole filling on (it is listed as a repair)."
        return _finish(rep, out, name, t0)

    # Layer 2, the program route: when it verifies and drives most of the surface, it is the result
    prog = None
    if layer >= 2:
        say({"stage": "layer2", "text": "Reading the part as sketches and extrusions", "fraction": 0.02})
        if _program is not _PROGRAM:                    # replaced in this process (a test, the bench's "before")
            got = {"status": "unbounded", "value": _program(V, F, tol, name, out, say, t0, budget_s)}
        else:
            got = bounded.run(_program_child, (V, F, tol, name, out, t0, budget_s),
                              timeout_s=min(PROGRAM_SHARE * float(budget_s) + PROGRAM_SLACK,
                                            _left(hard, fin) - _layer0_estimate(len(F))),
                              progress=lambda d: say({**d, "fraction": 0.02 + 0.6 * d.get("fraction", 0)}))
        prog = got.get("value") if got["status"] in ("ok", "unbounded") else None
        if prog is None:
            prog = {"report": {"method": "sketches and extrusions", "error": f"The program route {got.get('error')}"}}
            _cut(rep, "the program route (sketches and extrusions)", got)
        lc = None
        if LEARNED and _left(hard, fin) > 0 and _learned_installed():
            from . import learned as _lm
            if _lm.candidate is not _lm.CANDIDATE:      # replaced in this process (a test): run it here
                got_l = {"status": "unbounded", "value": _learned(V, F, tol, name, say)}
            else:
                got_l = bounded.run(_learned_child, (V, F, tol, name), timeout_s=LEARNED_SHARE * _left(hard, fin),
                                    progress=say)
            lc = got_l.get("value") if got_l["status"] in ("ok", "unbounded") else None
            if got_l["status"] not in ("ok", "unbounded"):
                _cut(rep, "the learned engine", got_l)
        if lc is not None:
            rep["learned"] = {"status": "installed", **{k: lc["report"].get(k) for k in (
                "engine", "licence", "verified", "hausdorff_mm", "params", "model_seconds", "seconds", "error")
                if lc["report"].get(k) is not None}}
            if lc.get("verified") and _better(lc, prog):  # verified and better, or it is never the result
                lc["report"]["also_tried"] = [{k: prog["report"].get(k) for k in (
                    "method", "verified", "hausdorff_mm", "editable_pct", "error") if prog["report"].get(k) is not None}]
                prog = lc
                rep["learned"]["chosen"] = True
        # optional CADFit candidate (cadfit/): off unless [recon] cadfit = true; its own time slice and child process
        from . import cadfit
        prog = cadfit.offer(prog, V, F, tol, name, say, budget_s, rep, _better)
        if prog.get("verified") and prog["report"].get("editable_pct", 0.0) >= PROGRAM_ENOUGH:
            why = (f"The program route verified first with {prog['report']['editable_pct']:g}% of the surface made by its "
                   "features; the slower layers were not needed.")
            rep["layers"]["0"] = {"skipped": why}
            rep["layers"]["1"] = {"skipped": why}
            return _take_program(rep, prog, V, F, mvol, out, name, t0, tol, budget_s)
    # the layers below have what is left of the budget: the program route is held to PROGRAM_SHARE of it (and stopped
    # PROGRAM_SLACK past that), and nothing runs past the budget as a whole (`hard`)
    tl = time.perf_counter() if prog is not None else t0
    if prog is not None:
        rep["program_seconds"] = round(tl - t0, 2)

    # Layer 0
    say({"stage": "layer0", "text": "Building the exact solid", "fraction": 0.02})
    P0 = T0 = c0 = None
    # Layer 0 is the fallback of every result: it may use all the time there is
    run0 = bounded.run(_layer0_child, (V, F), timeout_s=hard - 1.0 - time.perf_counter(),
                       progress=lambda d: say({**d, "fraction": 0.02 + 0.25 * d.get("fraction", 0)}))
    if run0["status"] in ("ok", "unbounded"):
        sh0, i0 = run0["value"]
    else:
        sh0, i0 = None, {"error": run0.get("error")}
        _cut(rep, "Layer 0 (the mesh as an exact solid)", run0)
    L0 = {"built": bool(i0.get("solid")), **{k: i0[k] for k in ("valid", "faces", "solids", "volume_mm3", "seconds") if k in i0}}
    if i0.get("solid"):
        P0, T0 = solid.tessellate(sh0, max(tol / 10, 1e-4))
        c0 = verify.compare(V, F, P0, T0)
        L0.update(_round(c0))
        _step(sh0, out / f"{name}_layer0.step")
        L0["step"] = f"{name}_layer0.step"
    else:
        L0["error"] = (f"Layer 0 {i0['error']}." if i0.get("error") else
                       f"Sewing left {i0.get('free_edges', 0)} free edges; the triangles do not close into a solid.")
    rep["layers"]["0"] = L0
    best = ("0", sh0, P0, T0, c0, None) if L0.get("valid") else None

    # A spur gear is recognised from the mesh itself (gears.py); when its parametric gear is within the tolerance,
    # it is the result and the surface-by-surface layer is not needed
    gear = None
    if layer >= 2 and best is not None:
        gear = _gear(V, F, tol, name, say)
        if gear is not None and gear.get("verified"):
            rep["layers"]["1"] = {"skipped": "A parametric gear was found and verified against the mesh first (Layer 2)."}

    # Layer 1
    regions = l1shape = None
    if layer >= 1 and best is not None and not (gear and gear.get("verified")):
        say({"stage": "layer1", "text": "Finding planes, cylinders, cones, spheres and tori", "fraction": 0.3})
        lim = LAYER1_SHARE * _left(hard, fin)
        run1 = bounded.run(_layer1, (V, F, tol), {"budget_s": max(5.0, 0.4 * lim)}, timeout_s=lim,
                           progress=lambda d: say({**d, "fraction": 0.3 + 0.4 * d.get("fraction", 0)}))
        if run1["status"] in ("ok", "unbounded"):
            got = run1["value"]
            for r in got.get("regions") or []:          # surfaces cached on a fit do not cross the process boundary
                if r.prim is not None and "_geom" in r.prim.p and r.prim.p["_geom"] is None:
                    del r.prim.p["_geom"]
        else:
            got = {"report": {"error": f"Layer 1 {run1.get('error')}; Layer 0 is the result."}}
            _cut(rep, "Layer 1 (planes, cylinders, cones, spheres, tori and B-spline patches)", run1)
        rep["layers"]["1"] = got["report"]
        if got.get("shape") is not None:
            regions = got["regions"]
            l1shape = got["shape"]
            best = ("1", got["shape"], got["P"], got["T"], got["cmp"], regions)

    # Layer 2
    recipe = None
    refs = []
    ref_paths = {}
    if gear is not None and gear.get("verified"):
        recipe = gear["source"]
        (out / f"{name}_recipe.py").write_text(recipe, encoding="utf-8")
        rep["layers"]["2"] = {**gear["report"], "file": f"{name}_recipe.py", "driven_by_params_pct": 100.0}
        best = ("2", gear["shape"], gear["P"], gear["T"], gear["cmp"], None)
    elif layer >= 2 and regions is not None:
        say({"stage": "layer2", "text": "Looking for features: base, holes, fillets, chamfers, patterns", "fraction": 0.72})
        lim = _left(hard, fin)
        run2 = bounded.run(layer2, (V, F, regions, l1shape, tol, name, out, rep["layers"]["1"]),
                           {"deadline": time.perf_counter() + 0.85 * lim}, timeout_s=lim,
                           progress=lambda d: say({**d, "fraction": 0.72 + 0.25 * d.get("fraction", 0)}))
        if run2["status"] in ("ok", "unbounded"):
            r2 = run2["value"]
        else:
            r2 = {"report": {"method": "feature tree", "error": f"The feature search {run2.get('error')}"}}
            _cut(rep, "Layer 2's feature search (base, holes, fillets, chamfers, patterns)", run2)
        if gear is not None:
            r2["report"]["also_tried"] = r2["report"].get("also_tried", []) + [
                {k: gear["report"].get(k) for k in ("method", "base", "verified", "hausdorff_mm", "error") if gear["report"].get(k) is not None}]
        if prog is not None and _better(prog, r2):
            r2 = {**prog, "report": {**prog["report"], "also_tried": [
                {k: r2["report"].get(k) for k in ("method", "base", "verified", "hausdorff_mm", "driven_by_params_pct", "error")
                 if r2["report"].get(k) is not None}]}}
        elif prog is not None:
            r2["report"]["also_tried"] = r2["report"].get("also_tried", []) + [
                {k: prog["report"].get(k) for k in ("method", "verified", "hausdorff_mm", "editable_pct", "error")
                 if prog["report"].get(k) is not None}]
        rep["layers"]["2"] = r2["report"]
        if r2.get("source"):
            recipe = r2["source"]
            (out / f"{name}_recipe.py").write_text(recipe, encoding="utf-8")
            rep["layers"]["2"]["file"] = f"{name}_recipe.py"
            if r2.get("verified"):
                best = ("2", r2["shape"], r2["P"], r2["T"], r2["cmp"], regions)
                refs = sorted(r2.get("refs") or [])
                ref_paths = dict(r2["refs"]) if isinstance(r2.get("refs"), dict) else {}

    if prog is not None and prog.get("verified") and (best is None or best[0] != "2"):
        rep["layers"]["2"] = {**prog["report"], **({"also_tried": rep["layers"]["2"].get("also_tried", [])}
                                                  if isinstance(rep["layers"].get("2"), dict) else {})}
        return _take_program(rep, prog, V, F, mvol, out, name, t0, tol, budget_s)
    if best is None:
        rep["error"] = "No layer produced a valid solid."
        return _finish(rep, out, name, t0)
    lay, shape, P, T, cmp, regs = best
    _step(shape, out / f"{name}.step")
    vol = solid.check(shape)["volume_mm3"]
    # what the surfaces are (Layer 1's split; a gear found first is all recipe), and for a recipe how much of the
    # area its Params drive
    area = rep["layers"]["1"] if lay in ("1", "2") else None
    if lay == "2" and (area or {}).get("skipped"):
        par, ff = 100.0, 0.0
    else:
        par = (area or {}).get("parametric_area_pct", 0.0)
        ff = (area or {}).get("freeform_area_pct", 0.0)
    rep["layer_achieved"] = int(lay)
    rep["result"] = {"layer": int(lay), "step": f"{name}.step", "recipe": f"{name}_recipe.py" if recipe else None,
                     "recipe_references": refs if lay == "2" else [],
                     "recipe_verified": bool(lay == "2"), "volume_mm3": round(vol, 4), "mesh_volume_mm3": round(mvol, 4),
                     "volume_delta_mm3": round(vol - mvol, 4), "volume_delta_pct": round(100 * (vol - mvol) / mvol, 5) if mvol else None,
                     "hausdorff_mm": round(cmp["hausdorff_mm"], 6), "parametric_area_pct": par, "freeform_area_pct": ff,
                     "frozen_area_pct": round(max(0.0, 100.0 - par - ff), 2),
                     "driven_by_params_pct": rep["layers"]["2"].get("driven_by_params_pct") if lay == "2" else 0.0}
    if lay == "2" and recipe:
        _dimensions(rep, recipe, ref_paths, t0, budget_s, say)
    _headline(rep, tol)
    dmap = verify.deviation_map(P, T, cmp["_rec_dev"], tol)
    (out / f"{name}_deviation.json").write_text(json.dumps(dmap), encoding="utf-8")
    rep["result"]["deviation_map"] = f"{name}_deviation.json"
    return _finish(rep, out, name, t0)


def _left(hard, fin=FINISH_S) -> float:
    """Seconds left before the budget's end, less what writing the result takes (fin)."""
    return hard - fin - time.perf_counter()


def _cut(rep, what, run):
    """Note a step that the budget (or a crash) cut short: the result is the best found without it."""
    rep.setdefault("cut_short", []).append({"step": what, "status": run["status"], "seconds": run.get("seconds"),
                                            "why": run.get("error")})


def _learned_installed() -> bool:
    try:
        from . import learned
        return bool(learned.status()["installed"])
    except Exception:                                   # noqa: BLE001
        return False


def _layer0_estimate(n_tris: int) -> float:
    """Seconds Layer 0 takes for this many triangles, about (measured: 2.3 s for 9,480 in the helper)."""
    return 2.0 + n_tris / 4000.0


def _layer0_child(V, F, progress=None):
    from . import solid
    return solid.layer0(V, F, progress=progress)


def _learned_child(V, F, tol, name, progress=None):
    return _learned(V, F, tol, name, progress or (lambda d: None))


def _program_child(V, F, tol, name, out, t0, budget_s, progress=None):
    """_program in the bounded child: the plan (only used in this process) is not sent back."""
    got = _program(V, F, tol, name, out, progress or (lambda d: None), t0, budget_s, raw=True)
    got.pop("plan", None)
    return got


def _program(V, F, tol, name, out, say, t0, budget_s, raw=False) -> dict:
    """The program route (program.py), within PROGRAM_SHARE of the budget. Never raises."""
    from . import program
    try:
        return program.recipe(V, F, tol, name=name, limit=tol, out_dir=out,
                              progress=say if raw else lambda d: say({**d, "fraction": 0.02 + 0.6 * d.get("fraction", 0)}),
                              deadline=t0 + PROGRAM_SHARE * float(budget_s))
    except Exception as e:                              # noqa: BLE001
        return {"report": {"method": "sketches and extrusions", "error": f"{type(e).__name__}: {e}"[:300]}}


def _learned(V, F, tol, name, say):
    """The learned engine's candidate (learned/), or None when it is not installed. Never raises."""
    try:
        from . import learned
        if not learned.status()["installed"]:
            return None
        say({"stage": "layer2", "text": "Asking the learned engine for a sketch program", "fraction": 0.3})
        return learned.candidate(V, F, tol, name=name, limit=tol)
    except Exception as e:                              # noqa: BLE001
        return {"report": {"method": "learned engine", "error": f"{type(e).__name__}: {e}"[:300]}, "verified": False}


_PROGRAM = _program


def _better(a, b) -> bool:
    """Is recipe result a better answer than b: verified first, then the share of the surface its Params drive, then
    the distance to the mesh."""
    def key(r):
        rp = r.get("report", {})
        drv = rp.get("editable_pct", rp.get("driven_by_params_pct")) or 0.0
        return (bool(r.get("verified")), round(float(drv), 1), -float(rp.get("hausdorff_mm") or 1e9))
    return key(a) > key(b)


def _take_program(rep, prog, V, F, mvol, out, name, t0, tol, budget_s=240.0):
    """Finish the report with the program route's result."""
    from . import solid
    r2 = prog["report"]
    rep["layers"].setdefault("2", r2)
    if rep["layers"]["2"] is not r2 and not rep["layers"]["2"].get("kind") == "program":
        rep["layers"]["2"] = r2
    (out / f"{name}_recipe.py").write_text(prog["source"], encoding="utf-8")
    rep["layers"]["2"]["file"] = f"{name}_recipe.py"
    shape, P, T, cmp = prog["shape"], prog["P"], prog["T"], prog["cmp"]
    _step(shape, out / f"{name}.step")
    vol = solid.check(shape)["volume_mm3"]
    edit = float(r2.get("editable_pct", 0.0))
    rep["layer_achieved"] = 2
    rep["result"] = {"layer": 2, "step": f"{name}.step", "recipe": f"{name}_recipe.py",
                     "recipe_references": sorted(prog.get("refs") or []), "recipe_verified": True,
                     "method": r2.get("method") or "sketches and extrusions",
                     "volume_mm3": round(vol, 4), "mesh_volume_mm3": round(mvol, 4),
                     "volume_delta_mm3": round(vol - mvol, 4),
                     "volume_delta_pct": round(100 * (vol - mvol) / mvol, 5) if mvol else None,
                     "hausdorff_mm": round(cmp["hausdorff_mm"], 6),
                     # the features make planes, cylinders and cones; the kept slices are the mesh's own facets
                     "parametric_area_pct": round(edit, 2), "freeform_area_pct": 0.0,
                     "frozen_area_pct": round(100.0 - edit, 2), "driven_by_params_pct": round(edit, 2),
                     "params": r2.get("params")}
    refs = prog.get("refs") or {}
    _dimensions(rep, prog["source"], {k: str(v) for k, v in refs.items()} if isinstance(refs, dict) else {},
                t0, budget_s, lambda d: None)
    _headline(rep, tol)
    dmap = verify.deviation_map(P, T, cmp["_rec_dev"], tol)
    (out / f"{name}_deviation.json").write_text(json.dumps(dmap), encoding="utf-8")
    rep["result"]["deviation_map"] = f"{name}_deviation.json"
    return _finish(rep, out, name, t0)


DIMENSION_TIME = (5.0, 30.0)   # seconds the dimension check may take: at least, at most (within what is left)


def _dimensions(rep, src, refs, t0, budget_s, say):
    """Which Params are real dimensions that move (program.movable_dimensions), within what is left of the budget."""
    from . import program
    left = float(budget_s) - (time.perf_counter() - t0) - 3.0
    say({"stage": "layer2", "text": "Checking which dimensions can be changed", "fraction": 0.96})
    try:
        d = program.movable_dimensions(src, refs, deadline=time.perf_counter()
                                       + min(DIMENSION_TIME[1], max(min(DIMENSION_TIME[0], FINISH_S - 5.0), left)))
    except Exception as e:                              # noqa: BLE001
        d = {"error": f"{type(e).__name__}: {e}"[:300], "params": 0, "dimensions": 0, "movable": 0}
    rep["result"]["dimensions"] = d


def _headline(rep, tol):
    """Editable first, then the deviation and whether it is within the tolerance asked for.

    Editable is the share of the design's Params that are real dimensions (lengths, diameters, radii, angles, levels;
    not the positions of sketch corners: program.is_dimension) and that move at least 0.5 mm with the design still
    building. The share of the surface that parametric features make (positions included) is reported beside it as
    feature_area_pct."""
    res = rep["result"]
    area = float(res.get("driven_by_params_pct") or 0.0)
    res["feature_area_pct"] = round(area, 2)
    d = res.get("dimensions") or {}
    n, mv = int(d.get("params") or 0), int(d.get("movable") or 0)
    res["editable_pct"] = round(100.0 * mv / n, 1) if n else 0.0
    h = float(res.get("hausdorff_mm") or 0.0)
    res["within_tolerance"] = bool(h <= tol + 1e-12)
    # the other number, never merged with editable: the share of the surface that is real CAD faces (analytic,
    # B-spline, or made by a feature) rather than a facet copy of the mesh, counted only within the tolerance
    res["brep_pct"] = round(max(0.0, 100.0 - float(res.get("frozen_area_pct") or 0.0)), 2) if res["within_tolerance"] else 0.0
    if n:
        what = (f"{res['editable_pct']:g}% editable ({mv} of {n} Params are dimensions that move "
                f"{d.get('move', 0.5):g} mm), {h:.4g} mm from the mesh; {res['feature_area_pct']:g}% of the surface "
                "from parametric features")
    else:
        what = f"0% editable (an exact copy of the mesh as a solid, no dimensions), {h:.4g} mm from the mesh"
    what += f"; {res['brep_pct']:g}% of the surface is real CAD faces"
    res["headline"] = what + ("" if res["within_tolerance"] else f", outside the {tol:g} mm asked for")
    if not res["within_tolerance"]:
        res["warning"] = (f"The result is {h:.4g} mm from the mesh, more than the {tol:g} mm tolerance asked for: the best "
                          "verified layer is offered, but it is not within the tolerance.")


def _gear(V, F, tol, name, say):
    """The parametric spur gear of the mesh, or None when the mesh is not one (checked about its principal axes)."""
    from . import gears
    c = V.mean(axis=0)
    _, _, vt = np.linalg.svd(V - c, full_matrices=False)
    for d in vt[::-1]:
        try:
            g, _ = gears.analyse(V, F, d, tol)
        except Exception:                               # noqa: BLE001
            continue
        if g is not None and g["flank_fit_mm"] <= max(3 * tol, 0.05 * g["module"]):
            say({"stage": "layer2", "text": f"A spur gear: {g['teeth']} teeth; building it as a parametric gear", "fraction": 0.3})
            try:
                return gears.recipe(V, F, [d], tol, name=name)
            except Exception as e:                      # noqa: BLE001
                return {"report": {"method": "spur gear", "error": f"{type(e).__name__}: {e}"[:300]}}
    return None


def layer2(V, F, regions, l1shape, tol, name, out, l1rep, progress=None, deadline=None) -> dict:
    """The best verified recipe: the feature tree (tree.py) first, the single extrusion or revolution (features.py)
    when the tree is not within the limit. Both are reported."""
    from . import features, tree
    limit = max(tol, l1rep.get("hausdorff_mm", 0.0) * 1.05)
    say = progress or (lambda d: None)
    tried = []
    try:
        t = tree.recipe(V, F, l1shape, tol, name=name, limit=limit, out_dir=out,
                        progress=lambda d: say({**d, "fraction": 0.8 * d.get("fraction", 0)}), deadline=deadline)
    except Exception as e:                              # noqa: BLE001
        t = {"report": {"method": "feature tree", "error": f"{type(e).__name__}: {e}"[:300]}}
    if l1rep.get("exact_edges") and (not t.get("verified") or t["report"].get("base") in ("embedded solid", None)) and \
            (deadline is None or time.perf_counter() < deadline):
        # the feature search reads turned and stacked bases off the faces of the Layer 1 solid; built with the mesh's
        # own boundaries it sometimes finds a base the exact-edged solid hides: try that solid too, keep the better
        from . import brep
        keep = brep.EXACT_EDGES
        try:
            brep.EXACT_EDGES = False
            plain, info = brep.build(V, F, regions, tol)
        finally:
            brep.EXACT_EDGES = keep
        if plain is not None and info.get("valid"):
            try:
                t2 = tree.recipe(V, F, plain, tol, name=name, limit=limit, out_dir=out, deadline=deadline,
                                 progress=lambda d: say({**d, "fraction": 0.8 * d.get("fraction", 0)}))
            except Exception:                           # noqa: BLE001
                t2 = None
            if t2 is not None and t2.get("verified") and (not t.get("verified") or
                                                        (t2["report"].get("driven_by_params_pct") or 0) >
                                                        (t["report"].get("driven_by_params_pct") or 0)):
                t2["report"]["layer1_edges"] = "the mesh's own boundaries (the exact-edged solid hid the base)"
                t = t2
    tried.append(t)
    if not t.get("verified") and (deadline is None or time.perf_counter() < deadline):
        try:
            f = features.recipe(V, F, regions, tol, name=name, limit=limit,
                                progress=lambda d: say({**d, "fraction": 0.8 + 0.2 * d.get("fraction", 0)}))
            f["report"]["method"] = "single extrusion or revolution"
        except Exception as e:                          # noqa: BLE001
            f = {"report": {"method": "single extrusion or revolution", "error": f"{type(e).__name__}: {e}"[:300]}}
        tried.append(f)
    best = next((r for r in tried if r.get("verified")), None) or next((r for r in tried if r.get("source")), tried[0])
    rep = dict(best["report"])
    others = [r["report"] for r in tried if r is not best]
    if others:
        rep["also_tried"] = [{k: o.get(k) for k in ("method", "base", "kind", "verified", "hausdorff_mm", "error") if o.get(k) is not None}
                             for o in others]
    return {**best, "report": rep}


def _finish(rep, out, name, t0):
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    if rep.get("cut_short") and isinstance(rep.get("result"), dict):
        steps = "; ".join(f"{c['step']} ({c['status']} after {c.get('seconds') or 0:.0f} s)" for c in rep["cut_short"])
        rep["result"]["cut_short"] = [c["step"] for c in rep["cut_short"]]
        rep["result"]["note"] = (f"The time budget ({rep.get('budget_s', 0):g} s) cut short: {steps}. This is the best "
                                 "result found within it; a larger budget may find more.")
    (out / f"{name}_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def vertex_dev(r, V, F) -> float:
    return float(np.abs(r.prim.dist(V[np.unique(F[r.tris])])).max())


def _allowance(V, F, tris, reg, tol, chord=None):
    """Largest deviation each triangle of a region may have: the tolerance, plus on a curved surface the chord error a
    straight-edged triangle of that size must have there. `chord` is the mesh's chord error measured on surfaces that
    fit exactly; when known it caps that allowance."""
    if not reg.parametric or reg.kind == "plane":
        return np.full(len(tris), tol)
    if reg.kind == "bspline":                       # the flat facet's middle against the smooth surface: its chord error
        a, b, c = V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]]
        sag = np.max(np.abs(np.c_[reg.prim.dist((a + b + c) / 3), reg.prim.dist((a + b) / 2), reg.prim.dist((b + c) / 2),
                                  reg.prim.dist((c + a) / 2)]), axis=1)
        return tol + 1.25 * sag
    from .segment import chord_error
    ce = chord_error(reg.prim, V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]])
    return tol + (np.minimum(ce, chord * 1.25) if chord is not None else ce)


def _layer1(V, F, tol, budget_s, progress):
    from . import brep, segment, solid
    t0 = time.perf_counter()
    regions, st = segment.segment(V, F, tol, budget_s=budget_s, progress=progress)
    from . import freeform
    try:
        regions, st["freeform"] = freeform.apply(V, F, regions, tol, progress=progress)
    except Exception as e:                              # noqa: BLE001
        st["freeform"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    rounds = []
    cmp = None
    for attempt in range(5):
        shape, info = brep.build(V, F, regions, tol, progress=progress)
        frozen = []
        partial = {}                                    # region id -> its triangles that are off the surface
        if shape is None or not info.get("valid"):
            ids = sorted({f["region"] for f in info.get("face_failures", [])} | set(info.get("free_edge_regions", [])))
            if shape is not None and not ids:
                ids = brep.bad_regions(shape, regions, V, F)
            if not ids:                                 # no face to blame: the B-spline patches go first
                ids = [r.id for r in regions if r.kind == "bspline"]
            if not ids:
                rounds.append({"build": _round(info), "frozen": []})
                break
            frozen = ids
            cmp = None
        else:
            P, T = solid.tessellate(shape, max(tol / 10, 1e-4))
            cmp = verify.compare(V, F, P, T)
            dev = cmp["_tri_dev"]
            # the mesh's own chord error, seen where a curved surface fits the vertices almost exactly
            exact = [r for r in regions if r.parametric and r.kind != "plane" and vertex_dev(r, V, F) < tol / 20]
            chord = max((float(dev[r.tris].max()) for r in exact), default=None)
            for r in regions:
                off = dev[r.tris] > _allowance(V, F, r.tris, r, tol, chord)
                if r.parametric and np.any(off):
                    frozen.append(r.id)
                    if r.kind == "plane" and attempt < 3:         # a plane keeps the triangles that are on it
                        partial[r.id] = r.tris[off]
        rounds.append({"build": {k: info[k] for k in ("faces", "valid", "edges_line", "edges_circle", "edges_arc", "edges_curve",
                                                                 "edges_segment", "edges_exact", "corners_moved", "exact_edges")
                                 if k in info}, "hausdorff_mm": round(cmp["hausdorff_mm"], 6) if cmp else None,
                       "frozen_regions": [{"id": i, "kind": regions[i].kind} for i in frozen]})
        if not frozen:
            break
        regions = _freeze(V, F, regions, frozen, partial)
        shape = None
    summ = segment.summary(regions)
    rep = {**summ, "segmentation": st, "rounds": rounds, "exact_edges": bool(info.get("exact_edges")),
           "surfaces": [{"kind": r.kind, "triangles": int(len(r.tris)), "area_mm2": round(r.area, 4), **(r.prim.public() if r.prim else {})}
                        for r in sorted(regions, key=lambda r: -r.area) if r.parametric][:300]}
    if shape is None or cmp is None or not rounds or rounds[-1].get("frozen_regions"):
        rep["error"] = "The analytic faces did not close into a valid solid; Layer 0 is the result."
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep}
    vol = solid.check(shape)["volume_mm3"]
    rep.update({"valid": True, "volume_mm3": round(vol, 4), **_round(cmp), "seconds": round(time.perf_counter() - t0, 2)})
    return {"report": rep, "shape": shape, "regions": regions, "P": P, "T": T, "cmp": cmp}


def _freeze(V, F, regions, ids, partial=None):
    """Turn regions into frozen facets, one per triangle, and renumber. A region in `partial` freezes only the given
    triangles; the rest keep its surface, one region per connected piece (a plane with a bad corner stays a plane)."""
    from .segment import Region
    _, A = meshmod.tri_normals(V, F)
    ids = set(ids)
    partial = partial or {}
    out = []
    for r in regions:
        if r.id in ids and r.id in partial and len(partial[r.id]) < len(r.tris):
            bad = set(partial[r.id].tolist())
            good = np.array([t for t in r.tris.tolist() if t not in bad])
            out += [Region(0, "facet", np.array([t]), None, float(A[t])) for t in sorted(bad)]
            for piece in _pieces(F, good):
                out.append(Region(0, r.kind, piece, r.prim, float(A[piece].sum()), dict(r.info)))
        elif r.id in ids:
            out += [Region(0, "facet", np.array([t]), None, float(A[t])) for t in r.tris.tolist()]
        else:
            out.append(r)
    for i, r in enumerate(out):
        r.id = i
    return out


def _pieces(F, tris):
    """Triangles split into pieces connected through shared edges."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    tris = np.asarray(tris)
    if len(tris) < 2:
        return [tris] if len(tris) else []
    sub = F[tris]
    E = np.sort(np.concatenate([sub[:, [0, 1]], sub[:, [1, 2]], sub[:, [2, 0]]]), axis=1)
    owner = np.tile(np.arange(len(tris)), 3)
    _, inv = np.unique(E, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    o = np.argsort(inv, kind="stable")
    a, b = owner[o][:-1], owner[o][1:]
    same = inv[o][1:] == inv[o][:-1]
    g = coo_matrix((np.ones(int(same.sum())), (a[same], b[same])), shape=(len(tris), len(tris)))
    k, lab = connected_components(g, directed=False)
    return [tris[lab == i] for i in range(k)]
