"""Creation bench: the briefs of tests/design_bench/creation_briefs.json run through Form Studio's MCP tools
(a real MCP stdio server, a temporary FORM_DATA), skeleton first and one feature per call, and measured.

    .venv/bin/python scripts/creation_bench.py --json bench.json                 # the scripted stub agent, all 20
    .venv/bin/python scripts/creation_bench.py --only hero_helmet,din_clip --no-score
    .venv/bin/python scripts/creation_bench.py --refine off --json off.json        # refinement off (FORM_REFINE=off)
    .venv/bin/python scripts/creation_bench.py --compare on.json off.json --doc docs/CREATION_BENCH.md

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
  refused / partial   design calls refused (no revision made) vs calls that saved a partial revision with a feature
                      left out (a revision waiting only for parts still to come is neither)
  hangs               design calls during which the kernel timed out or crashed, and of those how many still had
                      the project afterwards (get_project), with the feature and the seconds it ran
  checkpoint hits     features loaded from their checkpoint / features loaded or built, over every build_log
  parts               the declared and built part count of the last revision that reported it
  total seconds       the brief from its first call to its last
  refinement          (--refine on, the default) the background refinement after the last call, waited for with
                      refine_design(action="status", wait=...): its state, wall seconds, kept changes, and the final
                      source scored is the refined head
  function checks     the checks of the final design (form/checks.py, purpose model: solid, interfaces, mesh, STL vs
                      CAD, size, walls, statics), run in this process after the MCP session on the same data folder
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


DESIGN_CALLS = ("create_design", "update_design", "add_feature")


def _rate(a: int, n: int):
    return round(a / n, 3) if n else None


def _call_metrics(calls: list) -> dict:
    """Refused vs partial revisions, hangs (and whether the project survived them), checkpoint hits."""
    design = [c for c in calls if c["tool"] in DESIGN_CALLS]
    hits = sum((c.get("log") or {}).get("checkpoint", 0) for c in design)
    built = sum((c.get("log") or {}).get("built", 0) for c in design)
    parts = next((c["parts"] for c in reversed(design) if c.get("parts")), None)
    return {"refused": sum(1 for c in design if not c["ok"]),
            "partial_revisions": sum(1 for c in design if c["ok"] and c.get("left_out")),
            "hangs": [{**c["hang"], "tool": c["tool"]} for c in design if c.get("hang")],
            "checkpoint_hits": hits, "features_rebuilt": built, "checkpoint_hit_rate": _rate(hits, hits + built),
            **({"parts": parts} if parts else {})}


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


def _function_checks(data: Path, rows: list) -> None:
    """The final design's check rows {id: status}, per brief (geometry, exports and checks run here)."""
    os.environ["FORM_DATA"] = str(data)
    os.environ["FORM_REFINE"] = "off"                       # reading the designs must not refine them again
    from form import config
    from form.studio import Studio
    st = Studio(config.load())
    try:
        for r in rows:
            if not r.get("project"):
                continue
            try:
                j = st.run_sync(r["project"], ["geometry", "exports", "checks"])
                p = st.load(r["project"])
                got = st.read(p, "checks", st.keys(p)["checks"]) or {}
                r["checks"] = {c["id"]: c["status"] for c in got.get("checks") or []}
                r["checks_state"] = j["state"]
            except Exception as e:                           # noqa: BLE001 - a failure is a result
                r["checks"] = None
                r["checks_state"] = f"{type(e).__name__}: {e}"[:200]
    finally:
        st.kernel.stop()


