"""Benchmarks in public: Form Studio's own verification suites and Parametric CAD Bench v3, run and published.

    form bench list                                   the suites and the external benchmark, as JSON
    form bench run [--suite S ...] [--source DIR] [--save]
                                                      run suites (each in its own process) on a source tree
    form bench publish                                docs/BENCHMARKS.md and site/benchmarks.html from the saved results
    form bench cadbench --tasks DIR --agent claude-code --model M [--task ID ...] [--limit N]
                                                      Parametric CAD Bench v3 through Form Studio (form/bench/cadbench.py)
    form bench cadbench --download DIR                fetch the pinned task set with Harbor
    form bench oracle --tasks DIR [--task ID ...]     score each task's own reference: the scorer parity check

The saved results are docs/benchmarks/suites.json and docs/benchmarks/cadbench.json. Every entry records the commit,
the machine and the date it was measured on; publish only formats them, so nothing on the page is typed by hand.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "benchmarks"
SUITES_JSON = DATA / "suites.json"
CADBENCH_JSON = DATA / "cadbench.json"
RUNNER = Path(__file__).with_name("suites.py")

SUITES = [
    {"id": "strength", "title": "Strength studies against textbook and NAFEMS cases", "wave": "D",
     "module": "form.fea.verify", "needs": "the FEA engine's Python ($FORM_FEA_PYTHON)"},
    {"id": "calculators", "title": "Calculators against published worked examples", "wave": "X",
     "module": "form.calc.verify", "needs": "the CAD kernel for the solids"},
    {"id": "iso286", "title": "ISO 286 limits against the ISO 286-2 tables", "wave": "F",
     "module": "form.iso286", "needs": ""},
    {"id": "dfm", "title": "Manufacturability rules at their thresholds", "wave": "E",
     "module": "form.dfm.rules", "needs": ""},
    {"id": "recon", "title": "Mesh to editable CAD: deviation against tolerance", "wave": "recon",
     "module": "scripts/recon_bench.py", "needs": "the CAD kernel; about 15 minutes"},
]
IDS = [s["id"] for s in SUITES]


def _git(root: Path, *args) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def machine() -> str:
    return f"{platform.machine()}, {platform.system()} {platform.release()}, {os.cpu_count()} cores"


def run_suite(sid: str, source: Path | None = None, python: str | None = None, commit: str = "", branch: str = "") -> dict:
    """One suite in its own process, with `source` (default: this checkout) first on PYTHONPATH."""
    import tempfile
    src = Path(source or ROOT).resolve()
    with tempfile.TemporaryDirectory(prefix="form-bench-data-") as tmp:     # never the person's designs or settings
        (Path(tmp) / "studio.toml").write_text(f'[data]\ndir = "{Path(tmp).as_posix()}/data"\n', encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(src), os.environ.get("PYTHONPATH", "")) if p),
               "FORM_NO_UPDATE_CHECK": "1", "FORM_DATA": str(Path(tmp) / "data"), "FORM_CONFIG": str(Path(tmp) / "studio.toml")}
        r = subprocess.run([python or sys.executable, str(RUNNER), sid], capture_output=True, text=True, env=env, cwd=str(src))
    try:
        rep = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        rep = {"suite": sid, "available": True, "crashed": True, "rows": [
            {"group": sid, "item": "suite run", "expected": "completes", "got": "crashed", "unit": "", "tolerance": "",
             "error": None, "pass": False, "source": "", "note": (r.stderr or "")[-400:]}]}
    rows = rep.get("rows", [])
    rep.update({"passed": sum(1 for x in rows if x["pass"]), "failed": sum(1 for x in rows if not x["pass"]),
                "commit": commit or _git(src, "rev-parse", "HEAD") or "unknown",
                "branch": branch or _git(src, "rev-parse", "--abbrev-ref", "HEAD") or "",
                "dirty": bool(_git(src, "status", "--porcelain", "--", "form", "scripts")) if not commit else False,
                "machine": machine(), "date": _dt.date.today().isoformat(),
                "title": next(s["title"] for s in SUITES if s["id"] == sid)})
    return rep


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def scrub(obj):
    """Results go into the public repository: no home folder, temporary folder or user name in them."""
    import re
    import tempfile
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k != "out"}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        for real, shown in ((str(ROOT), "<checkout>"), (os.path.realpath(tempfile.gettempdir()), "<tmp>"),
                            (tempfile.gettempdir(), "<tmp>"), ("/private/tmp", "<tmp>"), (str(Path.home()), "~")):
            obj = obj.replace(real, shown)
        user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        if len(user) >= 3:
            obj = re.sub(rf"\b{re.escape(user)}\b", "<user>", obj)
    return obj


def save_suites(results: list[dict]) -> dict:
    """Merge into docs/benchmarks/suites.json. A suite that ran replaces its entry; a suite whose code is not in the
    measured tree keeps the entry measured elsewhere (that entry names its own commit and branch)."""
    data = load(SUITES_JSON, {"suites": {}})
    for r in scrub(results):
        old = data["suites"].get(r["suite"])
        if r.get("available") or not old:
            data["suites"][r["suite"]] = r
        else:
            old["absent_on"] = {"commit": r["commit"], "branch": r.get("branch", ""), "date": r["date"],
                                "reason": r.get("reason", "")}
    DATA.mkdir(parents=True, exist_ok=True)
    SUITES_JSON.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    return data


def save_cadbench(res: dict) -> dict:
    """Keep one entry per agent, model and effort: the newest run replaces the one before it."""
    data = load(CADBENCH_JSON, {"runs": []})
    res = scrub(res)
    key =(res["agent"], res["model"], res.get("effort", "default"))
    data["runs"] = [r for r in data["runs"] if (r["agent"], r["model"], r.get("effort", "default")) != key] + [res]
    DATA.mkdir(parents=True, exist_ok=True)
    CADBENCH_JSON.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    return data


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, default=str))


def main_cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="form bench", description="Benchmarks: own suites and Parametric CAD Bench v3")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the suites and the external benchmark")
    r = sub.add_parser("run", help="run suites on a source tree")
    r.add_argument("--suite", action="append", choices=IDS, help="one suite (repeat); default all")
    r.add_argument("--skip", action="append", choices=IDS, default=[], help="leave a suite out")
    r.add_argument("--source", default=None, help="the source tree to measure (default: this checkout)")
    r.add_argument("--commit", default="", help="the commit of --source when it is not a git checkout")
    r.add_argument("--branch", default="", help="the branch of --source when it is not a git checkout")
    r.add_argument("--python", default=None, help="the Python that runs the suites (default: this one)")
    r.add_argument("--save", action="store_true", help="merge into docs/benchmarks/suites.json")
    sub.add_parser("publish", help="write docs/BENCHMARKS.md and site/benchmarks.html")
    c = sub.add_parser("cadbench", help="Parametric CAD Bench v3 through Form Studio")
    c.add_argument("--tasks", default=None, help="a `harbor download` export of the task set")
    c.add_argument("--download", default=None, help="fetch the pinned task set into this folder and stop")
    c.add_argument("--agent", default="claude-code", help="claude-code or standin")
    c.add_argument("--model", default="", help="the model id the agent's CLI takes")
    c.add_argument("--effort", default="", help="reasoning effort, when the CLI takes one")
    c.add_argument("--task", action="append", help="one task id (repeat); default all 100")
    c.add_argument("--limit", type=int, default=None)
    c.add_argument("--budget-usd", type=float, default=10.0, help="spending cap per task (the agent CLI's own cap)")
    c.add_argument("--timeout", type=float, default=None, help="seconds per task (default: the task's own, 9000)")
    c.add_argument("--out", default=None, help="where the trials go (default: a temporary folder)")
    c.add_argument("--no-publish", action="store_true", help="do not save into docs/benchmarks/ or publish")
    o = sub.add_parser("oracle", help="score each task's reference answer (the scorer parity check)")
    o.add_argument("--tasks", required=True)
    o.add_argument("--task", action="append")
    o.add_argument("--out", default=None)
    o.add_argument("--no-save", action="store_true", help="do not record the parity check in docs/benchmarks/")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        from . import cadbench
        _print({"suites": SUITES, "saved": {k: {"passed": v.get("passed"), "failed": v.get("failed"),
                                                 "commit": v.get("commit"), "date": v.get("date"),
                                                 "available": v.get("available")}
                                             for k, v in load(SUITES_JSON, {"suites": {}})["suites"].items()},
                "external": [{"id": "cadbench", "title": "Parametric CAD Bench v3", "dataset": f"{cadbench.DATASET}@{cadbench.TAG}",
                              "digest": cadbench.DIGEST, "sources": cadbench.SOURCES, "agents": ["claude-code", "standin"],
                              "runs": [{"agent": x["agent"], "model": x["model"], "date": x["date"],
                                        "mean_reward": x["summary"]["mean_reward"], "tasks": x["summary"]["tasks"],
                                        "standin": x.get("standin")} for x in load(CADBENCH_JSON, {"runs": []})["runs"]]}]})
        return 0
    if a.cmd == "run":
        ids = [s for s in (a.suite or IDS) if s not in a.skip]
        results = []
        for sid in ids:
            print(f"running {sid} ...", file=sys.stderr, flush=True)
            results.append(run_suite(sid, Path(a.source) if a.source else None, a.python, a.commit, a.branch))
        if a.save:
            save_suites(results)
        _print({"suites": [{k: v for k, v in r.items() if k != "rows"} | {"failures": [x for x in r["rows"] if not x["pass"]]}
                           for r in results], "saved": str(SUITES_JSON) if a.save else None})
        return 0 if all(r.get("failed", 0) == 0 for r in results) else 1
    if a.cmd == "publish":
        from .publish import publish
        _print(publish())
        return 0
    if a.cmd == "oracle":
        from . import cadbench
        import tempfile
        tasks = cadbench.find_tasks(Path(a.tasks))
        if a.task:
            tasks = [t for t in tasks if t.name in a.task or t.name.removeprefix("freecad-") in a.task]
        out = Path(a.out or tempfile.mkdtemp(prefix="form-cadbench-oracle-"))
        rows = []
        for t in tasks:
            s = cadbench.oracle(t, out)
            rows.append({"task": s["task"], "mode": s["mode"], "reward": s.get("reward"), "error": s.get("error")})
            print(f"{t.name}: {s.get('reward')}", file=sys.stderr, flush=True)
        rep = {"oracle": rows, "all_one": all(r["reward"] == 1.0 for r in rows), "out": str(out)}
        if not a.no_save:
            data = load(CADBENCH_JSON, {"runs": []})
            data["parity"] = {"what": "each task's held-back reference scored as the answer, through the harness's "
                                      "scoring (the task's own verifier image and test.sh)",
                              "rows": rows, "all_one": rep["all_one"], "date": _dt.date.today().isoformat(),
                              "machine": machine(), "commit": _git(ROOT, "rev-parse", "HEAD")}
            data = scrub(data)
            DATA.mkdir(parents=True, exist_ok=True)
            CADBENCH_JSON.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
        _print(rep)
        return 0 if all(r["reward"] == 1.0 for r in rows) else 1
    if a.cmd == "cadbench":
        from . import cadbench
        try:
            if a.download:
                _print(cadbench.download(Path(a.download)))
                return 0
            if not a.tasks:
                ap.error("--tasks DIR (or --download DIR first)")
            res = cadbench.run(Path(a.tasks), a.agent, a.model, a.effort, a.task, a.limit,
                               Path(a.out) if a.out else None, a.budget_usd, a.timeout,
                               progress=lambda i, n, row: print(f"[{i}/{n}] {row['id']} {row['mode']}: reward "
                                                                f"{row['reward']}", file=sys.stderr, flush=True))
        except cadbench.BenchError as e:
            _print({"error": str(e)})
            return 2
        if not a.no_publish:
            save_cadbench(res)
            from .publish import publish
            res["published"] = publish()
        _print({k: v for k, v in res.items() if k != "trials"})
        return 0
    return 2
