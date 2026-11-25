"""A stand-in for an agent CLI, for tests. Speaks Claude Code's stream-json. No model, no network.

    fake_agent.py <data_dir> <session-or-"-"> <model> <message>

Behaviour is chosen by words in the message: "slow" waits until terminated; "make" creates a project folder and
reports it from a create_project tool; "render" reports a render PNG; "outline" answers in Markdown (lists, code, a table); "boom" exits 1. A session id that starts with
"gone" is refused the way a CLI refuses a session it no longer has. "ask" asks a question the way Form Studio's ask_user
tool does (the same files, form/ask.py; the word "ask" in the first line; "approve" makes it an approval card, "words" a question without choices) and
waits for the answer; "suggest" offers follow-ups through suggest_replies.

Home's start flow (form/start.py, form/concepts.py), by words in the FIRST line of the message:
  "concepts"  builds a real concept group of three tiny designs (Block, Disc, Bracket) with form.concepts.create, reports
              it as a propose_concepts tool call, and adds the line "Concepts: A Block, B Disc, C Bracket".
              The designs get the purpose of the message's "Purpose:" line. With "look" in that line too, it then
              looks at concept B the way render does (a "look" in the activity log, a moment later).
  "measure"   asks a measurement question (kind "measure", the files of form/ask.py) about the newest project's first
              parameter: where "Across the widest part, side to side", tolerance 0.1 mm, diagram box/x, current = its value.
              After the answer the reply has "You measured: <value> mm with <method>" (value as %g), or
              "You measured: nothing (<reason>)" when the question closed unanswered.
  "Replace a broken part: <name>."  (form/replace.py) creates a tiny Block design named <name> (create_design), adds
              "Replacement: <name>", then asks the measurement question above about it.
The end-of-run gate (form/chat.py, form/verdict.py), by words in the FIRST line:
  "failcheck"  reports a get_project result whose checks FAIL (Thinnest wall: 0.00 mm) for project "wall-test" and
               ends with "Designed." (FAIL not reported). With "ack" it says the wall check fails instead. With
               "stubborn" the project is "wall-stubborn" and every reply, the gate's continuation too, ignores it.
               The gate's continuation (a message naming "wall-test") gets "The Thinnest wall check FAILS at 0.00 mm."
Cost: total_cost_usd is the session's running total, as Claude Code reports it for a resumed session.
Always, from the prompt Form Studio builds:
  "Attached files:" present   -> a line "I received: <name> (<kind>), ..." (file names without the 6-hex id and dash)
  the sketch heading present  -> a line "Sketch: <n> primitives" per sketch, counted from the inlined JSON
  a line starting "Purpose:"  -> that line, verbatim
Extra lines follow "You said: <first line>" in that order, each after a blank line.
"""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path


def out(obj):
    print(json.dumps(obj), flush=True)


def session_total(data: Path, sid: str, spent: float) -> float:
    """The session's running total after this run (Claude Code restores it when a run resumes the session)."""
    f = data / ".fake-sessions" / (re.sub(r"[^A-Za-z0-9_-]", "_", sid) + ".json")
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        before = json.loads(f.read_text())["total"]
    except (OSError, ValueError, KeyError):
        before = 0.0
    total = round(before + spent, 6)
    f.write_text(json.dumps({"total": total}))
    return total


FAIL_DIGEST = {"verdict": "FAIL", "blocking": ["Thinnest wall: 0.00 mm [computed]"], "project": "wall-test", "head": 1,
               "checks": ["PASS  One valid solid: 1 solid  [computed]", "FAIL  Thinnest wall: 0.00 mm  [computed]"]}


def failcheck(data: Path, message: str, sid: str) -> int:
    first = message.splitlines()[0]
    gate = message.startswith("Form Studio check before this reply ends")
    stubborn = "stubborn" in first or "wall-stubborn" in message
    if not gate or stubborn:
        d = dict(FAIL_DIGEST, project="wall-stubborn" if stubborn else "wall-test")
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "g1", "name": "mcp__form__get_project",
                                                           "input": {"project": d["project"]}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "g1", "content": [
            {"type": "text", "text": json.dumps(d)}]}]}})
    if gate and not stubborn:
        reply = "The Thinnest wall check FAILS at 0.00 mm: the wall is missing where the arm meets the clamp."
    elif re.search(r"\back\b", first):
        reply = "Made it, but the wall check fails: 0.00 mm at the clamp."
    else:
        reply = "Designed."
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "total_cost_usd": session_total(data, sid, 0.4), "num_turns": 2, "session_id": sid})
    return 0