async def _run(only: set | None, score: bool, workers: int, refine: str = "on", wait: float = 240.0) -> dict:
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
           "FORM_KERNEL_WORKERS": str(workers), "FORM_REFINE_LOCAL": "1", "FORM_REFINE": refine}
    params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env,
                                   cwd=str(ROOT))
    out = {"agent": "scripted (deterministic stub, no model)", "workers": workers, "form_data": str(data),
           "refine": refine, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "briefs": []}
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
            if refine == "on" and rec.get("project"):         # the refinement after the last call, then its head
                t_r = time.time()
                ok_r, rs = await call("refine_design", {"project": rec["project"], "action": "status", "wait": wait})
                rs = rs if ok_r and isinstance(rs, dict) else {}
                rec["refine"] = {"state": rs.get("state"), "waited_s": round(time.time() - t_r, 2),
                                 "seconds": rs.get("seconds"), "budget_s": rs.get("budget_s"),
                                 "stopped": rs.get("stopped") or rs.get("why"), "base": rs.get("base"),
                                 "final": rs.get("final"), "head": rs.get("head"), "style": rs.get("style"),
                                 "applied": [a.get("label") for a in rs.get("applied") or []],
                                 "rejected": rs.get("rejected") or [], "measure": rs.get("measure"),
                                 "error": rs.get("error") or rs.get("commit_error")}
                ok_s, src2 = await call("get_design_source", {"project": rec["project"]})
                if ok_s and isinstance(src2, dict) and src2.get("source"):
                    rec["final_source"] = src2["source"]
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
                   "total_s": round(rec["end"] - rec["t0"], 2), "refine": rec.get("refine"),
                   **_call_metrics(rec["calls"]),
                   "calls": [{k: x[k] for k in ("tool", "ok", "s", "feature", "error", "partial", "left_out", "hang",
                                                "parts", "log") if k in x} for x in rec["calls"]]}
            if bench and src:
                row["critic"] = _score(bench, b, src, data)
                row["final_build_ok"] = row["final_build_ok"] and bool(row["critic"].get("builds"))
            out["briefs"].append(row)
            print(f"{b['id']:20s} first={'ok' if row['first_build_ok'] else 'NO':3s} final={'ok' if row['final_build_ok'] else 'NO':3s} "
                  f"visible={row['first_visible_s']}s built={row['features_built']}/{row['features_planned']} "
                  f"deferred={len(row['deferred'])} refused={row['refused']} partial={row['partial_revisions']} "
                  f"hangs={len(row['hangs'])} ckpt={row['checkpoint_hit_rate']} "
                  f"critic={(row.get('critic') or {}).get('total', '-')} total={row['total_s']}s",
                  flush=True)
    rows = out["briefs"]
    _function_checks(data, rows)
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
        "refused": sum(r["refused"] for r in rows), "partial_revisions": sum(r["partial_revisions"] for r in rows),
        "hangs": sum(len(r["hangs"]) for r in rows),
        "hangs_with_project": sum(1 for r in rows for h in r["hangs"] if h.get("project_exists")),
        "checkpoint_hit_rate": _rate(sum(r["checkpoint_hits"] for r in rows),
                                     sum(r["checkpoint_hits"] + r["features_rebuilt"] for r in rows)),
        "evidence": "measured in this run; critic scores are the design bench's heuristic"}
    rr = [r["refine"] for r in rows if r.get("refine")]
    if rr:
        secs = [x["seconds"] for x in rr if isinstance(x.get("seconds"), (int, float))]
        out["summary"]["refine"] = {
            "refined": sum(1 for x in rr if x.get("applied")), "of": len(rr),
            "changes": sum(len(x.get("applied") or []) for x in rr),
            "states": {k: sum(1 for x in rr if x.get("state") == k) for k in sorted({x.get("state") for x in rr})},
            "seconds_median": round(statistics.median(secs), 2) if secs else None,
            "seconds_max": round(max(secs), 2) if secs else None,
            "within_budget": sum(1 for x in rr if isinstance(x.get("seconds"), (int, float))
                                 and isinstance(x.get("budget_s"), (int, float)) and x["seconds"] <= x["budget_s"])}
    return out


def compare(on: dict, off: dict) -> dict:
    """The gates of the refinement plan, from an --refine on and an --refine off run of the same briefs."""
    a = {r["id"]: r for r in on["briefs"]}
    b = {r["id"]: r for r in off["briefs"]}
    ids = [i for i in a if i in b]
    rows = []
    for i in ids:
        x, y = a[i], b[i]
        cx, cy = (x.get("critic") or {}).get("total"), (y.get("critic") or {}).get("total")
        rows.append({"id": i, "critic_on": cx, "critic_off": cy,
                     "gain": round(cx - cy, 2) if isinstance(cx, (int, float)) and isinstance(cy, (int, float)) else None,
                     "checks_same": x.get("checks") == y.get("checks") and x.get("checks") is not None,
                     "checks_on": x.get("checks"), "checks_off": y.get("checks"),
                     "visible_on": x.get("first_visible_s"), "visible_off": y.get("first_visible_s"),
                     "refine": x.get("refine")})
    gains = [r["gain"] for r in rows if r["gain"] is not None]
    von = [r["visible_on"] for r in rows if r["visible_on"] is not None]
    voff = [r["visible_off"] for r in rows if r["visible_off"] is not None]
    mvon, mvoff = (round(statistics.median(von), 4) if von else None), (round(statistics.median(voff), 4) if voff else None)
    g = {"checks_identical": all(r["checks_same"] for r in rows),
         "mean_gain": round(statistics.mean(gains), 2) if gains else None,
         "no_brief_lower": all(x >= 0 for x in gains) if gains else False,
         "first_visible_median_on": mvon, "first_visible_median_off": mvoff,
         "first_visible_within_5pct": bool(mvon is not None and mvoff and mvon <= 1.05 * mvoff)}
    g["mean_gain_ok"] = g["mean_gain"] is not None and g["mean_gain"] >= 0.5
    return {"rows": rows, "gates": g}


