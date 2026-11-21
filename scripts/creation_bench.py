"""Creation bench: the twenty briefs of tests/design_bench/creation_briefs.json run through Form Studio's MCP tools
(a real MCP stdio server, a temporary FORM_DATA), skeleton first and one feature per call, and measured.

    .venv/bin/python scripts/creation_bench.py --json bench.json                 # the scripted stub agent, all 20
    .venv/bin/python scripts/creation_bench.py --only hero_helmet,din_clip --no-score

The agent is tests/fixtures/scripted_agent.py: a deterministic replay of tool calls, no model and no network, so the
numbers measure the engine and the tools (a real agent is scripts/design_eval.py). Per brief and in sum:
  first build ok      create_design of the skeleton made a project that is not partial
  final build ok      the design left at the end builds fully (no partial-build block; with scoring, it builds
                      in this process as a valid B-rep with its declared solids)
  first visible       seconds from the brief's first tool call to the first stage mesh the engine reported (the
                      activity log's "stage" event), the moment a solid is on screen
  features            built vs planned; retried (built on a second or third attempt); deferred (failed 3 times)
  critic score        tests/design_bench/bench.py score of the final design (heuristic), unless --no-score
  mesh-tier features  features of the final source that declare a mesh texture (MeshTexture)
  total seconds       the brief from its first call to its last
Kernel workers: FORM_KERNEL_WORKERS (default 2 here). Every number written is measured in this run; nothing is
estimated. Nothing is printed or uploaded.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _briefs() -> list[dict]:
    return json.loads((ROOT / "tests" / "design_bench" / "creation_briefs.json").read_text(encoding="utf-8"))["briefs"]


def _bench():
    spec = importlib.util.spec_from_file_location("design_bench", ROOT / "tests" / "design_bench" / "bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _activity(data: Path) -> list[dict]:
    f = data / ".activity.jsonl"
    out = []
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _score(bench, b: dict, source: str, tmp: Path) -> dict:
    f = tmp / f"final_{b['id']}.py"
    f.write_text(source, encoding="utf-8")
    try:
        recipe = bench._load(f)
    except Exception as e:
        return {"total": 0, "status": f"does not load: {type(e).__name__}: {e}"[:200]}
    m = bench.check(recipe, f"creation-{b['id']}", bench.product_class(b))
    r = bench.score(b, m)
    return {"total": r["total"], "status": r["status"], "points": r["points"], "notes": r["notes"][:6],
            "builds": not m.get("error") and bool(m.get("valid"))}


async def _run(only: set | None, score: bool, workers: int) -> dict:
    from mcp import Client, StdioServerParameters
    from form import featureprog
    from tests.fixtures.scripted_agent import S, ScriptedAgent
    briefs = [b for b in _briefs() if not only or b["id"] in only]
    for b in briefs:
        if S[b["id"]]["brief"] != b["brief"]:
            raise SystemExit(f"{b['id']}: the scripted agent's brief differs from creation_briefs.json")
    bench = _bench() if score else None
    data = Path(tempfile.mkdtemp(prefix="form-creation-bench-"))
    env = {**os.environ, "FORM_DATA": str(data), "PYTHONPATH": str(ROOT), "FORM_SKIP_UI": "1",
           "FORM_KERNEL_WORKERS": str(workers)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env,
                                   cwd=str(ROOT))
    out = {"agent": "scripted (deterministic stub, no model)", "workers": workers, "form_data": str(data),
           "started": time.strftime("%Y-%m-%d %H:%M:%S"), "briefs": []}
    async with Client(params) as c:
        async def call(tool, args):
            res = await c.call_tool(tool, args)
            text = next((x.text for x in res.content if getattr(x, "type", "") == "text"), "")
            if res.is_error:
                return False, {"text": text}
            try:
                return True, json.loads(text)
            except ValueError:
                return True, {"text": text}
        t0 = time.time()                                    # warm the kernel workers (not timed per brief)
        await call("form_overview", {})
        warm = await call("create_design", {"name": "Warm-up block", "run": False, "purpose": "model",
                                            "source": "from build123d import Box\nfrom form.recipes.base import Feature, "
                                            "Param, Recipe, Stage\n\nclass Design(Recipe):\n    title = 'Warm-up'\n"
                                            "    params = [Param('w', 'W', 10, 5, 20, 1, 'mm', 'form', 'b')]\n"
                                            "    features = [Feature('b', 'Block', 'structure')]\n\n"
                                            "    def build(self, v):\n        return [Stage('b', Box(v['w'], 10, 10))]\n"})
        out["warm_up_s"] = round(time.time() - t0, 2)
        out["warm_up_ok"] = warm[0]
        agent = ScriptedAgent(call)
        for b in briefs:
            rec = await agent.run(b["id"])
            stages = [e for e in _activity(data) if e.get("kind") == "stage" and rec["t0"] <= e.get("ts", 0) <= rec["end"]]
            src = rec.get("final_source") or ""
            row = {"id": b["id"], "category": b["category"], "route": rec.get("route"), "plan_ok": rec.get("plan_ok"),
                   "project": rec["project"], "first_build_ok": rec.get("first_build_ok", False),
                   "first_visible_s": round(stages[0]["ts"] - rec["t0"], 3) if stages else None,
                   "skeleton_returned_s": rec.get("skeleton_returned_s"),
                   "features_planned": rec["planned"], "features_built": len(rec["built"]),
                   "retried": rec["retried"], "deferred": rec["deferred"],
                   "mesh_tier_features": src.count("MeshTexture("),
                   "final_build_ok": bool(rec["project"] and src and featureprog.P_START not in src),
                   "total_s": round(rec["end"] - rec["t0"], 2),
                   "calls": [{k: x[k] for k in ("tool", "ok", "s", "feature", "error") if k in x} for x in rec["calls"]]}
            if bench and src:
                row["critic"] = _score(bench, b, src, data)
                row["final_build_ok"] = row["final_build_ok"] and bool(row["critic"].get("builds"))
            out["briefs"].append(row)
            print(f"{b['id']:20s} first={'ok' if row['first_build_ok'] else 'NO':3s} final={'ok' if row['final_build_ok'] else 'NO':3s} "
                  f"visible={row['first_visible_s']}s built={row['features_built']}/{row['features_planned']} "
                  f"deferred={len(row['deferred'])} critic={(row.get('critic') or {}).get('total', '-')} total={row['total_s']}s",
                  flush=True)
    rows = out["briefs"]
    n = max(1, len(rows))
    vis = [r["first_visible_s"] for r in rows if r["first_visible_s"] is not None]
    crit = [r["critic"]["total"] for r in rows if r.get("critic")]
    out["summary"] = {
        "briefs": len(rows),
        "first_build_ok_pct": round(100 * sum(r["first_build_ok"] for r in rows) / n, 1),
        "final_build_ok_pct": round(100 * sum(r["final_build_ok"] for r in rows) / n, 1),
        "first_visible_s": {"median": round(statistics.median(vis), 2) if vis else None,
                            "max": round(max(vis), 2) if vis else None, "within_20s": sum(1 for x in vis if x <= 20)},
        "features_built": sum(r["features_built"] for r in rows), "features_planned": sum(r["features_planned"] for r in rows),
        "retried": sum(len(r["retried"]) for r in rows), "deferred": sum(len(r["deferred"]) for r in rows),
        "mesh_tier_features": sum(r["mesh_tier_features"] for r in rows),
        "critic_score_mean": round(statistics.mean(crit), 1) if crit else None,
        "total_s": round(sum(r["total_s"] for r in rows), 1),
        "without_project": [r["id"] for r in rows if not r["project"]],
        "evidence": "measured in this run; critic scores are the design bench's heuristic"}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--no-score", action="store_true", help="skip the critic score (no OCCT build in this process)")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("FORM_KERNEL_WORKERS") or 2))
    a = ap.parse_args(argv)
    res = asyncio.run(_run(set(a.only.split(",")) if a.only else None, not a.no_score, a.workers))
    print(json.dumps(res["summary"], indent=1))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
