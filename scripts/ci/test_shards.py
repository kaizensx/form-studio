"""Split the unit suite (tests/test_*.py) into shards of about equal run time and run one shard.

The run times come from tests/ci_timings.json (seconds per test module, measured on the CI runners); a module that is
not listed counts as DEFAULT seconds. A module the file lists by class ("test_recon.Layers") is split into its test
classes (found in its source, so none is left out), each a unit of its own. Shards are filled longest module first, each into the shard with the least time
so far, so the plan is stable for a given timing file and module list.

    python scripts/ci/test_shards.py plan --shards 4              # the plan, one line per shard
    python scripts/ci/test_shards.py run --shards 4 --index 1     # run shard 1 (1-based), verbose
    python scripts/ci/test_shards.py run --shards 4 --index 1 --times out.json   # and write each module's time

`run` arms a per-test watchdog (FORM_TEST_TIMEOUT seconds, default 900): a test or a class set-up that runs longer
has every thread's stack printed and the shard ends, so a hang names its test instead of using up the job's time.
Refresh the timing file from a CI run's `times-*` artifacts with `merge`:

    python scripts/ci/test_shards.py merge times-*/*.json > tests/ci_timings.json

The CI run's `coverage` artifact holds that merge as measured-timings.json.
"""
from __future__ import annotations

import argparse
import ast
import faulthandler
import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
TIMINGS = TESTS / "ci_timings.json"
DEFAULT = 10.0


def modules() -> list[str]:
    return sorted(p.stem for p in TESTS.glob("test_*.py"))


def classes(mod: str) -> list[str]:
    """The top-level classes of tests/<mod>.py that define test methods, in source order."""
    tree = ast.parse((TESTS / f"{mod}.py").read_text(encoding="utf-8"))
    return [n.name for n in tree.body if isinstance(n, ast.ClassDef) and any(
        isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name.startswith("test") for b in n.body)]


def units(mods: list[str], times: dict[str, float]) -> list[str]:
    """Modules, with each module that the timings list by class replaced by its classes."""
    out = []
    for m in mods:
        if any(k.startswith(m + ".") for k in times):
            out += [f"{m}.{c}" for c in classes(m)]
        else:
            out.append(m)
    return out


def timings(path: Path = TIMINGS) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {k: float(v) for k, v in data.get("modules", data).items() if not k.startswith("_")}


def plan(n: int, mods: list[str] | None = None, times: dict[str, float] | None = None) -> list[list[str]]:
    mods = modules() if mods is None else mods
    times = timings() if times is None else times
    shards: list[list[str]] = [[] for _ in range(n)]
    load = [0.0] * n
    for m in sorted(units(mods, times), key=lambda m: (-times.get(m, DEFAULT), m)):
        i = min(range(n), key=lambda k: (load[k], k))
        shards[i].append(m)
        load[i] += times.get(m, DEFAULT)
    return [sorted(s) for s in shards]


class _Watchdog(unittest.TextTestResult):
    limit = 900.0

    def startTest(self, test):
        faulthandler.dump_traceback_later(self.limit, exit=True)
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        faulthandler.dump_traceback_later(self.limit, exit=True)   # still armed for the next class's setUpClass


def run(mods: list[str], times_out: Path | None = None) -> bool:
    sys.path[:0] = [str(TESTS), str(ROOT)]       # as `unittest discover -s tests` does: modules import each other by name
    os.chdir(ROOT)
    _Watchdog.limit = float(os.environ.get("FORM_TEST_TIMEOUT", "900"))
    runner = unittest.TextTestRunner(verbosity=2, resultclass=_Watchdog, stream=sys.stderr)
    result = runner._makeResult()
    spent: dict[str, float] = {}
    loader = unittest.TestLoader()
    t_all = time.perf_counter()
    result.startTestRun()
    try:
        for m in mods:
            t0 = time.perf_counter()
            suite = loader.loadTestsFromName(m)
            suite.run(result)
            spent[m] = round(time.perf_counter() - t0, 1)
            print(f"[shard] {m}: {spent[m]:.1f} s", file=sys.stderr, flush=True)     # m: a module or module.Class
    finally:
        faulthandler.cancel_dump_traceback_later()
        result.stopTestRun()
    took = time.perf_counter() - t_all
    result.printErrors()
    print(result.separator2, file=sys.stderr)
    print(f"Ran {result.testsRun} tests in {took:.1f}s", file=sys.stderr)
    ok = result.wasSuccessful()
    extra = [f"failures={len(result.failures)}"] if result.failures else []
    extra += [f"errors={len(result.errors)}"] if result.errors else []
    extra += [f"skipped={len(result.skipped)}"] if result.skipped else []
    print(("OK" if ok else "FAILED") + (f" ({', '.join(extra)})" if extra else ""), file=sys.stderr)
    print("[shard] slowest modules: " + ", ".join(f"{m} {s:.0f}s" for m, s in
                                                 sorted(spent.items(), key=lambda kv: -kv[1])[:8]), file=sys.stderr)
    if times_out:
        times_out.write_text(json.dumps(spent, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--shards", type=int, required=True)
    r = sub.add_parser("run")
    r.add_argument("--shards", type=int, required=True)
    r.add_argument("--index", type=int, required=True, help="1-based")
    r.add_argument("--times", type=Path)
    g = sub.add_parser("merge")
    g.add_argument("files", nargs="+", type=Path)
    m = sub.add_parser("summary", help="markdown: the slowest modules of a merged timing file, and the plan's balance")
    m.add_argument("file", type=Path)
    m.add_argument("--shards", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        times = timings()
        for i, s in enumerate(plan(a.shards), 1):
            print(f"shard {i} ({sum(times.get(m, DEFAULT) for m in s):.0f} s): {' '.join(s)}")
        return 0
    if a.cmd == "merge":
        merged: dict[str, float] = {}
        for f in a.files:                         # the slower measurement of a module wins (macOS or Linux)
            for k, v in json.loads(f.read_text(encoding="utf-8")).items():
                merged[k] = max(merged.get(k, 0.0), float(v))
        print(json.dumps({"modules": dict(sorted(merged.items()))}, indent=1))
        return 0
    if a.cmd == "summary":
        times = timings(a.file)
        print("### Slowest test modules (seconds, the slower of Linux and macOS)\n")
        for k, v in sorted(times.items(), key=lambda kv: -kv[1])[:15]:
            print(f"- {k}: {v:.0f}")
        loads = [sum(times.get(x, DEFAULT) for x in s) for s in plan(a.shards, times=times)]
        print(f"\nShards planned from these times: {', '.join(f'{x:.0f} s' for x in loads)}\n")
        return 0
    if not 1 <= a.index <= a.shards:
        ap.error("--index is 1-based and at most --shards")
    mods = plan(a.shards)[a.index - 1]
    print(f"[shard] {a.index}/{a.shards}: {' '.join(mods)}", file=sys.stderr, flush=True)
    return 0 if run(mods, a.times) else 1


if __name__ == "__main__":
    sys.exit(main())
