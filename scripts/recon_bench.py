"""Mesh to editable CAD, measured per part class: two numbers, always apart.

    .venv/bin/python scripts/recon_bench.py                       # the part classes -> docs/RECON_BENCH.md
    .venv/bin/python scripts/recon_bench.py --classes flange      # one class
    .venv/bin/python scripts/recon_bench.py --mesh a.stl --out /tmp/bench.md   # your own meshes, elsewhere

For every part:

- **B-rep**: the share of the result's surface that is real CAD faces (planes, cylinders, cones, spheres, tori,
  B-spline patches, or the faces a feature makes) rather than a facet-for-facet copy of the mesh, counted only when
  the result is within the tolerance asked for (`result.brep_pct`).
- **Editable**: the share of the result's Params that are real dimensions (lengths, diameters, radii, angles, levels,
  pitches) and move 0.5 mm with the part still building (`result.editable_pct`, form/recon/program.py
  movable_dimensions). The surface share the features make is shown beside it.

Beside them, the critics (form/recon/gates.py) and a shape score compare the result's STEP with the part:

- **Occupancy IoU**: both filled on one voxel grid, intersection over union of the volumes.
- **GMS**: the GMS-compatible surface score (form/recon/gms.py), 1.0 for the same surface.
- **Gates**: "pass", or which of occupancy, voids and openings failed (gates.check), and the time they took.

Each part runs without the optional learned engine (form/recon/learned, CAD-Recode) and, when it is installed, with it.
It is never downloaded by this script. The parts are synthetic build123d parts (tests/recon_fixtures.py) exported as
STL. The "scan artifacts" class is one of them with noise, quantisation or missing faces added
(recon_fixtures.scan_artifact); its gates and GMS are measured against the clean part. Meshes passed with --mesh are
never written into docs/ unless --out says so: keep private parts out of the repository. Every number is computed
against the mesh.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

CLASSES = {
    "bracket": ["filleted_bracket", "stepped_bracket"],
    "flange": ["bolt_flange"],
    "turned shaft": ["turned_shaft", "flanged_shaft"],
    "enclosure with holes": ["enclosure_with_holes"],
    "filleted block": ["filleted_block"],
    "scan artifacts": ["bolt_flange+noise", "bolt_flange+quantised", "bolt_flange+dropout"],
}
TOL = {"gear": 0.05, "bolt_flange+noise": 0.05, "bolt_flange+quantised": 0.05, "bolt_flange+dropout": 0.05}


def critique(ref: Path, out: Path, res: dict, tol: float) -> dict:
    """The gates and GMS of the result's STEP against the reference mesh. Never raises."""
    empty = {"occupancy_iou": None, "gms": None, "gates": None, "gate_failed": None, "gate_seconds": None}
    if not res.get("step") or not (out / res["step"]).exists():
        return {**empty, "gates": "no STEP"}
    try:
        from build123d import import_step
        from form.kernel import _tessellate
        from form.recon import gates, gms, mesh
        T, _ = mesh.read_triangles(ref)
        V, F, _ = mesh.weld(T)
        P, Q = _tessellate(import_step(str(out / res["step"])), max(tol / 4, 0.002))
        g = gates.check(V, F, P, Q, tol)
        t = time.perf_counter()
        s = gms.gms(V, F, P, Q)["gms"]
        return {"occupancy_iou": g["occupancy"]["iou"], "gms": s, "gates": g["verdict"], "gate_failed": g["failed"],
                "gate_seconds": g["seconds"], "gms_seconds": round(time.perf_counter() - t, 2),
                "gate_detail": {"occupancy": {k: v for k, v in g["occupancy"].items() if k != "axes"},
                                "openings": g["openings"]["mismatches"][:4]}}
    except Exception as e:                              # noqa: BLE001
        return {**empty, "gates": f"error: {type(e).__name__}: {e}"[:200]}


