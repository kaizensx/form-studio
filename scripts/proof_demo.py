"""The proof-carrying build in one minute, over real MCP stdio, with a scripted stand-in for the agent.

    .venv/bin/python scripts/proof_demo.py [--json out.json]

No model runs here: the "agent" is this script, calling the same tools an agent calls, in a temporary data folder.

  1. design_brief with a trap: a Ø68 flange, 4 x Ø5.2 on a 60 mm bolt circle, 2.4 mm walls. The audit finds, by
     arithmetic and before any code, that the wall between a hole and the edge would be 1.4 mm.
  2. design_brief again with the outside diameter the audit asked for (Ø70).
  3. create_design from a plain Recipe whose holes are Ø5.0, not Ø5.2: it builds, and the proof sheet has a red
     row at the feature that owes the holes, measured against wanted.
  4. edit_design with one op (set_param): the Recipe is lifted into feature methods, built once, and the sheet is green.
  5. edit_design on the last feature: only that feature is built again.

Every number printed is what the tools returned.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE = '''from build123d import Align, Axis, Cylinder, PolarLocations, chamfer
from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Bolted flange"
    summary = "A round flange with a centre bore and a bolt circle."
    params = [
        Param("outer_d", "Outside diameter", 70, 40, 120, 0.5, "mm", "brief", "disc"),
        Param("t", "Thickness", 8, 3, 20, 0.5, "mm", "form", "disc"),
        Param("bore_d", "Centre bore", 20, 5, 40, 0.5, "mm", "interface", "bore"),
        Param("circle_d", "Bolt circle", 60, 20, 110, 0.5, "mm", "interface", "holes"),
        Param("hole_d", "Bolt hole", 5.0, 2, 10, 0.1, "mm", "interface", "holes"),
        Param("n", "Bolt holes", 4, 2, 12, 1, "", "interface", "holes"),
        Param("edge", "Edge chamfer", 0.6, 0.2, 2, 0.1, "mm", "form", "edges"),
    ]
    features = [Feature("disc", "Disc", "structure"), Feature("bore", "Centre bore", "interface"),
                Feature("holes", "Bolt holes", "interface"), Feature("edges", "Edge chamfer", "finish")]

    def constraints(self, v):
        return []

    def build(self, v):
        body = Cylinder(v["outer_d"] / 2, v["t"], align=A)
        st = [Stage("disc", body)]
        body = body - Cylinder(v["bore_d"] / 2, v["t"], align=A)
        st.append(Stage("bore", body))
        for loc in PolarLocations(v["circle_d"] / 2, int(v["n"])):
            body = body - loc * Cylinder(v["hole_d"] / 2, v["t"], align=A)
        st.append(Stage("holes", body))
        rim = body.edges().filter_by(lambda e: abs(e.radius - v["outer_d"] / 2) < 1e-6 if e.geom_type.name == "CIRCLE" else False)
        body = chamfer(rim, v["edge"])
        st.append(Stage("edges", body))
        return st
'''


def data(res):
    if res.structured_content is not None:
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(next(c.text for c in res.content if getattr(c, "type", "") == "text"))


def sheet(proof) -> str:
    if not proof:
        return "  (no proof sheet)"
    rows = [f"  {r['status']:<8} {r['requirement']:<44} measured {str(r['measured']):<34} {r['tolerance']:<10} "
            f"{r['evidence']:<9} {r.get('feature', '')}" for r in proof["rows"]]
    return "\n".join(rows + [f"  => {proof['summary']}" + (" - GREEN" if proof["green"] else "")])


async def run(out: dict) -> None:
    from mcp import Client, StdioServerParameters
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
        params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env,
                                       cwd=str(ROOT))
        async with Client(params) as c:
            async def call(name, args):
                t = time.time()
                res = await c.call_tool(name, args)
                sent = len(json.dumps(args))
                step = {"tool": name, "input_chars": sent, "s": round(time.time() - t, 2), "error": bool(res.is_error)}
                out["steps"].append(step)
                if res.is_error:
                    step["text"] = next(x.text for x in res.content if getattr(x, "type", "") == "text")
                    return step["text"]
                return data(res)
            print("1. The brief, with a trap")
            brief = {"name": "Bolted flange", "goal": "A flange Ø68 with a Ø20 bore, 4 x Ø5.2 on a 60 mm bolt circle "
                     "and 2.4 mm walls, 8 mm thick.", "purpose": "model"}
            b = await call("design_brief", brief)
            au = b["contract"]["audit"]
            print("   contract:", "; ".join(a["text"] for a in b["contract"]["assertions"]))
            print("   audit   :", au.get("ask") or "nothing to settle")
            out["audit_trap"] = au
            out["brief_goal"] = brief["goal"]
            out["contract_trap"] = [x["text"] for x in b["contract"]["assertions"]]
            refused = await call("create_design", {"name": "Bolted flange", "source": SOURCE, "plan": b["brief"],
                                                   "run": False})
            print("   building from it is refused:", str(refused).splitlines()[0][:110])
            print("2. The brief, corrected to the outside diameter the audit computed")
            brief["goal"] = brief["goal"].replace("Ø68", "Ø70")
            b = await call("design_brief", brief)
            print("   audit   :", b["contract"]["audit"].get("ask") or "nothing to settle")
            plan = await call("plan_design", {"brief": b["brief"], "features": [
                {"id": "disc", "label": "Disc", "how": "Cylinder"}, {"id": "bore", "label": "Centre bore", "how": "cut"},
                {"id": "holes", "label": "Bolt holes", "how": "PolarLocations cut"},
                {"id": "edges", "label": "Edge chamfer", "how": "chamfer"}], "risks": ["holes too close to the edge"]})
            assert isinstance(plan, dict), plan
            print("3. create_design: a plain Recipe, holes Ø5.0 where the brief says Ø5.2")
            r = await call("create_design", {"name": "Bolted flange", "source": SOURCE, "plan": b["brief"],
                                             "purpose": "model", "run": False, "refine": "off"})
            assert isinstance(r, dict), r
            pid = r["project"]
            print(sheet(r.get("proof")))
            out["first"] = r.get("proof")
            red = [x for x in r["proof"]["rows"] if x["status"] == "FAIL"]
            print("4. edit_design: one op repairs the red row")
            e = await call("edit_design", {"project": pid, "expect_head": r["head"], "look": False, "run": False,
                                           "ops": [{"op": "set_param", "param": "hole_d", "default": 5.2}]})
            assert isinstance(e, dict), e
            out["repair_op"] = {"op": "set_param", "param": "hole_d", "default": 5.2}
            print("   canonical form:", e.get("canonical"), "| built:", [(x["feature"], x["status"]) for x in e["changed"]],
                  "| reused:", e["reused"])
            print(sheet(e.get("proof")))
            out["repaired"] = e.get("proof")
            out["repair_edit"] = {k: e[k] for k in ("changed", "reused", "canonical") if k in e}
            print("5. edit_design on the last feature: only it is built")
            e2 = await call("edit_design", {"project": pid, "expect_head": e["head"], "look": False, "run": False,
                                            "ops": [{"op": "set_param", "param": "edge", "value": 1.0}]})
            assert isinstance(e2, dict), e2
            print("   built:", [(x["feature"], x["status"], x["s"]) for x in e2["changed"]], "| reused:", e2["reused"])
            print(sheet(e2.get("proof")))
            out["last_feature_edit"] = {k: e2[k] for k in ("changed", "reused") if k in e2}
            src = await call("get_design_source", {"project": pid, "feature": "edges"})
            print("   get_design_source(feature='edges') returns", len(src["source"]), "characters, not the file")
            out["red_rows_first"] = len(red)


def main(argv=None) -> int:
    out: dict = {"steps": []}
    t = time.time()
    asyncio.run(run(out))
    out["wall_s"] = round(time.time() - t, 1)
    print(f"done in {out['wall_s']} s; tool input characters per step:",
          [(s["tool"], s["input_chars"]) for s in out["steps"]])
    args = argv if argv is not None else sys.argv[1:]
    if "--json" in args:
        Path(args[args.index("--json") + 1]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
