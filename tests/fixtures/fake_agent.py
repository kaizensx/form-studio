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
              The designs get the purpose of the message's "Purpose:" line.
  "measure"   asks a measurement question (kind "measure", the files of form/ask.py) about the newest project's first
              parameter: where "Across the widest part, side to side", tolerance 0.1 mm, diagram box/x, current = its value.
              After the answer the reply has "You measured: <value> mm with <method>" (value as %g), or
              "You measured: nothing (<reason>)" when the question closed unanswered.
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
    if "make" in message:
        pid = "made-" + uuid.uuid4().hex[:6]
        (data / pid).mkdir(parents=True)
        (data / pid / "project.json").write_text("{}", encoding="utf-8")
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
    if re.search(r"\bmeasure\b", first):
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
    out({"type": "result", "total_cost_usd": 0.25, "num_turns": 2, "session_id": sid})
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


def _purpose(message: str):
    line = next((ln for ln in message.splitlines() if ln.startswith("Purpose:")), "")
    return "model" if "just a 3D model" in line else "print" if "3D printing" in line else None


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
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t5",
                                                  "content": [{"type": "text", "text": json.dumps(board, default=str)}]}]}})
    return "Concepts: " + ", ".join(f"{m['letter']} {m['title']}" for m in board["members"])


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