def run(path: Path, tol: float, learned: bool, out: Path, budget: float, program_route: bool = True,
        ref: Path | None = None) -> dict:
    from form.recon import pipeline
    keep_prog, keep_learned = pipeline._program, getattr(pipeline, "LEARNED", False)
    if not program_route:
        pipeline._program = lambda *a, **k: {"report": {"method": "sketches and extrusions", "error": "off for the bench"}}
    pipeline.LEARNED = bool(learned)
    gaps, last = [], [time.perf_counter()]

    def prog(_d):
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
    t = time.perf_counter()
    try:
        rep = pipeline.reconstruct(path, out, path.stem, tol, 2, budget_s=budget, progress=prog)
    finally:
        pipeline._program, pipeline.LEARNED = keep_prog, keep_learned
    gaps.append(time.perf_counter() - last[0])
    res = rep.get("result") or {}
    L2 = rep.get("layers", {}).get("2", {}) or {}
    dims = res.get("dimensions") or {}
    seconds = round(time.perf_counter() - t, 1)
    return {"seconds": seconds, "layer": res.get("layer"),
            "method": res.get("method") or L2.get("method"),
            "brep_pct": res.get("brep_pct", brep_share(res)), "editable_pct": res.get("editable_pct"),
            "feature_area_pct": res.get("feature_area_pct"),
            "params": dims.get("params"), "movable": dims.get("movable"),
            "hausdorff_mm": res.get("hausdorff_mm"), "within": res.get("within_tolerance"),
            "triangles": rep.get("input", {}).get("triangles") or rep.get("input", {}).get("weld", {}).get("triangles"),
            "max_progress_gap_s": round(max(gaps), 2), "error": rep.get("error") or L2.get("error"),
            "learned": (rep.get("learned") or {}).get("status"),
            **critique(Path(ref or path), Path(out), res, tol)}


def isolated(path: Path, tol: float, learned: bool, out: Path, budget: float, ref: Path | None = None) -> dict:
    """run() in its own process: a part that crashes the CAD kernel (a segmentation fault in OpenCascade) is
    reported as crashed instead of ending the bench."""
    import subprocess
    args = json.dumps({"path": str(path), "tol": tol, "learned": learned, "out": str(out), "budget": budget,
                       "ref": str(ref or path)})
    t = time.perf_counter()
    limit = max(600.0, 4 * budget)
    try:
        p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--one", args], capture_output=True,
                           text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        p = None
    for line in reversed(p.stdout.splitlines() if p else []):
        if line.startswith("{"):
            return json.loads(line)
    why = f"did not finish in {limit:g} s" if p is None else f"crashed (exit code {p.returncode})"
    return {"seconds": round(time.perf_counter() - t, 1), "layer": None, "method": None, "brep_pct": 0.0,
            "editable_pct": 0.0, "feature_area_pct": None, "params": None, "movable": None, "hausdorff_mm": None,
            "within": False, "triangles": None, "max_progress_gap_s": 0.0, "learned": None,
            "error": f"the reconstruction {why}", "crashed": True, "occupancy_iou": None, "gms": None,
            "gates": None, "gate_failed": None, "gate_seconds": None}