def main():
    data, session, model, message = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    if session.startswith("gone"):
        print("No conversation found with session ID: " + session, file=sys.stderr)
        return 1
    sid = session if session != "-" else "sess-" + uuid.uuid4().hex[:8]
    out({"type": "system", "subtype": "init", "session_id": sid, "model": "fake-" + model + "-1"})
    if "boom" in message:
        print("the fake agent fell over", file=sys.stderr)
        return 1
    if "slow" in message:
        out({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}})
        out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Working"}}})
        time.sleep(60)
        return 0
    first0 = message.splitlines()[0] if message.strip() else ""
    if re.search(r"\bfailcheck\b", first0) or message.startswith("Form Studio check before this reply ends"):
        return failcheck(data, message, sid)
    if re.search(r"\beditable\b", first0):
        return editable(data, message, sid)
    if re.search(r"\bstages\b", first0):
        return stages(data, message, sid)
    if re.search(r"\bgame crate\b", first0):
        return game_crate(data, message, sid)
    if "make" in message:
        pid = "made-" + uuid.uuid4().hex[:6]
        (data / pid).mkdir(parents=True)
        (data / pid / "project.json").write_text("{}", encoding="utf-8")
        link(data, pid, "create_project")
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__form__create_project",
                                                           "input": {"name": "Made", "recipe": "hook"}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                                      "content": [{"type": "text", "text": json.dumps({"project": {"id": pid}})}]}]}})
    if "render" in message:
        pid = next((d.name for d in sorted(data.iterdir()) if (d / "project.json").exists()), "p")
        f = data / pid / "artifacts" / "renders" / "abc-sheet-all-v1.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"       # a valid 1 × 1 image
                      b"\x00\x00\x00\x0cIDATx\x9ccHhX\x00\x00\x02\xc4\x01\x81HR\x04\xc4\x00\x00\x00\x00IEND\xaeB`\x82")
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "mcp__form__render",
                                                           "input": {"project": pid, "view": "sheet"}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": [
            {"type": "image", "source": {}}, {"type": "text", "text": f"Part - r01. Rendered from the kernel tessellation. File: {f}"}]}]}})
    answered = ""
    first = message.splitlines()[0] if message.strip() else ""
    if re.search(r"\bask\b", first):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from form import ask
        if "approve" in message:
            q = ask.question("Replace the current design with this one?", ["Replace it", "Keep the current one"], kind="confirm",
                             why="The current revision stays in the history either way.")
        elif "words" in message:
            q = ask.question("What does the phone measure across, in mm?", why="It sets the cradle width.")
        else:
            q = ask.question("How thick is the phone with its case?", ["9 mm", "11 mm", "13 mm"],
                             why="It sets the slot width; a wrong guess makes it loose or tight.")
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t3", "name": "mcp__form__ask_user",
                                                           "input": {"question": q["question"], "choices": q["choices"]}}]}})
        folder = os.environ.get(ask.ENV_DIR)
        if not folder:
            res = ask.unreachable(q)
        else:
            qid = ask.post(Path(folder), q, 120)
            t0 = time.time()
            while True:
                st, extra = ask.state(Path(folder), qid)
                if st != "open":
                    break
                if time.time() - t0 > 120:
                    ask.close(Path(folder), qid, "timeout")
                time.sleep(0.1)
            res = ask.result(q, st, extra)
        answered = res.get("answer") or "no answer"
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t3",
                                                      "content": [{"type": "text", "text": json.dumps(res)}]}]}})
    extra = []
    if re.search(r"\bconcepts\b", first):
        extra.append(concepts(data, message))
    if first.startswith("Replace a broken part"):
        extra.append(replacement(data, message))
        extra.append(measure(data))
    elif re.search(r"\bmeasure\b", first):
        extra.append(measure(data))
    if re.search(r"\bsuggest\b", first):
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t4", "name": "mcp__form__suggest_replies",
                                                           "input": {"options": ["Make the walls 2 mm", "Show me the bottom"]}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t4", "content": [
            {"type": "text", "text": json.dumps({"shown": ["Make the walls 2 mm", "Show me the bottom"], "note": ""})}]}]}})
    out({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}})
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "You said: "}}})
    out({"type": "stream_event", "event": {"type": "content_block_stop"}})
    reply = "You said: " + message.splitlines()[0] + (f"\n\nYou answered: {answered}" if answered else "")
    extra += received(message)
    reply += "".join("\n\n" + x for x in extra if x)
    if "outline" in message:
        reply += ("\n\n1. First step, written long enough that it has to wrap onto a second line in the conversation column\n"
                  "2. Second step\n   - a nested point\n     - and one below it\n\n- a **bold** bullet with `code`\n\n"
                  "```python\nform.run()\n```\n\n| Option | Yield |\n|---|--:|\n| Head | 66 % |\n")
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "total_cost_usd": session_total(data, sid, 0.25), "num_turns": 2, "session_id": sid})
    return 0


