"""Split the unit suite (tests/test_*.py) into shards of about equal run time and run one shard.

The run times come from tests/ci_timings.json: seconds per test class ("test_recon.OrganicBlob") or per module, for
each runner OS, measured on the CI runners. A unit that is not listed counts as DEFAULT seconds. A module whose listed
time is above SPLIT_ABOVE and that the file lists by class is split into its test classes (found in its source, so
none is left out; the runner checks that against the loaded module), each a unit of its own. Shards are filled
longest unit first, each into the shard with the least time so far, so the plan is stable for a given timing file.

    python scripts/ci/test_shards.py plan --shards 10                     # the plan, one line per shard
    python scripts/ci/test_shards.py run --shards 10 --index 1            # run shard 1 (1-based), verbose
    python scripts/ci/test_shards.py run --shards 10 --index 1 --times times-ubuntu-latest-1.json
    git diff --name-only A B | python scripts/ci/test_shards.py scope     # "full" or "light"

--os picks the timing section (default: $OS, else ubuntu-latest). --scope light leaves out the HEAVY modules: the
geometry kernel's long numeric runs, which read nothing but form/ and tests/. CI runs them on every pull request on
Linux and on every push to dev and main (and nightly) on macOS; a pull request that changes only documentation, the
site, artwork or other workflows (`scope`) runs the light scope on both.

`run` arms a per-test watchdog (FORM_TEST_TIMEOUT seconds, default 900): a test or a class set-up that runs longer
has every thread's stack printed and the shard ends, so a hang names its test instead of using up the job's time.
Refresh the timing file from a CI run's `times-*` artifacts (named times-<os>-<shard>.json) with `merge`:

    python scripts/ci/test_shards.py merge times-*/*.json > tests/ci_timings.json

Each OS's `test (<os>)` job keeps that merge for its own shards as measured-timings-<os>.json; merging both artifacts'
files gives the whole file.
"""
from __future__ import annotations

import argparse
import ast
import faulthandler
import fnmatch
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
TIMINGS = TESTS / "ci_timings.json"
DEFAULT = 10.0
SPLIT_ABOVE = 120.0
OSES = ("ubuntu-latest", "macos-latest")
# The long geometry runs (mesh to CAD, remodelling, the design bench, mesh bodies). They import only form/ and read
# only tests/ fixtures, never the docs, the site or the workflows.
HEAVY = ("test_recon", "test_recon_program", "test_remodel", "test_design_bench", "test_meshbody")
# A pull request whose every changed path matches one of these runs the light scope: nothing here is read by a HEAVY
# module. ci.yml, ci-studio.toml and this script are not here; anything not listed runs the full scope.
LIGHT_PATHS = ("docs/*", "site/*", "brand/*", "community/*", ".github/ISSUE_TEMPLATE/*", ".github/*.md",
               ".github/*.yml", ".github/workflows/*", "scripts/*", "LICENSE", ".coderabbit.yaml",
               ".pre-commit-config.yaml", ".gitignore")
FULL_PATHS = (".github/workflows/ci.yml", ".github/ci-studio.toml", "scripts/ci/test_shards.py")


def modules() -> list[str]:
    return sorted(p.stem for p in TESTS.glob("test_*.py"))


def classes(mod: str) -> list[str]:
    """The top-level classes of tests/<mod>.py with test methods of their own or from a test class above them in the
    same file, in source order."""
    tree = ast.parse((TESTS / f"{mod}.py").read_text(encoding="utf-8"))
    found: list[str] = []
    for n in tree.body:
        if not isinstance(n, ast.ClassDef):
            continue
        own = any(isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name.startswith("test") for b in n.body)
        if own or any(isinstance(b, ast.Name) and b.id in found for b in n.bases):
            found.append(n.name)
    return found


def cost(unit: str, times: dict[str, float]) -> float:
    """A unit's seconds: its own entry, else (a module) the sum of its classes' entries, else DEFAULT."""
    if unit in times:
        return times[unit]
    parts = [v for k, v in times.items() if k.startswith(unit + ".")]
    return sum(parts) if parts else DEFAULT


