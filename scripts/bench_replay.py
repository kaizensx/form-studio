"""Replay a sequence of agent tool calls on a copy of a real project and count what the engine did: kernel builds
(B-rep constructions in the worker processes), their seconds, wall time per call and kernel restarts.

This is the before/after harness for engine work: run it on one commit, then on another, with the same arguments.
Nothing is read from or written to the data folder it copies from (default ~/FORM): the project and the design
sources are copied to a new temporary folder, which is the only FORM_DATA the run sees. No app window opens, no
agent runs, nothing is sliced (auto-slice is switched off in the copy).

    # a canned sequence on one revision: update_design to r05 from r04, then the usual follow-ups
    .venv/bin/python scripts/bench_replay.py --project ~/FORM/.trash/adjustable-shower-head-holder-20261119T132822Z \\
        --rev 5 --steps update,render,analyze,pipeline,render_iso,export --fresh

    # the tool calls of a logged conversation (events 45 to 58 of its events.jsonl), from the revision before them
    .venv/bin/python scripts/bench_replay.py --project <project dir> --conversation ~/FORM/.conversations/<id> \\
        --events 45:58

--fresh then starts a second process on the same copied data (its own kernel workers, the tessellated-view cache
removed) and asks for the head's view and a probe, which needs the B-rep: a build there is a build a disk store
would have saved. --json writes every number. Builds are counted by a hook the harness puts in front of the kernel
module of the workers it starts (sitecustomize on PYTHONPATH): it wraps kernel._build_brep when the kernel has one,
else kernel._build, and writes one line per call.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOOK = r'''
import json, os, sys, time
_LOG = os.environ.get("FORM_BENCH_LOG")
if _LOG:
    import importlib.abc, importlib.machinery

    def _patch(mod):
        name = "_build_brep" if hasattr(mod, "_build_brep") else "_build"
        fn = getattr(mod, name)

        def counted(recipe_id, *a, **kw):
            t = time.time()
            ok = False
            try:
                out = fn(recipe_id, *a, **kw)
                ok = True
                return out
            finally:
                try:
                    with open(_LOG, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"pid": os.getpid(), "t": t, "s": round(time.time() - t, 3), "fn": name,
                                             "recipe": str(recipe_id), "ok": ok}) + "\n")
                except OSError:
                    pass
        setattr(mod, name, counted)

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name != "form.kernel":
                return None
            spec = importlib.machinery.PathFinder.find_spec(name, path)
            if spec is None or spec.loader is None:
                return spec
            run = spec.loader.exec_module

            def exec_module(mod):
                run(mod)
                _patch(mod)
            spec.loader.exec_module = exec_module
            return spec
    sys.meta_path.insert(0, _Finder())
'''


def builds(log: Path, since: float = 0.0) -> list[dict]:
    if not log.is_file():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("t", 0) >= since:
            out.append(e)
    return out


# ---- the copy -------------------------------------------------------------------------------------------------------

def copy_project(src_dir: Path, data_src: Path, dest: Path, base_rev: int | None, refine: bool = False) -> dict:
    """The project (its revisions up to base_rev, head there), every design source and the imported references, in
    dest. Artifacts and caches are not copied: the run starts cold, as a new revision does."""
    p = json.loads((src_dir / "project.json").read_text(encoding="utf-8"))
    full = json.loads(json.dumps(p))
    if base_rev is not None:
        p["revisions"] = [r for r in p["revisions"] if r["n"] <= base_rev]
        p["head"] = base_rev
        head = next(r for r in p["revisions"] if r["n"] == base_rev)
        p["recipe"] = head.get("recipe") or p["recipe"]
        p["approvals"] = [a for a in p.get("approvals", []) if a.get("rev", 0) <= base_rev]
    p["auto_slice"] = False                    # no slicer runs: slicing is not what this harness measures
    if not refine:                             # background refinement builds its own variants at its own pace
        p["refine"] = "off"
    pd = dest / p["id"]
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "project.json").write_text(json.dumps(p, indent=1), encoding="utf-8")
    for sub in (".sources", ".references"):
        s = data_src / sub
        if s.is_dir():
            shutil.copytree(s, dest / sub, dirs_exist_ok=True)
    return full


def rev_of(full: dict, n: int) -> dict:
    return next(r for r in full["revisions"] if r["n"] == n)


def source_of(data: Path, rid: str) -> str:
    from form.recipes import source_path
    return source_path(data / ".sources", rid).read_text(encoding="utf-8")


# ---- steps ------------------------------------------------------------------------------------------------------------

def canned(step: str, pid: str, full: dict, rev: int, data: Path, out: Path) -> tuple[str, dict]:
    if step == "update":
        r = rev_of(full, rev)
        return "update_design", {"project": pid, "source": source_of(data, r["recipe"]), "values": r["values"],
                                 "expect_head": r.get("parent", rev - 1), "note": r.get("note", "")}
    if step == "pipeline":
        return "run_pipeline", {"project": pid, "wait_s": 300}
    if step == "render":
        return "render", {"project": pid, "view": "sheet"}
    if step == "render_iso":
        return "render", {"project": pid, "view": "iso"}
    if step == "analyze":
        return "analyze", {"project": pid, "map": "thickness"}
    if step == "features":
        return "analyze", {"project": pid, "map": "features"}
    if step == "export":
        return "export_project", {"project": pid, "path": str(out / f"{pid}.formstudio")}
    if step == "get_project":
        return "get_project", {"project": pid}
    raise SystemExit(f"unknown step {step}")


_ARG = re.compile(r"(?:^|\s)([a-z_]+)=")


def parse_input(text: str) -> dict:
    """events.jsonl keeps a tool's input as `key=value key=value` (long values summarised)."""
    out, marks = {}, list(_ARG.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        raw = text[m.end():end].strip()
        try:
            out[m.group(1)] = json.loads(raw)
        except ValueError:
            out[m.group(1)] = raw
    return out


REPLAYED = {"update_design", "render", "analyze", "run_pipeline", "get_project", "measure", "preview_change",
            "commit_change", "get_design_source", "export_project", "checkout_revision", "suggest_orientation"}


def from_conversation(conv: Path, span: str, full: dict, data: Path) -> list[tuple[str, dict]]:
    lo, _, hi = span.partition(":")
    lo, hi = int(lo or 0), int(hi) if hi else 10 ** 9
    calls = []
    for i, line in enumerate((conv / "events.jsonl").read_text(encoding="utf-8").splitlines()):
        if not lo <= i < hi:
            continue
        e = json.loads(line)
        if e.get("t") != "tool" or e.get("name") not in REPLAYED:
            continue
        a = parse_input(e.get("input") or "")
        if a.get("project") not in (None, full["id"]):
            continue
        if e["name"] == "update_design":           # the revision it made: the one whose note this call carried
            note = str(a.get("note") or "")[:40]
            r = next((r for r in full["revisions"] if note and str(r.get("note", "")).startswith(note)), None)
            if r is None:
                print(f"event {i}: no revision with note {note!r}; skipped", file=sys.stderr)
                continue
            a = {"project": full["id"], "source": source_of(data, r["recipe"]), "values": r["values"],
                 "expect_head": a.get("expect_head", r.get("parent")), "note": r.get("note", "")}
        calls.append((e["name"], a))
    return calls


# ---- running ----------------------------------------------------------------------------------------------------------

def _text(res) -> str:
    return "\n".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")


async def replay(calls: list[tuple[str, dict]], log: Path, warm: int | None, pid: str, rids: set) -> list[dict]:
    from mcp import Client
    from form import mcp_server
    server = mcp_server.build()
    rows = []
    async with Client(server) as c:
        st = mcp_server.studio()
        ops: list = []                             # every kernel call this process makes: (op, seconds)
        call = st.kernel.call

        def traced(op, *a, **kw):
            t = time.time()
            try:
                return call(op, *a, **kw)
            finally:
                ops.append((op, time.time() - t))
        st.kernel.call = traced
        if warm is not None:                       # the app has the base revision open: not counted
            p = st.load(pid)
            st.view(p, warm)
        for name, args in calls:
            t0 = time.time()
            r0 = st.kernel.restarts
            n0 = len(ops)
            res = await c.call_tool(name, args)
            dt = time.time() - t0
            txt = _text(res)
            b = builds(log, t0)
            rows.append({"tool": name, "args": {k: (v if k != "source" else f"<{len(v.splitlines())} lines>")
                                                for k, v in args.items()},
                         "seconds": round(dt, 2), "builds": len(b),
                         "design_builds": sum(1 for x in b if x.get("recipe") in rids), "build_s": round(sum(x["s"] for x in b), 2),
                         "kernel_calls": [[o, round(x, 2)] for o, x in ops[n0:]],
                         "load": round(os.getloadavg()[0], 1),
                         "restarts": st.kernel.restarts - r0, "error": bool(getattr(res, "is_error", False)),
                         "timeout": "did not answer within" in txt, "text": txt[:300]})
            print(f"  {name:<16} {dt:7.2f} s  builds {len(b)} ({rows[-1]['build_s']:.2f} s, "
                  f"{rows[-1]['design_builds']} of the design)  "
                  f"restarts {rows[-1]['restarts']}  load {rows[-1]['load']}  kernel "
                  f"{' '.join(f'{o}:{x:.1f}' for o, x in rows[-1]['kernel_calls']) or '-'}{'  ERROR ' + txt[:160] if rows[-1]['error'] else ''}", flush=True)
        st.kernel.stop()
    return rows


def fresh_probe(pid: str) -> dict:
    """In a new process: the head's view (with the tessellated-view cache removed) and a probe on the B-rep."""
    from form import config
    from form.studio import Studio
    st = Studio(config.load())
    shutil.rmtree(st.root / ".cache" / "views", ignore_errors=True)
    p = st.load(pid)
    out = {}
    t = time.time()
    v = st.view(p)
    out["view_s"] = round(time.time() - t, 2)
    bb = v["bbox"]
    at = [(a + b) / 2 for a, b in zip(*bb)]
    at[2] = bb[1][2]
    from form import analysis
    t = time.time()
    try:
        analysis.probe(st, p, at) if hasattr(analysis, "probe") else None
    except Exception as e:                         # noqa: BLE001 - the probe may miss the surface; the build counts
        out["probe_error"] = str(e)[:200]
    out["probe_s"] = round(time.time() - t, 2)
    out["restarts"] = st.kernel.restarts
    st.kernel.stop()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=False, help="the project folder to copy (in ~/FORM or its .trash)")
    ap.add_argument("--data", default="~/FORM", help="the data folder its design sources are in (read only)")
    ap.add_argument("--rev", type=int, help="canned steps: the revision update_design makes (from its parent)")
    ap.add_argument("--base-rev", type=int, help="the head of the copy (default: --rev's parent, or the conversation's "
                                                  "first expect_head)")
    ap.add_argument("--steps", default="update,render,analyze,pipeline,render_iso,export")
    ap.add_argument("--conversation", help="a conversation folder whose events.jsonl to replay instead of --steps")
    ap.add_argument("--events", default="0:", help="events a:b of the conversation")
    ap.add_argument("--warm", action="store_true", help="view the base revision first (not counted)")
    ap.add_argument("--fresh", action="store_true", help="then a fresh process views the head and probes the B-rep")
    ap.add_argument("--refine", action="store_true", help="leave background refinement on (off by default: it "
                                                           "builds variants of its own, at its own pace)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary data folder")
    ap.add_argument("--json", help="write the results here")
    ap.add_argument("--fresh-probe", help=argparse.SUPPRESS)   # internal: the second process
    a = ap.parse_args(argv)

    if a.fresh_probe:
        print(json.dumps(fresh_probe(a.fresh_probe)))
        return 0

    data_src = Path(a.data).expanduser()
    src_dir = Path(a.project).expanduser()
    full = json.loads((src_dir / "project.json").read_text(encoding="utf-8"))
    pid = full["id"]
    base = a.base_rev
    if base is None and a.rev:
        base = rev_of(full, a.rev).get("parent", a.rev - 1)
    tmp = Path(tempfile.mkdtemp(prefix="form-bench-"))
    data = tmp / "data"
    hook = tmp / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(HOOK, encoding="utf-8")
    log = tmp / "builds.jsonl"
    os.environ.update({"FORM_DATA": str(data), "FORM_BENCH_LOG": str(log), "FORM_SKIP_UI": "1",
                       "PYTHONPATH": os.pathsep.join([str(hook), str(ROOT), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)})
    os.environ.pop("FORM_CHECKPOINTS", None)
    sys.path.insert(0, str(hook))
    import sitecustomize  # noqa: F401  (the hook also counts in this process, if a kernel ever loads here)

    if a.conversation:
        if base is None:
            lo, _, hi = a.events.partition(":")
            lines = (Path(a.conversation).expanduser() / "events.jsonl").read_text(encoding="utf-8").splitlines()
            for line in lines[int(lo or 0):int(hi) if hi else None]:
                e = json.loads(line)
                if e.get("t") == "tool" and e.get("name") == "update_design":
                    base = parse_input(e.get("input") or "").get("expect_head")
                    break
    copy_project(src_dir, data_src, data, base, a.refine)
    if a.conversation:
        calls = from_conversation(Path(a.conversation).expanduser(), a.events, full, data)
    else:
        calls = [canned(s.strip(), pid, full, a.rev, data, tmp) for s in a.steps.split(",") if s.strip()]
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"bench_replay: {pid} from r{base} on {git or '?'}; data {data}")
    t0 = time.time()
    rids = {r.get("recipe") or full["recipe"] for r in full["revisions"]}
    rows = asyncio.run(replay(calls, log, base if a.warm else None, pid, rids))
    total = {"seconds": round(time.time() - t0, 2), "builds": sum(r["builds"] for r in rows),
             "design_builds": sum(r["design_builds"] for r in rows),
             "build_s": round(sum(r["build_s"] for r in rows), 2), "restarts": sum(r["restarts"] for r in rows),
             "timeouts": sum(1 for r in rows if r["timeout"]), "errors": sum(1 for r in rows if r["error"])}
    print(f"  {'TOTAL':<16} {total['seconds']:7.2f} s  builds {total['builds']} ({total['build_s']:.2f} s, "
          f"{total['design_builds']} of the design)  "
          f"restarts {total['restarts']}  timeouts {total['timeouts']}  errors {total['errors']}")
    fresh = None
    if a.fresh:
        flog = tmp / "builds-fresh.jsonl"
        env = {**os.environ, "FORM_BENCH_LOG": str(flog)}
        t = time.time()
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--fresh-probe", pid], env=env,
                           capture_output=True, text=True, timeout=1800)
        fresh = {"seconds": round(time.time() - t, 2), "builds": len(builds(flog)),
                 "build_s": round(sum(x["s"] for x in builds(flog)), 2)}
        try:
            fresh.update(json.loads(r.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            fresh["error"] = (r.stderr or r.stdout)[-600:]
        print(f"  {'fresh process':<16} {fresh['seconds']:7.2f} s  builds {fresh['builds']} ({fresh['build_s']:.2f} s)"
              f"  view {fresh.get('view_s')} s  probe {fresh.get('probe_s')} s")
    res = {"commit": git, "project": pid, "base_rev": base, "steps": rows, "total": total, "fresh": fresh,
           "builds": builds(log)}
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    if not a.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
