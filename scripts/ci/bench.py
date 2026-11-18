"""Benchmarks: build, check and slice time per recipe, the whole pipeline, and how long the app takes to start.

    python scripts/ci/bench.py run --out bench.json [--app-cmd "xvfb-run -a"] [--skip-app] [--only dock,hook]
    python scripts/ci/bench.py append --entry bench.json --history history.json [--keep 400]

`run` uses the Form Studio installed in this Python. Each recipe is created at its defaults in a fresh projects folder
and run through the whole pipeline once (solid, STEP and STL, checks, slice when a slicer is configured); the times are
the pipeline's own step timings. App start is the wall time of `python -m form.app --check --wait 0` (interface loaded
and the CAD kernel answering), cold once and then the median of three warm starts.

bench.json:
    {"schema": 1, "date", "commit", "subject", "runner", "form", "slicer",
     "app": {"cold_s", "warm_s"}, "recipes": {"<id>": {"load_s", "geometry_s", "exports_s", "checks_s", "slice_s",
     "pipeline_s"}}, "totals": {"pipeline_s", "geometry_s", "checks_s", "slice_s"}}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_json, log  # noqa: E402


def recipe_times(only: set | None) -> tuple[dict, dict]:
    os.environ["FORM_DATA"] = tempfile.mkdtemp(prefix="bench-")
    from form import config, slicer
    from form.studio import Studio
    st = Studio(config.load())
    out = {}
    try:
        st.kernel_id()                                  # start the kernel outside the timings
        s = st.slicer_info()
        sl = {k: v for k, v in slicer.public(s).items() if k in ("name", "version", "kind", "available")} if s else {}
        for rid, recipe in st.recipes.items():
            if (only and rid not in only) or rid.startswith(("src:", "scad:")):
                continue
            t0 = time.perf_counter()
            p = st.create(f"bench {rid}", rid)
            load = time.perf_counter() - t0
            t1 = time.perf_counter()
            job = st.run_sync(p["id"])
            total = time.perf_counter() - t1
            row = {"load_s": round(load, 3), "pipeline_s": round(total, 3), "state": job["state"]}
            for step in job["steps"]:
                if step.get("seconds") is not None:
                    row[f"{step['node']}_s"] = step["seconds"]
            out[rid] = row
            log(f"{rid}: {row}")
    finally:
        st.kernel.stop()
    return out, sl


def app_times(prefix: list[str]) -> dict:
    def once() -> float | None:
        env = {**os.environ, "FORM_DATA": tempfile.mkdtemp(prefix="bench-app-"), "FORM_NO_UPDATE_CHECK": "1",
               "FORM_CHECK_OUT": str(Path(tempfile.mkdtemp()) / "check.txt")}
        t0 = time.perf_counter()
        r = subprocess.run([*prefix, sys.executable, "-m", "form.app", "--check", "--wait", "0"], env=env,
                           capture_output=True, text=True, timeout=300)
        dt_ = time.perf_counter() - t0
        ok = Path(env["FORM_CHECK_OUT"]).exists() and "kernel: build123d" in Path(env["FORM_CHECK_OUT"]).read_text()
        if not ok:
            log("app check did not complete:", r.stdout[-800:], r.stderr[-1500:])
            return None
        return round(dt_, 3)
    cold = once()
    warm = [x for x in (once() for _ in range(3)) if x is not None]
    return {"cold_s": cold, "warm_s": round(statistics.median(warm), 3) if warm else None}


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""


def cmd_run(a) -> int:
    from form import __version__
    only = set(a.only.split(",")) if a.only else None
    recipes, sl = recipe_times(only)
    entry = {"schema": 1, "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "commit": os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD"),
             "subject": git("log", "-1", "--format=%s")[:120], "runner": os.environ.get("ImageOS", "local"),
             "form": __version__, "slicer": sl, "recipes": recipes}
    tot = {}
    for k in ("pipeline_s", "geometry_s", "checks_s", "slice_s"):
        vals = [r[k] for r in recipes.values() if isinstance(r.get(k), (int, float))]
        if vals:
            tot[k] = round(sum(vals), 3)
    entry["totals"] = tot
    entry["app"] = {} if a.skip_app else app_times(shlex.split(a.app_cmd))
    Path(a.out).write_text(json.dumps(entry, indent=1), encoding="utf-8")
    print(json.dumps({"totals": tot, "app": entry["app"]}, indent=1))
    return 0


def cmd_append(a) -> int:
    entry = load_json(a.entry)
    hist = []
    if Path(a.history).exists():
        try:
            hist = [h for h in load_json(a.history, kind=list) if isinstance(h, dict)]
        except ValueError:
            hist = []
    hist = [h for h in hist if h.get("commit") != entry.get("commit")]
    hist.append(entry)
    hist = hist[-a.keep:]
    Path(a.history).write_text(json.dumps(hist, separators=(",", ":")), encoding="utf-8")
    print(f"{len(hist)} entries")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--only", default="")
    r.add_argument("--app-cmd", default="", help="prefix for the app start, e.g. 'xvfb-run -a'")
    r.add_argument("--skip-app", action="store_true")
    p = sub.add_parser("append")
    p.add_argument("--entry", required=True)
    p.add_argument("--history", required=True)
    p.add_argument("--keep", type=int, default=400)
    a = ap.parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_append(a)


if __name__ == "__main__":
    sys.exit(main())
