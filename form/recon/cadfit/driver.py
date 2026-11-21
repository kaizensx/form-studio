"""CADFit's pipeline run in one process, in a work folder of its own (what upstream run_pipeline.py does with a
subprocess per step). Runs only inside the CADFit child process that cadfit/__init__.py starts and kills at its
deadline.

Analysis and search (run_pipeline.run_analysis_steps, with its settings: 5 axis slices, delta 0.01):

    1  planar contours        vendor/extract_planar_contours.py   planes found on the surface, sliced into loops
    2  split                  vendor/split_loops.py               loops grouped with the holes inside them
    3  axis-aligned sketches  vendor/extract_sketches.py          slices along x, y and z
    4  split, combine         vendor/split_loops.py, pipeline_steps.py (nested entries dropped)
    5  translation analysis   vendor/analyze_loop_translation.py  how far each loop sweeps along its normal on the surface
    6  revolve analysis       vendor/analyze_revolve_axis.py      symmetry axes a loop revolves about on the surface
    7  greedy search          vendor/greedy_search.py             extrusions and revolves kept while they raise the IoU,
                                                                  beam refinement, backward pruning

Then the residual refinement (run_pipeline.process_single_stl): what the program has too much of is reconstructed
the same way and cut, what it lacks is reconstructed and added, while time is left; the best program seen at any
step is kept. Not run here: the fillet/chamfer pass (off by default upstream; written for CadQuery) and the optional
DINOv2 loop filter (it downloads weights). Every step's best program so far is passed to `emit`, so a deadline that
ends the process mid-step keeps what was found. Part of the CADFit folder: see PERMISSION.md.
"""
from __future__ import annotations

import contextlib
import io
import json
import time
from pathlib import Path

OVER, UNDER = 0.02, 0.01        # residual volume (share of the mesh's) above which a cut / union pass runs (upstream)
ITERATIONS = 5                  # upstream's default max_iterations for process_single_stl


def analyse(stl: Path, work: Path, normalize: bool, steps: dict, prefix: str = "") -> Path | None:
    """Steps 1-7 on `stl` into `work`; the path of the program found (best_greedy_parallel.py), or None."""
    from .vendor import (analyze_loop_translation as alt, analyze_revolve_axis as ara, extract_planar_contours as epc,
                         extract_sketches as es, greedy_search as gs, split_loops as sl)
    from .vendor.pipeline_steps import _drop_nested_entries
    work.mkdir(parents=True, exist_ok=True)
    s = str(stl)
    nz = ["--normalize"] if normalize else []
    planar, planar_split = work / "planar_contours.json", work / "planar_loops_split.json"
    axis, axis_split = work / "axis_sketches.json", work / "axis_loops_split.json"
    loops, revolve = work / "loops_split.json", work / "loops_split_revolve.json"
    trans, rev = work / "translation_analysis", work / "revolve_analysis"

    def step(name, fn):
        t = time.perf_counter()
        try:
            return fn()
        finally:
            steps[prefix + name] = round(steps.get(prefix + name, 0.0) + time.perf_counter() - t, 2)
    step("planar contours", lambda: epc.main([s, "--out", str(planar), "--delta", "0.01", *nz, "--num-workers", "1"]))
    step("split loops", lambda: sl.split_loops(str(planar), str(planar_split), group_contained=True))
    step("axis sketches", lambda: es.main([s, "--out", str(axis), "--axis-slices", "5", *nz]))
    try:
        step("split loops", lambda: sl.split_loops(str(axis), str(axis_split), group_contained=True))
    except Exception:                                   # noqa: BLE001 - upstream carries on without them too
        pass
    combined = []
    for p in (planar_split, axis_split):
        if p.exists():
            combined += json.loads(p.read_text())
    combined = step("combine loops", lambda: _drop_nested_entries(combined))
    loops.write_text(json.dumps(combined))
    revolve.write_text(axis.read_text() if axis.exists() else "[]")
    step("translation analysis", lambda: alt.analyze_all_loops(str(loops), s, output_folder=str(trans),
                                                               normalize=normalize, num_workers=1, save_plots=False))
    step("revolve analysis", lambda: ara.analyze_all_revolve_axes(str(revolve), s, output_folder=str(rev),
                                                                  angle_range=(0, 90), step=90, num_workers=1,
                                                                  normalize=normalize, save_plots=False,
                                                                  cd_threshold=0.01))
    step("greedy search", lambda: gs.run_greedy_search(str(loops), str(revolve), s, str(trans), str(rev),
                                                       output_folder=str(work), normalize=normalize, num_workers=1))
    best = work / "best_greedy_parallel.py"
    return best if best.exists() and (work / "best_greedy_parallel.stl").exists() else None


