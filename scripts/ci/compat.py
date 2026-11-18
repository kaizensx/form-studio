"""The nightly compatibility matrix: every recipe sliced by every slicer CI can install.

    python scripts/ci/compat.py run --kind orca --python .venv/bin/python --out OUT     # one slicer, every recipe
    python scripts/ci/compat.py merge --in DIR --out SITE_DATA [--history history.json] # all slicers, one matrix

`run` builds each built-in recipe and each community recipe at its defaults with build_recipe.py and slices it with
the slicer FORM_CONFIG selects, then writes OUT/compat-<kind>.json:

    {"kind", "slicer": {"name", "version"}, "runner", "results": {"<recipe>": {"title", "builtin", "state": "ok" |
     "slice-failed" | "build-failed" | "check-failed", "time_s", "filament_g", "layers", "supports", "seconds",
     "rollup", "error"}}}

`merge` writes latest.json (the site's /compat/ page), badge.json (a shields.io endpoint) and appends to history.json:

    latest.json  {"schema": 1, "generated", "commit", "run_url", "slicers": [{"kind", "name", "version"}],
                  "recipes": [{"id", "title", "builtin"}], "cells": {"<recipe>": {"<kind>": {...}}},
                  "totals": {"ok", "sliced", "cells"}}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_json, log, run_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def recipes(root: Path) -> list[tuple[str, str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pr_preview import builtin_ids
    out = [("builtin", rid) for rid in builtin_ids(root).values()]
    for d in sorted((root / "community" / "recipes").glob("*/")):
        if (d / "recipe.py").exists():
            out.append(("community", d.name))
    return out


def cmd_run(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results, slicer_info = {}, {}
    only = set(a.only.split(",")) if a.only else None
    for kind, rid in recipes(ROOT):
        if only and rid not in only:
            continue
        d = out / f"{kind}-{rid}"
        args = [a.python, str(ROOT / "scripts" / "ci" / "build_recipe.py"), "--out", str(d), "--slice"]
        args += ["--builtin", rid] if kind == "builtin" else ["--community", str(ROOT / "community" / "recipes" / rid)]
        env = {**os.environ, "FORM_DATA": tempfile.mkdtemp(prefix=f"compat-{rid}-")}
        log(f"{a.kind}: {rid}")
        try:
            subprocess.run(args, env=env, timeout=900, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            pass
        cell = {"title": rid, "builtin": kind == "builtin", "state": "build-failed"}
        try:
            r = load_json(d / "result.json")
        except (ValueError, OSError):
            results[rid] = {**cell, "error": "no result (timeout or crash)"}
            continue
        sres = ((r.get("environment") or {}).get("slicer")) or {}
        if sres.get("available"):
            slicer_info = {"name": sres.get("name"), "version": sres.get("version")}
        cell["title"] = (r.get("recipe") or {}).get("title") or rid
        s0 = (r.get("sets") or [{}])[0]
        sl = s0.get("slice") or {}
        cell["seconds"] = s0.get("seconds")
        cell["rollup"] = s0.get("rollup")
        if s0.get("state") != "built":
            cell["error"] = ((s0.get("error") or {}).get("message") or "")[:300]
        elif sl.get("ok"):
            cell.update({k: sl.get(k) for k in ("time_s", "filament_g", "layers", "supports")})
            cell["state"] = "ok" if not (s0.get("rollup") or {}).get("FAIL") else "check-failed"
            if sl.get("slicer_version"):
                slicer_info["version"] = sl["slicer_version"]
            if sl.get("slicer"):
                slicer_info["name"] = sl["slicer"]
        else:
            cell["state"] = "slice-failed"
            cell["error"] = (((sl.get("error") or {}).get("message")) or "not sliced")[:300]
        results[rid] = cell
    doc = {"kind": a.kind, "slicer": {"name": a.name or slicer_info.get("name") or a.kind,
                                      "version": slicer_info.get("version") or a.version},
           "runner": a.runner, "results": results}
    (out / f"compat-{a.kind}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    ok = sum(1 for c in results.values() if c["state"] == "ok")
    print(f"{a.kind}: {ok}/{len(results)} sliced cleanly")
    return 0


def badge(ok: int, cells: int) -> dict:
    share = ok / cells if cells else 0
    color = "brightgreen" if share == 1 else ("green" if share >= 0.9 else ("yellow" if share >= 0.7 else "red"))
    return {"schemaVersion": 1, "label": "slicer matrix", "message": f"{ok}/{cells} sliced" if cells else "no data",
            "color": color if cells else "lightgrey"}


def cmd_merge(a) -> int:
    docs = []
    for f in sorted(Path(a.inp).rglob("compat-*.json")):
        try:
            docs.append(load_json(f))
        except (ValueError, OSError) as e:
            log(f"skip {f}: {e}")
    slicers, cells, recipes_ = [], {}, {}
    for d in sorted(docs, key=lambda d: str(d.get("slicer", {}).get("name", d.get("kind")))):
        kind = str(d.get("kind"))
        slicers.append({"kind": kind, **{k: d.get("slicer", {}).get(k) for k in ("name", "version")}, "runner": d.get("runner")})
        for rid, c in (d.get("results") or {}).items():
            recipes_.setdefault(rid, {"id": rid, "title": c.get("title") or rid, "builtin": bool(c.get("builtin"))})
            cells.setdefault(rid, {})[kind] = c
    order = sorted(recipes_.values(), key=lambda r: (not r["builtin"], r["title"].lower()))
    n_ok = sum(1 for r in cells.values() for c in r.values() if c.get("state") == "ok")
    n_sliced = sum(1 for r in cells.values() for c in r.values() if c.get("state") in ("ok", "check-failed"))
    n = sum(len(r) for r in cells.values())
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    latest = {"schema": 1, "generated": now, "commit": os.environ.get("GITHUB_SHA"), "run_url": run_url(),
              "slicers": slicers, "recipes": order, "cells": cells, "totals": {"ok": n_ok, "sliced": n_sliced, "cells": n}}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(latest, indent=1), encoding="utf-8")
    (out / "badge.json").write_text(json.dumps(badge(n_sliced, n)), encoding="utf-8")
    hist = []
    if a.history and Path(a.history).exists():
        try:
            hist = load_json(a.history, kind=list)
        except ValueError:
            hist = []
    hist = [h for h in hist if isinstance(h, dict)][-364:]
    hist.append({"date": now, "ok": n_ok, "sliced": n_sliced, "cells": n, "slicers": len(slicers), "recipes": len(order),
                 "commit": (os.environ.get("GITHUB_SHA") or "")[:10]})
    (out / "history.json").write_text(json.dumps(hist, indent=0), encoding="utf-8")
    print(f"matrix: {n_sliced}/{n} sliced, {n_ok} with every check passing, across {len(slicers)} slicers and {len(order)} recipes")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--kind", required=True)
    r.add_argument("--name", default="")
    r.add_argument("--version", default="")
    r.add_argument("--runner", default=os.environ.get("ImageOS", "local"))
    r.add_argument("--python", default=sys.executable)
    r.add_argument("--only", default="", help="comma-separated recipe ids (tests)")
    r.add_argument("--out", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--in", dest="inp", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--history")
    a = ap.parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_merge(a)


if __name__ == "__main__":
    sys.exit(main())
