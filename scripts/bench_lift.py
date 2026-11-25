"""Measure the canonical lift (form/canon.py) on a folder of design sources.

    .venv/bin/python scripts/bench_lift.py SOURCES_DIR [--json out.json] [--workers 4] [--timeout 240]

Every plain Recipe source (*.py that is not already a FeatureDesign) is built twice through the kernel workers, as it
is and lifted, with its default values at the tolerance create_design uses (0.1 mm). The lift "keeps" a design when
both build and volume (1e-6 relative), face count and bounding box (1e-4 mm) are the same. Reported per mode
(features: build() split into feature methods; skeleton: build() kept as one feature). A source whose original does
not build here (a refused attempt the store kept, or a part it reads is not given with --refs) is counted apart:
there is nothing to compare. SOURCES_DIR is only read; the copies and checkpoints go to a temporary folder.
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


def same(a: dict, b: dict) -> dict:
    va, vb = a["volume_mm3"], b["volume_mm3"]
    box = max(abs(x - y) for p, q in zip(a["bbox"], b["bbox"]) for x, y in zip(p, q))
    return {"volume": abs(va - vb) <= 1e-6 * max(1.0, abs(va)), "faces": a["faces"] == b["faces"], "bbox": box <= 1e-4,
            "dvol": vb - va, "dfaces": b["faces"] - a["faces"], "dbox": box}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources")
    ap.add_argument("--json")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refs", help="a folder of <project>/references/<file>: imported parts the sources read")
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="form-lift-"))
    store = tmp / ".sources"
    os.environ["FORM_DATA"] = str(tmp)
    os.environ["FORM_SOURCES"] = str(store)
    from form import canon, featureprog
    from form.recipes import store_source
    from form.worker import KernelFailure, KernelPool
    rows, calls = [], []
    files = sorted(Path(a.sources).glob("*.py"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        if featureprog.is_feature_design(src):
            continue
        r = canon.lift(src)
        row = {"file": f.name, "mode": r["mode"], "why": r["why"], "features": len(r["features"]),
               "lines": [len(src.splitlines()), len(r["source"].splitlines())]}
        rows.append(row)
        if r["mode"] in ("features", "skeleton"):
            calls.append((row, "orig", store_source(store, src)))
            calls.append((row, "lift", store_source(store, r["source"])))
    if a.limit:
        keep = {id(r) for r in rows[:a.limit]}
        calls = [c for c in calls if id(c[0]) in keep]
        rows = rows[:a.limit]
    refs = {}
    if a.refs:                                           # by file name; the first project that has a name gives it
        for f in sorted(Path(a.refs).glob("*/references/*")):
            if f.is_file() and not f.name.endswith(".json"):
                refs.setdefault(f.name, str(f))
    pool = KernelPool(size=a.workers)
    t0 = time.time()
    try:
        outs = pool.map("summary", [{"key": f"bl-{k}-{rid}", "recipe_id": rid, "values": {}, "tol": 0.1,
                                     **({"_refs": refs} if refs else {})}
                                    for _r, k, rid in calls], timeout=a.timeout)
    finally:
        pool.stop()
    for (row, k, _rid), o in zip(calls, outs):
        if isinstance(o, KernelFailure) or isinstance(o, Exception) or not isinstance(o, dict) or "volume_mm3" not in o:
            info = getattr(o, "info", None) or {}
            row[k] = {"ok": False, "error": str(info.get("message") or o)[:300]}
        else:
            row[k] = {"ok": True, "volume_mm3": o["volume_mm3"], "faces": o["faces"], "bbox": o["bbox"],
                      "build_s": o["timing"]["build_s"], "skipped": [x["feature"] for x in o.get("skipped", [])]}
    tot = {"plain": len(rows), "wall_s": round(time.time() - t0, 1)}
    for mode in ("features", "skeleton"):
        rs = [r for r in rows if r["mode"] == mode]
        base = [r for r in rs if r.get("orig", {}).get("ok")]
        kept = 0
        for r in base:
            if r["lift"]["ok"] and not r["lift"]["skipped"]:
                r["same"] = same(r["orig"], r["lift"])
                r["kept"] = all(r["same"][k] for k in ("volume", "faces", "bbox"))
            else:
                r["kept"] = False
            kept += bool(r["kept"])
        tot[mode] = {"sources": len(rs), "original_builds": len(base), "kept": kept}
    tot["none"] = len([r for r in rows if r["mode"] == "none"])
    builds = tot["features"]["original_builds"] + tot["skeleton"]["original_builds"]
    tot["kept_of_buildable"] = [tot["features"]["kept"] + tot["skeleton"]["kept"], builds]
    tot["kept_of_plain"] = [tot["features"]["kept"] + tot["skeleton"]["kept"], len(rows)]
    tot["features_kept_of_plain"] = [tot["features"]["kept"], len(rows)]
    print(json.dumps(tot, indent=1))
    for r in rows:
        if r["mode"] != "none" and r.get("orig", {}).get("ok") and not r.get("kept"):
            print("NOT KEPT", r["file"], r["mode"], r["lift"].get("error") or r["lift"].get("skipped") or r.get("same"))
    if a.json:
        Path(a.json).write_text(json.dumps({"totals": tot, "rows": rows}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
