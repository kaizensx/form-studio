"""Run the design bench's evaluation briefs through a real agent in Form Studio's chat, and record for each brief
whether the agent's first build worked, whether it ended with a design that builds, how many builds it tried, how
long it took, and the bench score of the design it left (tests/design_bench/bench.py).

    .venv/bin/python scripts/design_eval.py --agent codex                       # every brief marked eval or solution
    .venv/bin/python scripts/design_eval.py --agent claude --effort low --only eval_slider,eval_coupler
    .venv/bin/python scripts/design_eval.py --agent codex --root ../old-checkout --json before.json   # another engine

Each brief runs in its own empty data folder (FORM_DATA), headless (`form chat --json`), with the brief as the whole
message plus "Purpose: just a 3D model". It uses the person's agent CLI and account, so it costs what the agent costs:
run a few briefs first. Nothing is printed or uploaded. Results are computed from the conversation's events (a tool
result is ok or not) and from the design's final source built in this process; the score is the bench's heuristic.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDS = ("create_design", "update_design", "build_candidates", "propose_concepts")


def _bench():
    spec = importlib.util.spec_from_file_location("design_bench", ROOT / "tests" / "design_bench" / "bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _events(data: Path) -> list[dict]:
    out = []
    for f in sorted((data / ".conversations").glob("*/events.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _final_source(data: Path) -> Path | None:
    """The source file of the most recently changed design in the data folder."""
    best, when = None, 0.0
    for pj in data.glob("*/project.json"):
        try:
            p = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rid = str(p.get("recipe") or "")
        if not rid.startswith("src:"):
            continue
        f = data / ".sources" / f"{rid[4:]}.py"
        t = pj.stat().st_mtime
        if f.is_file() and t > when:
            best, when = f, t
    return best


def run_brief(b: dict, agent: str, effort: str, model: str, root: Path, timeout: float) -> dict:
    data = Path(tempfile.mkdtemp(prefix=f"form-eval-{b['id']}-"))
    env = dict(os.environ, FORM_DATA=str(data), FORM_SKIP_UI="1", PYTHONPATH=str(root))
    msg = b["brief"] + "\n\nPurpose: just a 3D model."
    cmd = [str(Path(sys.executable)), "-m", "form", "chat", msg, "--agent", agent, "--json"]
    if effort:
        cmd += ["--effort", effort]
    if model:
        cmd += ["--model", model]
    t0 = time.time()
    try:
        subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
    secs = time.time() - t0
    evs = _events(data)
    names = {e.get("id"): e.get("name") for e in evs if e.get("t") == "tool"}
    builds = [e for e in evs if e.get("t") == "result" and (e.get("name") or names.get(e.get("id"))) in BUILDS]
    limit = any(e.get("t") == "error" and e.get("kind") == "usage_limit" for e in evs)
    row = {"id": b["id"], "agent": agent, "effort": effort or "default", "seconds": round(secs, 1),
           "timed_out": timed_out, "builds_tried": len(builds), "first_build_ok": bool(builds and builds[0].get("ok")),
           "final_build_ok": False, "usage_limit": limit, "data": str(data),
           "steps": sum(1 for e in evs if e.get("t") == "tool")}
    src = _final_source(data)
    if src is not None:
        bench = _bench()
        spec = importlib.util.spec_from_file_location(f"eval_{b['id']}", src)
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            rec = mod.Design()
            rec.id = f"eval:{b['id']}"
            m = bench.check(rec, f"eval-{b['id']}", bench.product_class(b))
            s = bench.score(b, m)
            row.update(final_build_ok=not m.get("error"), score=s["total"], status=s["status"], notes=s["notes"][:6])
        except Exception as e:                       # a source that does not even load scores 0
            row.update(score=0, status="failed to load", notes=[f"{type(e).__name__}: {e}"[:200]])
    else:
        row.update(score=None, status="no design")
    return row


def summary(rows: list[dict]) -> dict:
    n = len(rows) or 1
    scored = [r["score"] for r in rows if isinstance(r.get("score"), (int, float))]
    return {"briefs": len(rows), "first_build_rate": round(sum(r["first_build_ok"] for r in rows) / n, 3),
            "final_build_rate": round(sum(r["final_build_ok"] for r in rows) / n, 3),
            "mean_score": round(sum(scored) / len(scored), 1) if scored else None,
            "mean_builds_tried": round(sum(r["builds_tried"] for r in rows) / n, 2),
            "mean_seconds": round(sum(r["seconds"] for r in rows) / n, 1),
            "usage_limited": sum(r["usage_limit"] for r in rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", default="codex")
    ap.add_argument("--effort", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--only")
    ap.add_argument("--root", type=Path, default=ROOT, help="the Form Studio checkout whose engine runs the chat")
    ap.add_argument("--timeout", type=float, default=1500)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    briefs = json.loads((ROOT / "tests" / "design_bench" / "briefs.json").read_text(encoding="utf-8"))["briefs"]
    pick = [b for b in briefs if (b.get("eval") or b.get("solution"))]
    if a.only:
        want = set(a.only.split(","))
        pick = [b for b in briefs if b["id"] in want]
    rows = []
    for b in pick:
        r = run_brief(b, a.agent, a.effort, a.model, a.root.resolve(), a.timeout)
        rows.append(r)
        print(json.dumps({k: r.get(k) for k in ("id", "first_build_ok", "final_build_ok", "builds_tried", "score",
                                                "seconds", "usage_limit")}), flush=True)
        if r["usage_limit"]:
            print("The agent reached its usage limit; stopping.", flush=True)
            break
    out = {"summary": summary(rows), "rows": rows}
    print(json.dumps(out["summary"], indent=1))
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