TINY = {
    "Block": ("Box(v['size'], v['size'] * 0.6, 8, align=A)", "A solid block that sits flat."),
    "Disc": ("Cylinder(v['size'] / 2, 6, align=A)", "A round disc, no corners to catch."),
    "Bracket": ("Box(v['size'], 6, 30, align=A) + Box(v['size'], 24, 6, align=A)", "An L bracket that screws to a wall."),
}


def _source(title: str, expr: str) -> str:
    return (f'"""{title}: a tiny concept for tests."""\n'
            "from build123d import Align, Box, Cylinder\n"
            "from form.recipes.base import Feature, Param, Recipe, Stage\n"
            "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\n"
            "class Design(Recipe):\n"
            f"    title, summary = {title!r}, 'A tiny concept.'\n"
            "    params = [Param('size', 'Size', 30, 10, 80, 1, 'mm', 'form', 'body')]\n"
            "    features = [Feature('body', 'Body', 'structure')]\n\n"
            "    def build(self, v):\n"
            f"        return [Stage('body', {expr})]\n")


def link(data: Path, project, tool: str, role: str = "made", group=None):
    """What Form Studio's MCP server does when a tool makes a design: record it in the conversation
    ($FORM_CONVERSATION), the same function the server calls."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from form import conversations
    conversations.made(data, project, role, tool, group=group)


def _attached(message: str) -> list:
    lines = message.splitlines()
    if "Attached files:" not in lines:
        return []
    out = []
    for ln in lines[lines.index("Attached files:") + 1:]:
        if not ln.startswith("- "):
            break
        p = ln[2:].rsplit(" (", 1)[0]
        if p.lower().endswith((".stl", ".obj", ".3mf")):
            out.append(p)
    return out


def editable(data: Path, message: str, sid: str) -> int:
    """"make this editable" with meshes attached, through Form Studio's real MCP tools (in this process, with this
    conversation's $FORM_CONVERSATION). First line words:
      "together"  the new way: one reconstruct(files=[...]) -> one design with one part per mesh;
      otherwise   a replay of what an agent did with the owner's three STLs: design_brief, one reconstruct per file,
                  then create_design without a relation (refused: the conversation has a design in front), again with
                  relation="alternative" and the brief, and once more with the same brief (one brief, several designs).
    "layer N" picks the reconstruction layer (default 0, fast). Ends with a line "Projects: id, id, ..."."""
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ["FORM_DATA"] = str(data)
    from form import mcp_server
    first = message.splitlines()[0]
    m = re.search(r"\blayer (\d)\b", first)
    layer = int(m.group(1)) if m else 0
    files = _attached(message)
    srv = mcp_server.build()
    made, notes, n = [], [], [10]

    async def call(name, args):
        n[0] += 1
        tid = f"t{n[0]}"
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "mcp__form__" + name,
                                                           "input": {k: v for k, v in args.items() if k != "source"}}]}})
        try:
            res = await srv.call_tool(name, args)
            sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
            text = json.dumps(sc.get("result", sc) if isinstance(sc, dict) else sc, default=str) if sc is not None else \
                "".join(getattr(c, "text", "") for c in res.content)
            err = bool(getattr(res, "is_error", False) or getattr(res, "isError", False))
        except Exception as e:                              # ToolError: the agent sees the message
            text, err = str(e), True
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": err,
                                                      "content": [{"type": "text", "text": text}]}]}})
        if err:
            return None, text
        try:
            return json.loads(text), text
        except ValueError:                                  # a result with pictures: the first block is the JSON
            first_block = next((getattr(c, "text", "") for c in res.content if getattr(c, "text", "")), "")
            try:
                return json.loads(first_block), text
            except ValueError:
                return {}, text

    async def run():
        if re.search(r"\btogether\b", first):
            r, _ = await call("reconstruct", {"files": files, "layer": layer, "tolerance": 0.1})
            if r:
                made.append(r["project"])
            return
        b, _ = await call("design_brief", {"name": "Editable parts", "goal": "Rebuild the supplied parts as clean "
                                           "parametric CAD within 0.1 mm.", "purpose": "model"})
        if b:
            await call("plan_design", {"brief": b["brief"], "risks": ["sections that do not close"],
                                       "features": [{"id": "body", "label": "Body", "how": "extrude the outline"},
                                                    {"id": "pocket", "label": "Pocket", "how": "cut the pocket"},
                                                    {"id": "edges", "label": "Edges", "how": "fillet the outside"}]})
        for f in files:
            r, _ = await call("reconstruct", {"project_or_file": f, "layer": layer, "tolerance": 0.1,
                                              "name": Path(f).stem[7:] + " editable"})
            if r:
                made.append(r["project"])
        src = _source("Block", TINY["Block"][0])
        args = {"name": "Parametric part", "source": src, "run": False, "purpose": "model"}
        r, text = await call("create_design", args)
        notes.append("Refused without a relation: " + ("yes" if r is None and "relation" in text else "no"))
        for name in ("Parametric part", "Parametric part two"):     # one brief serves both
            r, text = await call("create_design", {**args, "name": name, "relation": "alternative",
                                                   "plan": b["brief"] if b else ""})
            hit = re.search(r'"project"\s*:\s*"([a-z0-9-]+)"', text) if r is not None else None
            if hit:
                made.append(hit.group(1))
            else:
                notes.append(f"create_design {name} failed: {text[:300]}")

    try:
        asyncio.run(run())
    finally:
        try:
            mcp_server.studio().kernel.stop()
        except Exception:
            pass
    reply = "You said: " + first + "\n\nProjects: " + ", ".join(made) + "".join("\n\n" + x for x in notes)
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "total_cost_usd": 0.0, "num_turns": 1, "session_id": sid})
    return 0


# A FeatureDesign whose features take a moment each, so its stages stream out one by one while it builds; the third
# (a fillet wider than the part) fails and is left out with its diagnosis, and the fourth still builds.
STAGED = '''"""A block built in stages, for the streaming journey."""
import time

from build123d import Axis, Box, Cylinder, Pos, fillet
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Staged block"
    params = [Param("w", "Width", 60, 30, 90, 1, "mm", "form", "body")]

    @feature("Body")
    def body(self, v, body):
        time.sleep(PAUSE)
        return Box(v["w"], v["w"] * 0.6, 12)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        time.sleep(PAUSE)
        return body - Cylinder(7, 40)

    @feature("Rounded top")
    def rounded_top(self, v, body):
        time.sleep(PAUSE)
        return fillet(body.edges().group_by(Axis.Z)[-1], radius=40)

    @feature("Tower")
    def tower(self, v, body):
        time.sleep(PAUSE)
        return body + Pos(v["w"] * 0.3, 0, 16) * Box(14, 14, 22)
'''


def stages(data: Path, message: str, sid: str) -> int:
    """"stages": create_design through Form Studio's real MCP tool (in this process, with this conversation's
    $FORM_CONVERSATION), with STAGED: every stage is written as a draft and logged while it builds (form/studio.py
    _draft_sink), so the app can draw it before the project is saved. "pause N" sets the seconds per feature."""
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ["FORM_DATA"] = str(data)
    from form import mcp_server
    first = message.splitlines()[0]
    m = re.search(r"\bpause ([0-9.]+)\b", first)
    src = STAGED.replace("PAUSE", m.group(1) if m else "1.2")
    srv = mcp_server.build()
    args = {"name": "Staged block", "source": src, "run": False, "purpose": "model"}
    if re.search(r"\banother\b", first):          # a second design of the same conversation, beside the first
        # another width, so no feature loads from the first one's checkpoints: every stage builds (and streams) again
        args.update(name="Staged block two", relation="alternative",
                    source=src.replace('Param("w", "Width", 60,', 'Param("w", "Width", 66,'))
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t20", "name": "mcp__form__create_design",
                                                       "input": {k: v for k, v in args.items() if k != "source"}}]}})

    async def run():
        try:
            res = await srv.call_tool("create_design", args)
            text = "".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")
            return text, bool(getattr(res, "is_error", False) or getattr(res, "isError", False))
        except Exception as e:
            return str(e), True
    try:
        text, err = asyncio.run(run())
    finally:
        try:
            mcp_server.studio().kernel.stop()
        except Exception:
            pass
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t20", "is_error": err,
                                                  "content": [{"type": "text", "text": text}]}]}})
    hit = re.search(r'"(?:project|id)"\s*:\s*"([A-Za-z0-9_-]+)"', text)
    reply = "You said: " + first + "\n\nProject: " + (hit.group(1) if hit and not err else "none")
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "total_cost_usd": 0.0, "num_turns": 1, "session_id": sid})
    return 0


def game_crate(data: Path, message: str, sid: str) -> int:
    """"game crate": create_design through Form Studio's real MCP tool with a small subdivision cage (a box cage, 3
    quads a side, written by form/game/pipeline.py cage_design_source), with the purpose of the message's "Purpose:"
    line (Home's "Make it for: Game asset" gives "game")."""
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ["FORM_DATA"] = str(data)
    import numpy as np
    from form import mcp_server, meshsource
    from form.game import pipeline
    n, lo, hi = 3, np.array([0.0, 0.0, 0.0]), np.array([60.0, 40.0, 36.0])
    V, F, ids = [], [], {}

    def pid(i, j, k):
        if (i, j, k) not in ids:
            ids[(i, j, k)] = len(V)
            V.append(lo + (hi - lo) * np.array([i, j, k]) / n)
        return ids[(i, j, k)]
    for a in range(n):
        for b in range(n):
            F += [[pid(a, b, 0), pid(a, b + 1, 0), pid(a + 1, b + 1, 0), pid(a + 1, b, 0)],
                  [pid(a, b, n), pid(a + 1, b, n), pid(a + 1, b + 1, n), pid(a, b + 1, n)],
                  [pid(a, 0, b), pid(a + 1, 0, b), pid(a + 1, 0, b + 1), pid(a, 0, b + 1)],
                  [pid(a, n, b), pid(a, n, b + 1), pid(a + 1, n, b + 1), pid(a + 1, n, b)],
                  [pid(0, a, b), pid(0, a, b + 1), pid(0, a + 1, b + 1), pid(0, a + 1, b)],
                  [pid(n, a, b), pid(n, a + 1, b), pid(n, a + 1, b + 1), pid(n, a, b + 1)]]
    src = pipeline.cage_design_source(meshsource.cage(np.array(V), F, [], {}), "Game crate")
    args = {"name": "Game crate", "source": src, "run": True}
    if _purpose(message):
        args["purpose"] = _purpose(message)
    srv = mcp_server.build()
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t30", "name": "mcp__form__create_design",
                                                       "input": {k: v for k, v in args.items() if k != "source"}}]}})

    async def run():
        try:
            res = await srv.call_tool("create_design", args)
            text = "".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")
            return text, bool(getattr(res, "is_error", False) or getattr(res, "isError", False))
        except Exception as e:
            return str(e), True
    try:
        text, err = asyncio.run(run())
    finally:
        try:
            mcp_server.studio().kernel.stop()
        except Exception:
            pass
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t30", "is_error": err,
                                                  "content": [{"type": "text", "text": text}]}]}})
    hit = re.search(r'"(?:project|id)"\s*:\s*"([A-Za-z0-9_-]+)"', text)
    reply = "You said: " + message.splitlines()[0] + "\n\nProject: " + (hit.group(1) if hit and not err else "none")
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "total_cost_usd": 0.0, "num_turns": 1, "session_id": sid})
    return 0