def run(stl: Path, work: Path, emit=None, deadline: float | None = None) -> dict:
    """Run CADFit on `stl` inside `work`. Returns (and passes to `emit` whenever it improves) {"script": the best
    CadQuery program text or None, "iou": its IoU against the mesh, "steps": seconds per step, "passes": ...}."""
    from . import cqrun
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cqrun.allow(work)
    out = {"steps": {}, "script": None, "iou": None, "passes": []}
    emit = emit or (lambda d: None)
    left = (lambda: deadline - time.perf_counter()) if deadline else (lambda: float("inf"))
    sink = io.StringIO()                                # CADFit prints a great deal; keep it out of the worker's output
    with contextlib.redirect_stdout(sink):
        _run(Path(stl), work, out, emit, left)
    if out["script"] is None:
        out["error"] = "CADFit found no operation that matches the mesh"
    out["final"] = True
    return out


def _run(stl, work, out, emit, left):
    from .vendor.iou import mesh_iou_cpu_boolean
    from .vendor.pipeline_steps import combine_cadquery_scripts, compute_difference_mesh, compute_mesh_volume
    from . import cqrun
    steps = out["steps"]
    script = analyse(stl, work / "search", True, steps)
    if script is None:
        return

    def score(stl_path):
        try:
            return float(mesh_iou_cpu_boolean(str(stl), str(stl_path), normalize=True))
        except Exception:                               # noqa: BLE001
            return None

    def keep(py, st, what):
        v = score(st)
        out["passes"].append({"pass": what, "iou": None if v is None else round(v, 6)})
        if v is not None and (out["iou"] is None or v > out["iou"] + 1e-9):
            out["script"], out["iou"] = py.read_text(encoding="utf-8"), v
            emit(dict(out))
        return v
    cur_py, cur_stl = script, script.with_suffix(".stl")
    keep(cur_py, cur_stl, "greedy search")
    gt_vol = compute_mesh_volume(str(stl), normalize=True)
    under = 10.0
    it = 0
    while it < ITERATIONS and under > UNDER and left() > 0:
        it += 1
        for kind in ("cut", "union"):
            if left() <= 0:
                return
            res = work / f"{'over' if kind == 'cut' else 'under'}_{it}.stl"
            a, b = (cur_stl, stl) if kind == "cut" else (stl, cur_stl)
            ok = compute_difference_mesh(str(a), str(b), str(res), normalize_a=(kind == "union"),
                                         normalize_b=(kind == "cut"))
            if not ok or not res.exists():
                return
            ratio = compute_mesh_volume(str(res)) / gt_vol if gt_vol > 0 else 0.0
            if kind == "union":
                under = ratio
            if ratio <= (OVER if kind == "cut" else UNDER):
                continue
            sub = analyse(res, work / f"refine_{kind}_{it}", False, steps, prefix="refine: ")
            if sub is None:
                continue
            comb = work / f"reconstruction_{kind}_{it}.py"
            if not combine_cadquery_scripts(str(cur_py), str(sub), str(comb), operation=kind):
                continue
            try:
                cqrun.run_script(comb.read_text(encoding="utf-8"))
            except Exception:                           # noqa: BLE001 - upstream skips a combined script that fails
                continue
            if comb.with_suffix(".stl").exists():
                cur_py, cur_stl = comb, comb.with_suffix(".stl")
                keep(cur_py, cur_stl, f"{kind} {it}")
