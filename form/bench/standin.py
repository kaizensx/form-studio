"""The bench's stand-in agent: deterministic, no model, no network. It proves the harness, never a score.

    python standin.py --mcp '<json>' --cwd <trial folder> --freecad <freecadcmd> <prompt>

It speaks Claude Code's stream-json (what form/agents/claude.py parses), and does the same kind of work a real agent
does through the same doors:

1. starts Form Studio's MCP server from --mcp (the command, arguments and environment the harness gives every agent)
   and calls form_overview and create_design with a block of the prompt's three largest millimetre values;
2. writes answer.py: a FreeCAD PartDesign Body with one sketch and one Pad of that block, saving the FCStd file(s)
   the task names next to the script (answer.FCStd, or answer_base.FCStd and answer_edit.FCStd);
3. runs answer.py with FreeCAD's command line.

The block is the same for every task of one prompt, so a run scores low, and the same every time.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ANSWER = '''# Written by the bench's stand-in agent (deterministic, no model): one PartDesign Pad of a block.
import os

import FreeCAD as App
import Part
import Sketcher

X, Y, Z = {x!r}, {y!r}, {z!r}


def block(path):
    doc = App.newDocument("answer")
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    sketch = body.newObject("Sketcher::SketchObject", "BlockSketch")
    sketch.AttachmentSupport = [(xy, "")]
    sketch.MapMode = "FlatFace"
    p = [App.Vector(-X / 2, -Y / 2, 0), App.Vector(X / 2, -Y / 2, 0), App.Vector(X / 2, Y / 2, 0), App.Vector(-X / 2, Y / 2, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]), False)
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Length = Z
    doc.recompute()
    doc.saveAs(path)
    App.closeDocument(doc.Name)


here = os.path.dirname(os.path.abspath(__file__))
stem = os.path.splitext(os.path.basename(__file__))[0]
for suffix in {suffixes!r}:
    block(os.path.join(here, stem + suffix + ".FCStd"))
'''

DESIGN = '''from build123d import Align, Box

from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Bench stand-in block"
    params = [Param("x", "X", {x!r}, 0.1, 5000, 0.1, "mm", "brief", "body"),
              Param("y", "Y", {y!r}, 0.1, 5000, 0.1, "mm", "brief", "body"),
              Param("z", "Z", {z!r}, 0.1, 5000, 0.1, "mm", "brief", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["x"], v["y"], v["z"], align=(Align.CENTER, Align.CENTER, Align.MIN)))]
'''


def out(obj) -> None:
    print(json.dumps(obj), flush=True)


def dims(prompt: str) -> tuple[float, float, float]:
    vals = sorted({float(m) for m in re.findall(r"=\s*([0-9]+(?:\.[0-9]+)?)\s*mm", prompt)}, reverse=True)
    vals = [v for v in vals if v > 0][:3]
    while len(vals) < 3:
        vals.append(20.0 if not vals else min(vals))
    return vals[0], vals[1], vals[2]


class MCP:
    """A minimal MCP client over stdio (newline-delimited JSON-RPC)."""

    def __init__(self, spec: dict, cwd: str):
        import os
        env = {**os.environ, **(spec.get("env") or {})}
        self.p = subprocess.Popen([spec["command"], *spec.get("args", [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd)
        self.n = 0
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "form-bench-standin", "version": "1"}})
        self.notify("notifications/initialized")

    def notify(self, method: str, params: dict | None = None) -> None:
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("the MCP server closed its output")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result") or {}

    def call(self, name: str, args: dict) -> str:
        res = self.request("tools/call", {"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content") or [] if c.get("type") == "text")
        return ("ERROR: " if res.get("isError") else "") + text

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:                                   # noqa: BLE001
            self.p.kill()


def tool(i: int, name: str, args: dict, result: str) -> None:
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"s{i}", "name": name, "input": args}]}})
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"s{i}",
                                                  "content": [{"type": "text", "text": result[:4000]}]}]}})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--freecad", default="")
    ap.add_argument("prompt")
    a = ap.parse_args(argv)
    sid = "standin-" + uuid.uuid4().hex[:8]
    out({"type": "system", "subtype": "init", "session_id": sid, "model": "standin"})
    cwd = Path(a.cwd)
    x, y, z = dims(a.prompt)
    i = 0
    try:
        mcp = MCP(json.loads(a.mcp), str(cwd))
        try:
            i += 1
            tool(i, "mcp__form__form_overview", {}, mcp.call("form_overview", {}))
            args = {"name": "Bench block", "source": DESIGN.format(x=x, y=y, z=z), "purpose": "model", "refine": "off",
                    "run": False}
            i += 1
            tool(i, "mcp__form__create_design", {"name": args["name"], "purpose": "model"}, mcp.call("create_design", args))
        finally:
            mcp.close()
    except Exception as e:                                  # noqa: BLE001 - reported, the FreeCAD answer is still written
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Form Studio's MCP server: {e}"}]}})
    suffixes = ["_base", "_edit"] if "_base.FCStd" in a.prompt else [""]
    script = cwd / "answer.py"
    script.write_text(ANSWER.format(x=x, y=y, z=z, suffixes=suffixes), encoding="utf-8")
    i += 1
    tool(i, "Write", {"file_path": str(script)}, "written")
    if a.freecad:
        r = subprocess.run([a.freecad, "-c", f"import runpy; runpy.run_path({str(script)!r}, run_name='__main__')"],
                           capture_output=True, text=True, timeout=600, cwd=str(cwd))
        i += 1
        tool(i, "Bash", {"command": "freecadcmd answer.py"}, f"exit {r.returncode}\n{(r.stdout + r.stderr)[-1500:]}")
    made = sorted(p.name for p in cwd.glob("answer*.FCStd"))
    out({"type": "assistant", "message": {"content": [{"type": "text", "text":
        f"Stand-in answer: a {x:g} x {y:g} x {z:g} mm block; wrote {', '.join(made) or 'no FCStd'}."}]}})
    out({"type": "result", "total_cost_usd": 0.0, "num_turns": i, "session_id": sid})
    return 0


if __name__ == "__main__":
    sys.exit(main())
