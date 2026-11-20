"""Build every design on the design bench (exemplars and reference solutions) through the kernel workers, first on
one worker (one build after another, as Form Studio did before the pool) and then on the pool, and report wall time
and how many built.

    .venv/bin/python scripts/bench_timing.py                  # all bench designs, pool of the default size
    .venv/bin/python scripts/bench_timing.py --workers 4 --all-exemplars --json out.json

Each design is built once per run from a cold cache (a fresh set of workers), at the same tolerance create_design
uses (0.1 mm). Worker start-up is timed separately (warm), so the build numbers compare builds, not imports.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def designs(all_exemplars: bool) -> list[tuple[str, str]]:
    from form import exemplars
    bench = json.loads((ROOT / "tests" / "design_bench" / "briefs.json").read_text(encoding="utf-8"))["briefs"]
    out, seen = [], set()
    for b in bench:
        if b.get("exemplar") and b["exemplar"] not in seen:
            seen.add(b["exemplar"])
            out.append((b["exemplar"], exemplars.get(b["exemplar"])["source"]))
        elif b.get("solution"):
            f = ROOT / "tests" / "design_bench" / "solutions" / f"{b['solution']}.py"
            out.append((b["solution"], f.read_text(encoding="utf-8")))
    if all_exemplars:
        for e in exemplars.catalogue():
            if e["name"] not in seen:
                seen.add(e["name"])
                out.append((e["name"], exemplars.get(e["name"])["source"]))
    return out


def run(size: int, items: list[tuple[str, str]], store: Path) -> dict:
    from form.recipes import store_source
    from form.worker import KernelFailure, KernelPool
    calls = []
    for name, src in items:
        rid = store_source(store, src)
        calls.append({"key": f"bt-{size}-{name}", "recipe_id": rid, "values": {}, "tol": 0.1, "sweep": False})
    pool = KernelPool(size=size)
    try:
        t = time.time()
        pool.warm()
        warm = time.time() - t
        t = time.time()
        outs = pool.map("candidate", [dict(c) for c in calls], timeout=900)
        wall = time.time() - t
    finally:
        pool.stop()
    rows = []
    for (name, _), o in zip(items, outs):
        if isinstance(o, KernelFailure):
            rows.append({"name": name, "ok": False, "error": o.info.get("message", "")[:200]})
        else:
            rows.append({"name": name, "ok": bool(o["valid"] and o["solids"] == o["declared"]), "build_s": o["build_s"],
                         "seconds": o["seconds"]})
    return {"workers": size, "warm_s": round(warm, 2), "wall_s": round(wall, 2),
            "built": sum(r["ok"] for r in rows), "designs": len(rows),
            "sum_of_builds_s": round(sum(r.get("seconds", 0) for r in rows), 2), "rows": rows}


def main(argv=None) -> int:
    from form.worker import default_workers
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=default_workers({}))
    ap.add_argument("--all-exemplars", action="store_true")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    store = Path(tempfile.mkdtemp(prefix="form-bench-sources-"))
    os.environ["FORM_SOURCES"] = str(store)                    # the workers resolve src: ids from here
    items = designs(a.all_exemplars)
    serial = run(1, items, store)
    pool = run(a.workers, items, store)
    out = {"designs": len(items), "serial": {k: v for k, v in serial.items() if k != "rows"},
           "pool": {k: v for k, v in pool.items() if k != "rows"},
           "speedup": round(serial["wall_s"] / max(pool["wall_s"], 1e-6), 2),
           "rows": {"serial": serial["rows"], "pool": pool["rows"]}}
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    for r in pool["rows"]:
        if not r["ok"]:
            print(f"  {r['name']}: {r.get('error', 'invalid or wrong solid count')}")
    if a.json:
        a.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
