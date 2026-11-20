"""Mesh to editable CAD, measured: editable share, deviation and time per part, before and after the program route.

    .venv/bin/python scripts/recon_bench.py                       # the synthetic fixtures -> docs/RECON_BENCH.md
    .venv/bin/python scripts/recon_bench.py --mesh a.stl b.stl --out /tmp/bench.md   # your own meshes, elsewhere

For each part the pipeline runs twice in this process: with the program route (sketches and extrusions read off the
mesh, form/recon/program.py) and without it (the Layer 1 surfaces and feature tree only, what came before). For a
program recipe every Param is swept over its range: does it change the solid, and does the part still build. Every
number is computed by comparing with the mesh. Meshes passed with --mesh are never written into docs/ unless --out
says so: keep private parts out of the repository.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

FIXTURES = {"box_with_holes": 0.02, "stepped_bracket": 0.02, "filleted_bracket": 0.02, "turned_part": 0.02,
            "flanged_shaft": 0.02, "gear": 0.05, "organic_blob": 0.02, "wallet_plate": 0.02}


def run(path: Path, tol: float, program_route: bool, out: Path, budget: float) -> dict:
    from form.recon import pipeline
    keep = pipeline._program
    if not program_route:
        pipeline._program = lambda *a, **k: {"report": {"method": "sketches and extrusions", "error": "off for the bench"}}
    gaps, last = [], [time.perf_counter()]

    def prog(_d):
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
    t = time.perf_counter()
    try:
        rep = pipeline.reconstruct(path, out, path.stem, tol, 2, budget_s=budget, progress=prog)
    finally:
        pipeline._program = keep
    gaps.append(time.perf_counter() - last[0])
    res = rep.get("result") or {}
    L2 = rep.get("layers", {}).get("2", {}) or {}
    return {"seconds": round(time.perf_counter() - t, 1), "layer": res.get("layer"), "method": L2.get("method"),
            "editable_pct": res.get("editable_pct"), "hausdorff_mm": res.get("hausdorff_mm"),
            "within": res.get("within_tolerance"), "params": res.get("params") or (len(L2["params"]) if isinstance(L2.get("params"), list) else L2.get("params")),
            "triangles": rep.get("input", {}).get("triangles") or rep.get("input", {}).get("weld", {}).get("triangles"),
            "max_progress_gap_s": round(max(gaps), 2), "error": rep.get("error") or L2.get("error"),
            "recipe": (out / res["recipe"]) if res.get("recipe") else None,
            "refs": {r: str(out / r) for r in res.get("recipe_references") or []}}


def swept(r: dict, budget: float) -> dict | None:
    if not r.get("recipe") or r.get("method") != "sketches and extrusions":
        return None
    from form.recon import program
    rows = program.sweep(Path(r["recipe"]).read_text(), r["refs"], deadline=time.perf_counter() + budget)
    if not rows:
        return None
    good = [x for x in rows if x["changes"] and x["rebuilds_pct"] >= 80]
    return {"params": len(rows), "change_and_rebuild_80": len(good),
            "changes": sum(1 for x in rows if x["changes"]),
            "rebuild_median_pct": sorted(x["rebuilds_pct"] for x in rows)[len(rows) // 2]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", nargs="*", default=None, help="fixture names (default: all)")
    ap.add_argument("--mesh", nargs="*", default=[], help="extra meshes (kept out of docs/ unless --out says so)")
    ap.add_argument("--tol", type=float, default=None, help="tolerance for --mesh parts (default 0.05)")
    ap.add_argument("--out", default=None, help="Markdown report (default docs/RECON_BENCH.md for fixtures only)")
    ap.add_argument("--budget", type=float, default=240.0)
    ap.add_argument("--sweep-s", type=float, default=60.0, help="time for the Param sweep per part")
    ap.add_argument("--no-before", action="store_true", help="skip the run without the program route")
    a = ap.parse_args(argv)
    import recon_fixtures as fx
    work = Path(tempfile.mkdtemp(prefix="recon-bench-"))
    parts = []
    names = list(FIXTURES) if a.fixtures is None else a.fixtures
    for n in names:
        if n not in fx.FIXTURES:
            print(f"skip {n}: no such fixture")
            continue
        try:
            stl = fx.export(n, work)[0]
        except Exception as e:                          # noqa: BLE001  (py_gearworks missing, ...)
            print(f"skip {n}: {type(e).__name__}: {e}")
            continue
        parts.append((n, stl, FIXTURES.get(n, 0.02)))
    for m in a.mesh:
        parts.append((Path(m).stem, Path(m), a.tol or 0.05))
    if a.out is None and a.mesh:
        ap.error("pass --out for your own meshes (docs/RECON_BENCH.md is for the synthetic fixtures)")
    out_md = Path(a.out) if a.out else ROOT / "docs" / "RECON_BENCH.md"
    rows = []
    for n, p, tol in parts:
        print(f"{n} ({tol:g} mm) ...", flush=True)
        after = run(p, tol, True, work / f"{n}-after", a.budget)
        sw = swept(after, a.sweep_s)
        before = None if a.no_before else run(p, tol, False, work / f"{n}-before", a.budget)
        rows.append({"part": n, "tol": tol, "after": after, "sweep": sw, "before": before})
        print(json.dumps({k: v for k, v in after.items() if k not in ("recipe", "refs")}, default=str), flush=True)
    write(out_md, rows)
    print(f"wrote {out_md}")


def _f(x, nd=4):
    return "–" if x is None else (f"{x:.{nd}g}" if isinstance(x, float) else str(x))


def write(path: Path, rows: list):
    import statistics
    eds = [r["after"]["editable_pct"] or 0.0 for r in rows]
    L = ["# Mesh to editable CAD: benchmark", "",
         "Written by `scripts/recon_bench.py` from real runs of `form/recon` on the synthetic fixtures in "
         "`tests/recon_fixtures.py` (build123d parts exported as STL). **Editable** is the share of the result's surface "
         "that its Params make; **deviation** is the two-sided Hausdorff distance to the mesh. *Before* is the same "
         "pipeline without the program route (Layer 1 surfaces and the feature tree only). Computed, not assumed.", "",
         f"Median editable after: **{statistics.median(eds) if eds else 0:g}%** over {len(rows)} parts.", "",
         "| Part | Tol (mm) | Triangles | Before: editable, deviation, time | After: editable | After: deviation (mm) | "
         "Within tol | After: time (s) | Method | Params | Params that change the part and rebuild over 80% of their range |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        a, b, s = r["after"], r["before"], r["sweep"]
        bt = "–" if b is None else f"{_f(b['editable_pct'])}%, {_f(b['hausdorff_mm'])} mm, {_f(b['seconds'])} s"
        sw = "–" if not s else f"{s['change_and_rebuild_80']} of {s['params']}"
        L.append(f"| {r['part']} | {r['tol']:g} | {_f(a['triangles'])} | {bt} | {_f(a['editable_pct'])}% | "
                 f"{_f(a['hausdorff_mm'])} | {'yes' if a['within'] else 'no'} | {_f(a['seconds'])} | {a['method'] or '–'} | "
                 f"{_f(a['params'])} | {sw} |")
    L += ["", "Largest gap between progress events, after: " +
          ", ".join(f"{r['part']} {r['after']['max_progress_gap_s']:g} s" for r in rows) + ".", ""]
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