def units(mods: list[str], times: dict[str, float]) -> list[str]:
    """Modules, with each long module that the timings list by class replaced by its classes."""
    out = []
    for m in mods:
        if any(k.startswith(m + ".") for k in times) and cost(m, times) > SPLIT_ABOVE:
            out += [f"{m}.{c}" for c in classes(m)]
        else:
            out.append(m)
    return out


def timings(path: Path = TIMINGS, os_name: str | None = None) -> dict[str, float]:
    """One OS's section of the timing file (a file with a flat "modules" table serves every OS)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    os_name = os_name or os.environ.get("OS") or OSES[0]
    table = data.get(os_name, data.get("modules", {}))
    return {k: float(v) for k, v in table.items() if not k.startswith("_")}


def scope(paths: list[str]) -> str:
    """"light" when every changed path is one the HEAVY modules never read; otherwise "full"."""
    paths = [p.strip() for p in paths if p.strip()]
    if not paths:
        return "full"
    for p in paths:
        if ".." in p.split("/") or any(fnmatch.fnmatch(p, f) for f in FULL_PATHS):
            return "full"
        root_md = "/" not in p and p.endswith(".md")
        if not (root_md or any(fnmatch.fnmatch(p, f) for f in LIGHT_PATHS)):
            return "full"
    return "light"


def plan(n: int, mods: list[str] | None = None, times: dict[str, float] | None = None,
         light: bool = False) -> list[list[str]]:
    mods = modules() if mods is None else mods
    times = timings() if times is None else times
    if light:
        mods = [m for m in mods if m not in HEAVY]
    shards: list[list[str]] = [[] for _ in range(n)]
    load = [0.0] * n
    for u in sorted(units(mods, times), key=lambda u: (-cost(u, times), u)):
        i = min(range(n), key=lambda k: (load[k], k))
        shards[i].append(u)
        load[i] += cost(u, times)
    return [sorted(s) for s in shards]


class _Watchdog(unittest.TextTestResult):
    """Arms the hang watchdog around every test and times every test class (set-ups included)."""
    limit = 900.0
    spent: dict[str, float] = {}
    mark = 0.0

    def startTest(self, test):
        faulthandler.dump_traceback_later(self.limit, exit=True)
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        now = time.perf_counter()
        key = f"{type(test).__module__}.{type(test).__name__}"
        _Watchdog.spent[key] = _Watchdog.spent.get(key, 0.0) + now - _Watchdog.mark
        _Watchdog.mark = now
        faulthandler.dump_traceback_later(self.limit, exit=True)   # still armed for the next class's setUpClass


def _missing_classes(mod: str) -> list[str]:
    """Test classes of an imported module that classes() does not see (a split module would leave them out)."""
    m = sys.modules[mod]
    loader = unittest.TestLoader()
    real = {n for n, o in vars(m).items() if isinstance(o, type) and issubclass(o, unittest.TestCase)
            and o.__module__ == mod and loader.getTestCaseNames(o)}
    return sorted(real - set(classes(mod)))


def run(units_: list[str], times_out: Path | None = None) -> bool:
    sys.path[:0] = [str(TESTS), str(ROOT)]       # as `unittest discover -s tests` does: modules import each other by name
    os.chdir(ROOT)
    _Watchdog.limit = float(os.environ.get("FORM_TEST_TIMEOUT", "900"))
    runner = unittest.TextTestRunner(verbosity=2, resultclass=_Watchdog, stream=sys.stderr)
    result = runner._makeResult()
    spent: dict[str, float] = {}
    loader = unittest.TestLoader()
    checked: set[str] = set()
    lost: list[str] = []
    t_all = time.perf_counter()
    faulthandler.dump_traceback_later(_Watchdog.limit, exit=True)   # covers the first class's setUpClass too
    result.startTestRun()
    try:
        for u in units_:
            t0 = _Watchdog.mark = time.perf_counter()
            suite = loader.loadTestsFromName(u)
            mod = u.split(".")[0]
            if "." in u and mod not in checked:
                checked.add(mod)
                lost += [f"{mod}.{c}" for c in _missing_classes(mod)]
            suite.run(result)
            took = round(time.perf_counter() - t0, 1)
            print(f"[shard] {u}: {took:.1f} s", file=sys.stderr, flush=True)     # u: a module or module.Class
            spent[u] = took
    finally:
        faulthandler.cancel_dump_traceback_later()
        result.stopTestRun()
    took = time.perf_counter() - t_all
    result.printErrors()
    print(result.separator2, file=sys.stderr)
    print(f"Ran {result.testsRun} tests in {took:.1f}s", file=sys.stderr)
    ok = result.wasSuccessful() and not lost
    if lost:
        print(f"[shard] test classes no shard runs (scripts/ci/test_shards.py classes() missed them): {lost}",
              file=sys.stderr)
    extra = [f"failures={len(result.failures)}"] if result.failures else []
    extra += [f"errors={len(result.errors)}"] if result.errors else []
    extra += [f"skipped={len(result.skipped)}"] if result.skipped else []
    print(("OK" if ok else "FAILED") + (f" ({', '.join(extra)})" if extra else ""), file=sys.stderr)
    print("[shard] slowest units: " + ", ".join(f"{m} {s:.0f}s" for m, s in
                                               sorted(spent.items(), key=lambda kv: -kv[1])[:8]), file=sys.stderr)
    if times_out:
        # per class, so a long module can be split by class next time; a class's set-up counts towards it
        per_class = {k: round(v, 1) for k, v in _Watchdog.spent.items() if k.split(".")[0] in {u.split(".")[0] for u in units_}}
        times_out.write_text(json.dumps(per_class, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return ok


def merge(files: list[Path]) -> dict[str, dict[str, float]]:
    """times-<os>-<shard>.json files into one table per OS; the slower measurement of a unit wins."""
    out: dict[str, dict[str, float]] = {}
    for f in files:
        m = re.match(r"times-(.+)-\d+\.json$", f.name)
        table = out.setdefault(m.group(1) if m else "modules", {})
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            table[k] = max(table.get(k, 0.0), float(v))
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    r = sub.add_parser("run")
    for x in (p, r):
        x.add_argument("--shards", type=int, required=True)
        x.add_argument("--os", dest="os_name")
        x.add_argument("--scope", choices=("full", "light"), default="full")
    r.add_argument("--index", type=int, required=True, help="1-based")
    r.add_argument("--times", type=Path)
    g = sub.add_parser("merge")
    g.add_argument("files", nargs="+", type=Path)
    sub.add_parser("scope", help='changed paths on stdin, one per line: prints "full" or "light"')
    m = sub.add_parser("summary", help="markdown: the slowest units of a merged timing file, and the plan's balance")
    m.add_argument("file", type=Path)
    m.add_argument("--shards", type=int, default=10)
    m.add_argument("--os", dest="os_name")
    a = ap.parse_args(argv)
    if a.cmd == "scope":
        print(scope(sys.stdin.read().splitlines()))
        return 0
    if a.cmd == "merge":
        print(json.dumps(merge(a.files), indent=1))
        return 0
    if a.cmd == "summary":
        times = timings(a.file, a.os_name)
        print(f"### Slowest test units on {a.os_name or os.environ.get('OS') or OSES[0]} (seconds)\n")
        for k, v in sorted(times.items(), key=lambda kv: -kv[1])[:15]:
            print(f"- {k}: {v:.0f}")
        loads = [sum(cost(x, times) for x in s) for s in plan(a.shards, times=times)]
        print(f"\nTotal {sum(times.values()):.0f} s; {a.shards} shards planned from these times: "
              f"{', '.join(f'{x:.0f} s' for x in loads)}\n")
        return 0
    times = timings(os_name=a.os_name)
    shards = plan(a.shards, times=times, light=a.scope == "light")
    if a.cmd == "plan":
        for i, s in enumerate(shards, 1):
            print(f"shard {i} ({sum(cost(u, times) for u in s):.0f} s): {' '.join(s)}")
        return 0
    if not 1 <= a.index <= a.shards:
        ap.error("--index is 1-based and at most --shards")
    mods = shards[a.index - 1]
    print(f"[shard] {a.index}/{a.shards} ({a.scope}): {' '.join(mods)}", file=sys.stderr, flush=True)
    if not mods:
        print("[shard] nothing to run in this shard", file=sys.stderr)
        if a.times:
            a.times.write_text("{}\n", encoding="utf-8")
        return 0
    return 0 if run(mods, a.times) else 1


if __name__ == "__main__":
    sys.exit(main())
