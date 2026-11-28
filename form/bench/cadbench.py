"""Parametric CAD Bench v3 (arXiv 2611.02659) through Form Studio: each task's prompt to an agent with Form Studio's
MCP server, the answer scored by the task's own verifier.

    form bench cadbench --tasks DIR --agent claude-code --model <model> [--task ID ...] [--limit N] [--out DIR]
    form bench cadbench --download DIR          fetch the pinned task set with Harbor (harbor download)

What is public and what this uses, unchanged:

* the 100 tasks (30 create, 30 create-and-edit, 40 image-to-CAD) of `gnucleus-ai/cad-bench@v3`, pinned to its
  content digest DIGEST, from Harbor Hub (`harbor download`), Apache-2.0 (github.com/gNucleus-AI/cad-bench-submission);
* each task's verifier: tests/test.sh and tests/run_scorer.py, run in the image its tests/Dockerfile builds
  (FreeCAD 1.1.0, gnucleus-freecad-validator 0.6.0, OCP 7.9.3.1 from conda-forge), with the held-back reference and
  spec copied to /opt/grader exactly where that image puts them, and no network;
* the scoring rule of the leaderboard: the mean reward over all tasks, a missing or failed trial counting zero,
  create-and-edit one trial scored by its own harmonic mean, mode means over 30, 30 and 40.

What differs from a leaderboard run, and is written into every result:

* the agent runs on this computer, not in the task's agent container. The prompt is instruction.md as published,
  with one substitution: "/app" becomes the trial's folder. A preamble says where that folder is, that Form Studio's
  MCP tools are attached, and where FreeCAD's command line is (FreeCAD as installed here, not the image's 1.1.0);
* the agent's tools are Form Studio's MCP tools plus Read, Write and Edit inside the trial folder and Bash limited to
  FreeCAD's command line (Form Studio has no FreeCAD PartDesign export yet, and the verifier accepts only a
  PartDesign feature tree, so the agent writes the FreeCAD script itself);
* the result is not a Harbor job and cannot be submitted as one. A leaderboard row needs `harbor run` with an
  adapter that installs Form Studio in the task's container (not written yet).

The agent never sees solution/ or tests/: a trial folder gets only the task's environment files (the drawing).
Every trial runs with its own Form Studio data folder and configuration, so nothing touches the person's designs.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

DATASET = "gnucleus-ai/cad-bench"
TAG = "v3"
DIGEST = "sha256:8a786725d3648a76282fc5868df06da3d5e00d603f283573a53430803465d78a"
HARBOR = "0.23.0"
MODE_COUNTS = {"create": 30, "create_edit": 30, "image_to_cad": 40}
ANSWERS = {"create": ["answer.py", "answer.FCStd"], "image_to_cad": ["answer.py", "answer.FCStd"],
           "create_edit": ["answer.py", "answer_base.FCStd", "answer_edit.FCStd"]}
SOURCES = {"paper": "https://arxiv.org/abs/2611.02659", "tasks": "https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench/v3",
           "submission": "https://github.com/gNucleus-AI/cad-bench-submission",
           "validator": "https://github.com/gNucleus-AI/freecad-validator", "site": "https://cadbench.ai/"}
AGENTS = {"claude-code": "claude", "claude": "claude", "standin": "standin"}
HOST_TOOLS = {"Read", "Write", "Edit", "Bash", "ToolSearch", "WebSearch", "WebFetch", "TodoWrite", "Glob", "Grep"}
ROOT = Path(__file__).resolve().parents[2]


class BenchError(Exception):
    pass


# ---- tasks ------------------------------------------------------------------------------------------------------

def find_tasks(where: Path) -> list[Path]:
    """Task folders (each with task.toml and instruction.md) under a `harbor download` export or a folder of tasks."""
    where = Path(where)
    for cand in (where / "cad-bench", where):
        found = sorted(p.parent for p in cand.glob("*/task.toml"))
        if found:
            return found
    return []


def mode_of(task: Path) -> str:
    meta = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    arts = [Path(a).name for a in meta.get("artifacts", [])]
    if "answer_base.FCStd" in arts:
        return "create_edit"
    env = task / "environment"
    if env.is_dir() and any(p.suffix.lower() in (".png", ".jpg", ".jpeg") for p in env.iterdir()):
        return "image_to_cad"
    return "create"


def task_meta(task: Path) -> dict:
    meta = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    return {"id": task.name, "name": meta.get("task", {}).get("name", task.name), "mode": mode_of(task),
            "agent_timeout_s": float(meta.get("agent", {}).get("timeout_sec", 9000)),
            "verifier_timeout_s": float(meta.get("verifier", {}).get("timeout_sec", 600)),
            "description": meta.get("task", {}).get("description", "")}


def download(dest: Path) -> dict:
    exe = shutil.which("harbor")
    if not exe:
        raise BenchError(f"Harbor is not installed. Install it ({HARBOR}: `uv tool install harbor=={HARBOR}`), then run "
                         "this again; or download the tasks yourself with "
                         f"`harbor download {DATASET}@{DIGEST} -o DIR` and pass --tasks DIR.")
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([exe, "download", f"{DATASET}@{DIGEST}", "-o", str(dest)], capture_output=True, text=True)
    if r.returncode != 0:
        raise BenchError((r.stderr or r.stdout)[-800:])
    return {"tasks": len(find_tasks(dest)), "dir": str(dest), "dataset": f"{DATASET}@{DIGEST}"}


# ---- the prompt -------------------------------------------------------------------------------------------------

def prompt_for(task: Path, ws: Path, freecad: str | None) -> str:
    text = (task / "instruction.md").read_text(encoding="utf-8")
    text = re.sub(r"/app(?=/|\b)", ws.as_posix(), text)
    run = (f'{freecad} -c "import runpy; runpy.run_path(\'{ws.as_posix()}/answer.py\', run_name=\'__main__\')"'
           if freecad else "(FreeCAD's command line was not found on this computer)")
    pre = ("This is a benchmark task (Parametric CAD Bench v3), run through Form Studio. The task's folder /app is "
           f"{ws.as_posix()} here: read and write files only there. Form Studio's MCP tools are attached: use them to "
           "design, build and check the part as you would for a person. The answer must be the FreeCAD files the task "
           "names, so write the FreeCAD script yourself and run it with FreeCAD's command line:\n\n    " + run +
           "\n\nThe task as published follows.\n\n---\n\n")
    return pre + text


def harness_note() -> str:
    return ("Prompt: instruction.md as published, '/app' replaced by the trial folder, after a preamble naming that "
            "folder, Form Studio's MCP tools and FreeCAD's command line. Tools: Form Studio's MCP tools; Read, Write and "
            "Edit in the trial folder; Bash limited to FreeCAD's command line. Agent on the host, not in the task's "
            "container; FreeCAD as installed on the host. Scoring: the task's own verifier image and scripts, unchanged, "
            "no network. One attempt per task, no retries.")


# ---- agents -----------------------------------------------------------------------------------------------------

def _standin_adapter():
    from ..agents.base import Adapter
    from ..agents.claude import ClaudeParser

    script = os.environ.get("FORM_UITEST_AGENT") or str(Path(__file__).with_name("standin.py"))
    bench_own = Path(script).name == "standin.py"

    class StandIn(Adapter):
        id, label, cli = "standin", "Stand-in agent (deterministic, no model)", "python"

        def executable(self, cfg):
            return sys.executable

        def command(self, run, exe):
            if bench_own:
                return [exe, script, "--mcp", json.dumps(run.mcp), "--cwd", str(run.cwd),
                        "--freecad", os.environ.get("FORM_BENCH_FREECAD", ""), run.message]
            # $FORM_UITEST_AGENT: the app's stand-in contract (tests/fixtures/fake_agent.py)
            return [exe, script, str((run.mcp.get("env") or {}).get("FORM_DATA", "")), "-", run.model or "default", run.message]

        def parser(self):
            return ClaudeParser()

    return StandIn()


def adapter_for(agent: str):
    aid = AGENTS.get(agent, agent)
    if aid == "standin":
        return _standin_adapter()
    from ..agents import ADAPTERS
    a = ADAPTERS.get(aid)
    if a is None:
        raise BenchError(f"Unknown agent {agent!r}. Agents: claude-code, standin.")
    if aid != "claude":
        raise BenchError(f"{a.label} is not wired for the bench yet: the harness passes its file tools only to Claude "
                         "Code so far. Use --agent claude-code or --agent standin.")
    return a


def isolated_env(trial: Path, freecad: str | None) -> dict:
    """A data folder and configuration of the trial's own: the person's designs and settings are never read."""
    data = trial / "form-data"
    data.mkdir(parents=True, exist_ok=True)
    cfg = trial / "studio.toml"
    cfg.write_text(f'[data]\ndir = "{data.as_posix()}"\n\n[chat]\nweb = false\n'
                   + (f'\n[cad]\nfreecad = "{freecad}"\n' if freecad else ""), encoding="utf-8")
    return {"FORM_DATA": str(data), "FORM_CONFIG": str(cfg), "FORM_NO_UPDATE_CHECK": "1",
            "PYTHONPATH": os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p),
            "FORM_ENGINES_DIR": os.environ.get("FORM_ENGINES_DIR", str(data / ".engines"))}


def run_agent(meta: dict, task: Path, trial: Path, agent: str, model: str, effort: str, budget: float,
              freecad: str | None, timeout: float | None = None) -> dict:
    from ..agents.base import Run
    ws = trial / "app"
    ws.mkdir(parents=True, exist_ok=True)
    env_dir = task / "environment"
    if env_dir.is_dir():
        for f in env_dir.iterdir():
            if f.is_file() and f.name != "Dockerfile":
                shutil.copy2(f, ws / f.name)
    adapter = adapter_for(agent)
    exe = adapter.executable({"chat": {}})
    if not exe:
        raise BenchError(f"{adapter.label} is not installed ({adapter.cli} not on PATH).")
    env = isolated_env(trial, freecad)
    mcp = {"command": sys.executable, "args": ["-m", "form.mcp_server", "--no-bench"], "env": env}
    message = prompt_for(task, ws, freecad)
    root = "/" + ws.as_posix().rstrip("/")
    extra = [f"Read({root}/**)", f"Write({root}/**)", f"Edit({root}/**)"] + ([f"Bash({freecad}:*)"] if freecad else [])
    os.environ.setdefault("FORM_BENCH_FREECAD", freecad or "")
    try:
        from ..chat import system_prompt
        from .. import config
        old = {k: os.environ.get(k) for k in ("FORM_DATA", "FORM_CONFIG")}
        os.environ.update({"FORM_DATA": env["FORM_DATA"], "FORM_CONFIG": env["FORM_CONFIG"]})
        try:
            system = system_prompt(config.load(), None, adapter, message)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    except Exception:                                                  # noqa: BLE001 - the stand-in needs none
        system = ""
    scratch = Path(tempfile.mkdtemp(prefix="form-bench-"))
    run = Run(message=message, system=system, model=model, effort=effort, cwd=ws, scratch=scratch, mcp=mcp, web=False,
              budget_usd=budget, extra_tools=extra, tool_timeout_s=600)
    (trial / "prompt.md").write_text(message, encoding="utf-8")
    parser = adapter.parser()
    events: list = []
    t0 = time.time()
    timed_out = False
    try:
        cmd = adapter.command(run, exe)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace", cwd=str(ws), bufsize=1,
                                env=dict(os.environ, **env, **adapter.run_env(run)))
        err: list[str] = []
        drain = threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True)
        drain.start()
        killer = threading.Timer(timeout or meta["agent_timeout_s"], proc.kill)
        killer.start()
        with open(trial / "trajectory.jsonl", "w", encoding="utf-8") as raw:
            for line in proc.stdout:
                raw.write(line)
                events += parser.feed(line)
        proc.wait()
        timed_out = not killer.is_alive() and proc.returncode != 0
        killer.cancel()
        events += parser.finish()
        drain.join(timeout=5)
        (trial / "agent.log").write_text("".join(err), encoding="utf-8")
        rc = proc.returncode
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    end = next((e for e in reversed(events) if e.get("t") == "end"), {})
    start = next((e for e in events if e.get("t") == "start"), {})
    tools = [e.get("name") for e in events if e.get("t") == "tool"]
    return {"exit": rc, "timed_out": timed_out, "seconds": round(time.time() - t0, 1), "cost_usd": end.get("cost_usd"),
            "turns": end.get("turns"), "model_reported": start.get("model"), "tool_calls": len(tools),
            "form_tool_calls": sum(1 for t in tools if str(t).split("__")[-1] not in HOST_TOOLS),
            "form_tools": sorted({str(t).split("__")[-1] for t in tools} - HOST_TOOLS),
            "error": end.get("error") or (next((e.get("text") for e in events if e.get("t") == "error"), None))}


# ---- scoring ----------------------------------------------------------------------------------------------------

def docker() -> str | None:
    exe = shutil.which("docker")
    if not exe:
        return None
    r = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True)
    return exe if r.returncode == 0 else None


def verifier_image(task: Path) -> str:
    """The image the task's tests/Dockerfile builds, cached by the Dockerfile's hash. Built from a copy of tests/ with
    an empty grader/, so one image serves every task of that Dockerfile; each trial copies its own grader in."""
    exe = docker()
    if not exe:
        raise BenchError("Docker is not running. The verifier runs in the task's own image (tests/Dockerfile).")
    dockerfile = task / "tests" / "Dockerfile"
    tag = "form-cadbench-verifier:" + hashlib.sha256(dockerfile.read_bytes()).hexdigest()[:12]
    if subprocess.run([exe, "image", "inspect", tag], capture_output=True).returncode == 0:
        return tag
    with tempfile.TemporaryDirectory(prefix="form-bench-ctx-") as ctx:
        shutil.copytree(task / "tests", Path(ctx) / "tests", ignore=shutil.ignore_patterns("grader"))
        (Path(ctx) / "tests" / "grader").mkdir()
        r = subprocess.run([exe, "build", "-q", "-t", tag, "-f", str(Path(ctx) / "tests" / "Dockerfile"), str(Path(ctx) / "tests")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise BenchError("Building the verifier image failed: " + (r.stderr or r.stdout)[-800:])
    return tag


def score(task: Path, trial: Path, meta: dict) -> dict:
    """Run tests/test.sh in the verifier image: /tests and /opt/grader from the task, /app from the trial, no network.
    Returns the reward and the verifier's details exactly as it wrote them."""
    exe = docker()
    if not exe:
        raise BenchError("Docker is not running.")
    tag = verifier_image(task)
    ver = trial / "verifier"
    shutil.rmtree(ver, ignore_errors=True)
    ver.mkdir(parents=True)
    cid = subprocess.run([exe, "create", "--network", "none", "--cpus", "2", "--memory", "4g", tag, "bash", "/tests/test.sh"],
                         capture_output=True, text=True, check=True).stdout.strip()
    try:
        for src, dst in ((task / "tests", "/tests/"), (task / "tests" / "grader", "/opt/grader/"), (trial / "app", "/app/")):
            subprocess.run([exe, "cp", f"{src}/.", f"{cid}:{dst}"], capture_output=True, check=True)
        try:
            r = subprocess.run([exe, "start", "-a", cid], capture_output=True, text=True, timeout=meta["verifier_timeout_s"] + 60)
            (ver / "test-stdout.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired:
            subprocess.run([exe, "kill", cid], capture_output=True)
            return {"reward": None, "error": "verifier timed out"}
        subprocess.run([exe, "cp", f"{cid}:/logs/verifier/.", str(ver)], capture_output=True)
    finally:
        subprocess.run([exe, "rm", "-f", cid], capture_output=True)
    try:
        reward = json.loads((ver / "reward.json").read_text(encoding="utf-8")).get("reward")
    except (OSError, ValueError):
        return {"reward": None, "error": "the verifier wrote no reward.json"}
    try:
        details = json.loads((ver / "reward_details.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        details = {}
    return {"reward": float(reward), "details": details, "image": tag}


# ---- a run ------------------------------------------------------------------------------------------------------

def aggregate(trials: list[dict], dataset_counts: dict | None = None) -> dict:
    """The leaderboard's rule: every task counts, a trial without a reward counts zero, mode means over the mode's task
    count. With a subset of tasks the denominators are the subset's (and the result says it is a subset)."""
    counts = dataset_counts or {}
    by: dict = {m: [] for m in MODE_COUNTS}
    for t in trials:
        by.setdefault(t["mode"], []).append(float(t.get("reward") or 0.0))
    n = len(trials)
    out = {"tasks": n, "complete": n == sum(MODE_COUNTS.values()) and all(len(by[m]) == MODE_COUNTS[m] for m in MODE_COUNTS),
           "mean_reward": round(sum(sum(v) for v in by.values()) / n, 6) if n else None,
           "scored": sum(1 for t in trials if t.get("reward") is not None),
           "errors": sum(1 for t in trials if t.get("reward") is None),
           "perfect": sum(1 for t in trials if (t.get("reward") or 0) >= 1.0 - 1e-9), "modes": {}}
    for m, v in by.items():
        if v:
            d = counts.get(m) or len(v)
            out["modes"][m] = {"tasks": len(v), "mean_reward": round(sum(v) / d, 6)}
    return out


def _git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def provenance() -> dict:
    from .. import __version__
    return {"form_version": __version__, "commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain", "--", "form", "scripts")),
            "machine": f"{platform.machine()}, {platform.system()} {platform.release()}, {os.cpu_count()} cores",
            "python": platform.python_version(), "date": _dt.date.today().isoformat()}


def run(tasks_dir: Path, agent: str, model: str = "", effort: str = "", ids: list[str] | None = None,
        limit: int | None = None, out: Path | None = None, budget: float = 10.0, timeout: float | None = None,
        progress=None) -> dict:
    from .. import cad_bridges
    tasks = find_tasks(tasks_dir)
    if not tasks:
        raise BenchError(f"No tasks under {tasks_dir}. Fetch them with `form bench cadbench --download DIR`.")
    if ids:
        want = set(ids)
        tasks = [t for t in tasks if t.name in want or t.name.removeprefix("freecad-") in want]
    if limit:
        tasks = tasks[:limit]
    freecad = os.environ.get("FORM_FREECADCMD") or cad_bridges.find_freecad({})
    fc_version = cad_bridges.version(freecad) if freecad and hasattr(cad_bridges, "version") else None
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(out or Path(tempfile.gettempdir()) / "form-cadbench" / f"{stamp}-{agent}")
    out.mkdir(parents=True, exist_ok=True)
    counts = {m: 0 for m in MODE_COUNTS}
    for t in find_tasks(tasks_dir):
        counts[mode_of(t)] = counts.get(mode_of(t), 0) + 1
    trials = []
    for i, task in enumerate(tasks, 1):
        meta = task_meta(task)
        trial = out / "trials" / task.name
        if trial.exists():
            shutil.rmtree(trial)
        trial.mkdir(parents=True)
        row = {"task": meta["name"], "id": task.name, "mode": meta["mode"], "reward": None}
        try:
            row["agent"] = run_agent(meta, task, trial, agent, model, effort, budget, freecad, timeout)
        except BenchError as e:
            row["agent"] = {"error": str(e)}
        made = [n for n in ANSWERS[meta["mode"]] if (trial / "app" / n).is_file()]
        row["answers"] = made
        try:
            s = score(task, trial, meta)
            row["reward"] = s.get("reward")
            row["details"] = _short(s.get("details") or {})
            if s.get("error"):
                row["error"] = s["error"]
        except (BenchError, subprocess.CalledProcessError) as e:
            row["error"] = f"not scored: {e}"
        (trial / "result.json").write_text(json.dumps(row, indent=1), encoding="utf-8")
        trials.append(row)
        if progress:
            progress(i, len(tasks), row)
    full = len(find_tasks(tasks_dir)) == len(tasks)
    res = {"benchmark": "Parametric CAD Bench v3", "dataset": f"{DATASET}@{TAG}", "digest": DIGEST, "sources": SOURCES,
           "agent": agent, "model": model or "default", "effort": effort or "default",
           "standin": AGENTS.get(agent, agent) == "standin",
           "freecad_on_host": fc_version or freecad or "not found", "harness": harness_note(), **provenance(),
           "summary": aggregate(trials, counts if full else None), "trials": trials, "out": str(out),
           "leaderboard_comparable": False}
    (out / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _short(details: dict) -> dict:
    """The verifier's details, keeping the sub-scores and the first part of each reason."""
    def cut(d):
        return {k: (v[:400] if isinstance(v, str) else cut(v) if isinstance(v, dict) else v) for k, v in d.items()}
    return cut(details)


def oracle(task: Path, out: Path) -> dict:
    """Score the task's own reference as the answer (what solution/solve.sh does). The verifier should give 1.0: this
    is the parity check between the harness's scoring and the task's verifier."""
    meta = task_meta(task)
    trial = Path(out) / task.name
    shutil.rmtree(trial, ignore_errors=True)
    (trial / "app").mkdir(parents=True)
    sol = task / "solution"
    if meta["mode"] == "create_edit":
        shutil.copy2(sol / "reference_base.FCStd", trial / "app" / "answer_base.FCStd")
        shutil.copy2(sol / "reference_target.FCStd", trial / "app" / "answer_edit.FCStd")
    else:
        shutil.copy2(sol / "reference.FCStd", trial / "app" / "answer.FCStd")
    (trial / "app" / "answer.py").write_text("# oracle: the held-back reference, as solution/solve.sh copies it\n")
    return {"task": task.name, "mode": meta["mode"], **score(task, trial, meta)}