def _purpose(message: str):
    line = next((ln for ln in message.splitlines() if ln.startswith("Purpose:")), "")
    return "game" if "game asset" in line else "model" if "just a 3D model" in line else "print" if "3D printing" in line else None


def concepts(data: Path, message: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ.setdefault("FORM_DATA", str(data))
    from form import concepts as concepts_mod
    from form import config
    from form.studio import Studio
    st = Studio(config.load())
    items = [{"title": t, "rationale": why, "source": _source(t, expr)} for t, (expr, why) in TINY.items()]
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t5", "name": "mcp__form__propose_concepts",
                                                       "input": {"name": "Desk hook", "concepts": [{"title": i["title"]} for i in items]}}]}})
    try:
        board = concepts_mod.create(st, "Desk hook", items, "A hook for the desk.", purpose=_purpose(message), by="fake")
    finally:
        st.kernel.stop()
    link(data, None, "propose_concepts", role="concept", group=board["id"])
    for m in board["members"]:
        link(data, m["project"], "propose_concepts", role="concept", group=board["id"])
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t5",
                                                  "content": [{"type": "text", "text": json.dumps(board, default=str)}]}]}})
    if re.search(r"\blook\b", message.splitlines()[0]) and len(board["members"]) > 1:
        time.sleep(2.5)                  # the agent renders a concept a moment after proposing them (the owner's case)
        b = board["members"][1]["project"]
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t8", "name": "mcp__form__render",
                                                           "input": {"project": b, "view": "iso"}}]}})
        st.activity(b, "look", "Looking at the iso view", by="fake", view="iso")      # what render's act() writes
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t8",
                                                      "content": [{"type": "text", "text": "Rendered concept B."}]}]}})
        time.sleep(1.5)
    return "Concepts: " + ", ".join(f"{m['letter']} {m['title']}" for m in board["members"])