def write_doc(on: dict, off: dict, path: Path) -> None:
    c = compare(on, off)
    g = c["gates"]
    L = ["# Creation bench: refinement on and off", "",
         f"The {len(c['rows'])} creation briefs (tests/design_bench/creation_briefs.json) run twice through the MCP "
         "server by the scripted agent (tests/fixtures/scripted_agent.py, deterministic, no model): once with design "
         "refinement on (the default: it runs in the background after every build and the bench waits for the last "
         "one), once with FORM_REFINE=off. "
         f"On: {on.get('started')}, off: {off.get('started')}, {on.get('workers')} kernel workers. Every number is "
         "measured in these runs; the critic score is the design bench's heuristic (tests/design_bench/bench.py), "
         "not a person's judgement.", "",
         "## Gates", "",
         f"- Function checks identical on and off: **{'pass' if g['checks_identical'] else 'FAIL'}**",
         f"- Mean critic gain >= 0.5: **{'pass' if g['mean_gain_ok'] else 'FAIL'}** (mean {g['mean_gain']})",
         f"- No brief lower: **{'pass' if g['no_brief_lower'] else 'FAIL'}**",
         f"- First visible within 5 % of off: **{'pass' if g['first_visible_within_5pct'] else 'FAIL'}** (median "
         f"{g['first_visible_median_on']} s on, {g['first_visible_median_off']} s off)", "",
         "## Per brief", "",
         "| Brief | Critic off | Critic on | Gain | Checks same | First visible off / on (s) | Refinement | Changes kept |",
         "|---|---|---|---|---|---|---|---|"]
    for r in c["rows"]:
        rf = r.get("refine") or {}
        L.append("| " + " | ".join([
            r["id"], str(r["critic_off"]), str(r["critic_on"]), "—" if r["gain"] is None else f"{r['gain']:+.1f}",
            "yes" if r["checks_same"] else "**no**",
            f"{r['visible_off']} / {r['visible_on']}",
            f"{rf.get('state')} {rf.get('seconds')} s" + (f" ({rf.get('stopped')})" if rf.get("stopped") else ""),
            ", ".join(rf.get("applied") or []) or "none"]) + " |")
    diff = [r for r in c["rows"] if not r["checks_same"]]
    if diff:
        L += ["", "## Check differences", ""]
        for r in diff:
            on_, off_ = r["checks_on"] or {}, r["checks_off"] or {}
            ks = sorted(set(on_) | set(off_))
            L.append(f"- {r['id']}: " + ", ".join(f"{k} {off_.get(k)} → {on_.get(k)}" for k in ks
                                                  if on_.get(k) != off_.get(k)))
    so, sf = on.get("summary") or {}, off.get("summary") or {}
    L += ["", "## Totals", "",
          f"- Final build ok: {sf.get('final_build_ok_pct')} % off, {so.get('final_build_ok_pct')} % on.",
          f"- Critic mean: {sf.get('critic_score_mean')} off, {so.get('critic_score_mean')} on.",
          f"- Refinement: {json.dumps(so.get('refine'))}.",
          f"- Total seconds: {sf.get('total_s')} off, {so.get('total_s')} on.", "",
          "## Reading it", "",
          "- The critic is the design bench's score out of 100 (staging, builds, features, craft, form, integrity, "
          "and a product class's silhouette). Refinement can move only some of it: craft (rounds present, sharp-edge "
          "share under 0.6), integrity (it must not fold a skin or thin a wall) and the class silhouette. Material "
          "zones change the deficit vector the engine searches on but no critic item, so most briefs keep their score.",
          "- First visible is the time from the brief's first call to the first stage the kernel reports: the "
          "skeleton, built before any refinement starts. The difference on and off is a few milliseconds.",
          f"- Refinement time: {(so.get('refine') or {}).get('within_budget')} of {(so.get('refine') or {}).get('of')} "
          "jobs within their budget (20 s for CAD, the final exported-mesh check included); the median and the "
          "longest are in the Refinement line above.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--no-score", action="store_true", help="skip the critic score (no OCCT build in this process)")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("FORM_KERNEL_WORKERS") or 2))
    ap.add_argument("--refine", choices=("on", "off"), default="on", help="design refinement after every build")
    ap.add_argument("--wait", type=float, default=240.0, help="seconds to wait for the last refinement of a brief")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("ON_JSON", "OFF_JSON"), help="the gates of two runs")
    ap.add_argument("--doc", type=Path, help="with --compare: write the on/off report here")
    a = ap.parse_args(argv)
    if a.compare:
        on, off = (json.loads(x.read_text(encoding="utf-8")) for x in a.compare)
        print(json.dumps(compare(on, off)["gates"], indent=1))
        if a.doc:
            write_doc(on, off, a.doc)
        return 0
    res = asyncio.run(_run(set(a.only.split(",")) if a.only else None, not a.no_score, a.workers, a.refine, a.wait))
    print(json.dumps(res["summary"], indent=1))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