def brep_share(res: dict) -> float:
    """B-rep share for a report written before `brep_pct` existed: the same rule (pipeline._headline)."""
    if not res or not res.get("within_tolerance"):
        return 0.0
    return round(max(0.0, 100.0 - float(res.get("frozen_area_pct") or 0.0)), 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classes", nargs="*", default=None, help=f"part classes (default: all): {', '.join(CLASSES)}")
    ap.add_argument("--fixtures", nargs="*", default=None, help="fixture names instead of classes")
    ap.add_argument("--mesh", nargs="*", default=[], help="extra meshes (kept out of docs/ unless --out says so)")
    ap.add_argument("--tol", type=float, default=None, help="tolerance for --mesh parts (default 0.05)")
    ap.add_argument("--out", default=None, help="Markdown report (default docs/RECON_BENCH.md for the classes)")
    ap.add_argument("--json", default=None, help="also write the rows as JSON here")
    ap.add_argument("--budget", type=float, default=240.0)
    ap.add_argument("--label", default="", help="a note on the run (shown in the report)")
    ap.add_argument("--one", default=None, help=argparse.SUPPRESS)          # internal: one part, in its own process
    a = ap.parse_args(argv)
    if a.one:
        o = json.loads(a.one)
        print(json.dumps(run(Path(o["path"]), o["tol"], o["learned"], Path(o["out"]), o["budget"],
                             ref=Path(o.get("ref") or o["path"])), default=str))
        return
    import recon_fixtures as fx
    try:
        from form.recon import learned
        status = learned.status()
    except ImportError:                                 # a checkout from before the learned engine existed
        status = {"installed": False}
    work = Path(tempfile.mkdtemp(prefix="recon-bench-"))
    if a.fixtures is not None:
        todo = [("fixtures", n) for n in a.fixtures]
    else:
        todo = [(c, n) for c in (a.classes or list(CLASSES)) for n in CLASSES.get(c, [])]
    parts = []
    for c, n in todo:
        base_name, _, artifact = n.partition("+")
        if base_name not in fx.FIXTURES or (artifact and artifact not in fx.SCAN_ARTIFACTS):
            print(f"skip {n}: no such fixture")
            continue
        try:
            stl = fx.export(base_name, work)[0]
            ref = stl
            if artifact:                                # the same part as a scanner would deliver it
                from form.recon import mesh
                V, F, _ = mesh.weld(mesh.read_triangles(stl)[0])
                Va, Fa = fx.scan_artifact(V, F, artifact)
                stl = work / f"{base_name}-{artifact}.stl"
                mesh.write_stl(stl, Va, Fa)
        except Exception as e:                          # noqa: BLE001
            print(f"skip {n}: {type(e).__name__}: {e}")
            continue
        parts.append((c, n, stl, TOL.get(n, 0.02), ref))
    for m in a.mesh:
        parts.append(("your meshes", Path(m).stem, Path(m), a.tol or 0.05, Path(m)))
    if a.out is None and a.mesh:
        ap.error("pass --out for your own meshes (docs/RECON_BENCH.md is for the synthetic part classes)")
    out_md = Path(a.out) if a.out else ROOT / "docs" / "RECON_BENCH.md"
    before = previous(out_md) if out_md.exists() else {}
    rows = []
    for c, n, p, tol, ref in parts:
        print(f"{c}: {n} ({tol:g} mm) ...", flush=True)
        safe = n.replace("+", "-")
        base = isolated(p, tol, False, work / f"{safe}-plain", a.budget, ref)
        print(json.dumps(base, default=str), flush=True)
        opt = isolated(p, tol, True, work / f"{safe}-learned", a.budget, ref) if status.get("installed") else None
        rows.append({"class": c, "part": n, "tol": tol, "without": base, "with": opt})
    write(out_md, rows, status, a.label, before)
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "learned": status, "label": a.label}, indent=1, default=str))
    print(f"wrote {out_md}")


def _f(x, nd=4):
    return "–" if x is None else (f"{x:.{nd}g}" if isinstance(x, float) else str(x))


def _pct(x):
    return "–" if x is None else f"{x:g}%"


def previous(path: Path) -> dict:
    """The main table of an earlier report, by part: what this run is compared with."""
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    head = None
    for ln in lines:
        if not ln.startswith("|"):
            if head:
                break
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if head is None:
            if "Part" in cells and "B-rep" in cells and "Editable" in cells and "Class" in cells:
                head = cells
            continue
        if set(ln) <= set("|-: "):
            continue
        row = dict(zip(head, cells))
        out[row["Part"]] = row
    return out


def _gate_cell(a):
    g = a.get("gates")
    if g is None:
        return "–"
    t = a.get("gate_seconds")
    return g + (f" ({t:g} s)" if isinstance(t, (int, float)) else "")