def replacement(data: Path, message: str) -> str:
    """Replace a broken part (form/replace.py): a tiny block design, reported as create_design, with a commit in the
    activity log so the app follows it; then measure() asks for its size."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ.setdefault("FORM_DATA", str(data))
    from form import config
    from form.studio import Studio
    name = message.splitlines()[0].split(":", 1)[1].strip().rstrip(".") or "Replacement"
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t7", "name": "mcp__form__create_design",
                                                       "input": {"name": name}}]}})
    st = Studio(config.load())
    try:
        p = st.create_design(name, _source("Block", TINY["Block"][0]), purpose=_purpose(message))
        st.activity(p["id"], "commit", f"Created {name} (r01)", by="fake")
    finally:
        st.kernel.stop()
    link(data, p["id"], "create_design")
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t7",
                                                  "content": [{"type": "text", "text": json.dumps({"project": {"id": p["id"]}})}]}]}})
    return f"Replacement: {name}"


def measure(data: Path) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from form import ask
    projects = []
    for d in data.iterdir():
        try:
            p = json.loads((d / "project.json").read_text(encoding="utf-8"))
            projects.append((p.get("created", 0), p))
        except (OSError, ValueError):
            continue
    if not projects:
        return "You measured: nothing (no project)"
    p = max(projects, key=lambda t: t[0])[1]
    head = next(r for r in p["revisions"] if r["n"] == p["head"])
    param, value = next(iter(head["values"].items()))
    q = ask.measure_question(f"How wide is it ({param})?", p["id"], param, where="Across the widest part, side to side",
                             tolerance_mm=0.1, diagram={"shape": "box", "axis": "x"}, current=value,
                             why="It sets the size of the design.")
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t6", "name": "mcp__form__ask_measurement",
                                                       "input": {"project": p["id"], "param": param, "question": q["question"]}}]}})
    folder = os.environ.get(ask.ENV_DIR)
    if not folder:
        res = ask.unreachable(q)
    else:
        qid = ask.post(Path(folder), q, 120)
        t0 = time.time()
        while True:
            st, extra = ask.state(Path(folder), qid)
            if st != "open":
                break
            if time.time() - t0 > 120:
                ask.close(Path(folder), qid, "timeout")
            time.sleep(0.1)
        res = ask.measure_result(q, st, extra)
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t6",
                                                  "content": [{"type": "text", "text": json.dumps(res)}]}]}})
    if res.get("answered") and res.get("value") is not None:
        return f"You measured: {res['value']:g} mm with {res.get('method')}"
    return f"You measured: nothing ({res.get('reason', 'no number')})"


SKETCH_HEADING = "Sketch drawn in Form Studio (structured geometry, mm, y up):"


def received(message: str) -> list:
    lines, out_ = message.splitlines(), []
    if "Attached files:" in message:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from form.conversations import kind_of
        i = lines.index("Attached files:")
        names = []
        for ln in lines[i + 1:]:
            if not ln.startswith("- "):
                break
            path = ln[2:].rsplit(" (", 1)[0]
            name = Path(path).name[7:]
            names.append(f"{name} ({kind_of(name)})")
        out_.append("I received: " + ", ".join(names))
    for i, ln in enumerate(lines):
        if ln.startswith(SKETCH_HEADING) and i + 1 < len(lines):
            try:
                s = json.loads(lines[i + 1])
                n = s.get("primitives_total", len(s.get("primitives", [])))
            except ValueError:
                n = "unreadable"
            out_.append(f"Sketch: {n} primitives")
    out_ += [ln for ln in lines if ln.startswith("Purpose:")]
    return out_


if __name__ == "__main__":
    sys.exit(main())