def write(path: Path, rows: list, status: dict, label: str = "", before: dict | None = None):
    L = ["# Mesh to editable CAD: benchmark", "",
         "Written by `scripts/recon_bench.py` from real runs of `form/recon` on synthetic build123d parts "
         "(`tests/recon_fixtures.py`, exported as STL). Two numbers, never merged:", "",
         "- **B-rep**: share of the result's surface that is real CAD faces (analytic, B-spline, or made by a feature) "
         "rather than a facet copy of the mesh, counted only when the result is within the tolerance.",
         "- **Editable**: share of the result's Params that are real dimensions and move 0.5 mm with the part still "
         "building. *Feature area* is the share of the surface the parametric features make.", "",
         "**Deviation** is the two-sided Hausdorff distance to the mesh. Computed, not assumed."
         + (f" Run: {label}." if label else ""), "",
         "The critics compare the result's STEP with the part (`form/recon/gates.py`, `form/recon/gms.py`):", "",
         "- **Occupancy IoU**: both filled on one voxel grid (winding number, so orientation counts); intersection "
         "over union of the volumes.",
         "- **GMS**: a GMS-compatible surface score (positions within 5 % of the part's largest extent, normals within "
         "0 to 25 degrees); 1.0 is the same surface. Reimplemented on scipy, not yet cross-checked against the "
         "upstream code.",
         "- **Gates**: `pass`, or which gates failed: *occupancy* (volume missing or added beyond a skin of the "
         "size-relative tolerance over the surface), *voids* (a void the part's slices enclose filled solid), "
         "*openings* (a hole, slot or pocket missing, added, or of another shape in a plane section). The time is "
         "what the gates took.",
         "- **Scan artifacts**: `bolt_flange` with Gaussian vertex noise (0.01 mm), coordinates quantised to "
         "0.02 mm, or 1 % of its triangles removed. Its critics are measured against the clean part.", ""]
    inst = status.get("installed")
    L.append("Optional learned engine (CAD-Recode, non-commercial licence): "
             + ("installed; the *with* columns use it." if inst else
                "not installed on the machine that wrote this, so only *without* is measured."))
    L.append("")
    L += ["| Class | Part | Tol (mm) | Triangles | B-rep | Editable | Params moving / all | Feature area | "
          "Deviation (mm) | Within tol | Occupancy IoU | GMS | Gates | Time (s) | Method | With learned engine |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        a, w = r["without"], r["with"]
        wt = "not installed" if w is None else f"B-rep {_pct(w['brep_pct'])}, editable {_pct(w['editable_pct'])}"
        L.append(f"| {r['class']} | {r['part']} | {r['tol']:g} | {_f(a['triangles'])} | {_pct(a['brep_pct'])} | "
                 f"{_pct(a['editable_pct'])} | {_f(a['movable'])} / {_f(a['params'])} | {_pct(a['feature_area_pct'])} | "
                 f"{_f(a['hausdorff_mm'])} | {'yes' if a['within'] else 'no'} | {_f(a.get('occupancy_iou'))} | "
                 f"{_f(a.get('gms'))} | {_gate_cell(a)} | {_f(a['seconds'])} | "
                 f"{a['method'] or (str(a['error'])[:90] if a.get('error') else '–')} | {wt} |")
    if before:
        L += ["", "Before this run (the previous version of this file, same parts):", "",
              "| Part | B-rep before | B-rep now | Editable before | Editable now | Time before (s) | Time now (s) |",
              "|---|---|---|---|---|---|---|"]
        for r in rows:
            b, a = before.get(r["part"]), r["without"]
            if b is None:
                L.append(f"| {r['part']} | new | {_pct(a['brep_pct'])} | new | {_pct(a['editable_pct'])} | – | "
                         f"{_f(a['seconds'])} |")
            else:
                L.append(f"| {r['part']} | {b.get('B-rep', '–')} | {_pct(a['brep_pct'])} | {b.get('Editable', '–')} | "
                         f"{_pct(a['editable_pct'])} | {b.get('Time (s)', '–')} | {_f(a['seconds'])} |")
    by = {}
    for r in rows:
        by.setdefault(r["class"], []).append(r["without"])
    L += ["", "Per class, without the learned engine (median over its parts):", "",
          "| Class | Parts | B-rep | Editable |", "|---|---|---|---|"]
    for c, xs in by.items():
        L.append(f"| {c} | {len(xs)} | {statistics.median([x['brep_pct'] or 0.0 for x in xs]):g}% | "
                 f"{statistics.median([x['editable_pct'] or 0.0 for x in xs]):g}% |")
    L += ["", "Largest gap between progress events: " +
          ", ".join(f"{r['part']} {r['without']['max_progress_gap_s']:g} s" for r in rows) + ".", ""]
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
