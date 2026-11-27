"""The stand-in agent of the docs pictures (scripts/media/docs_shots.py). No model, no network.

    docs_agent.py <data_dir> <session-or-"-"> <model> <message>

It speaks Claude Code's stream-json, like tests/fixtures/fake_agent.py, and does through the engine what a real agent
does through Form Studio's MCP tools, so what the pictures show is real: the checks it quotes are read from the
design, the picture in the conversation is the engine's own render, the concepts are built by the CAD kernel and the
measurement question goes through form/ask.py. Only the sentences are written here. What it does follows the first
line of the message:

  "Review ..."     reads the open design (get_project), renders its sheet (render) and answers with its checks
  "Concepts ..."   builds three concepts of a phone stand (propose_concepts)
  "Measure ..."    asks for one measurement of the newest design (ask_measurement) and says what it did with it
  anything else    one line that it received the message and what was attached
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def out(obj):
    print(json.dumps(obj), flush=True)


def use(tid, name, args):
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "mcp__form__" + name, "input": args}]}})


def result(tid, content):
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": content}]}})


def say(text):
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def studio(data: Path):
    os.environ.setdefault("FORM_DATA", str(data))
    from form import config
    from form.studio import Studio
    return Studio(config.load())


def newest(data: Path) -> dict | None:
    found = []
    for d in data.iterdir():
        try:
            p = json.loads((d / "project.json").read_text(encoding="utf-8"))
            if p.get("revisions"):
                found.append((p.get("created", 0), p))
        except (OSError, ValueError):
            continue
    return max(found, key=lambda t: t[0])[1] if found else None


def open_design(data: Path, message: str) -> dict | None:
    """The design the message is about: Form Studio names the open design in the prompt it builds."""
    for pid in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", message):
        if (data / pid / "project.json").exists():
            return json.loads((data / pid / "project.json").read_text(encoding="utf-8"))
    return newest(data)


def review(data: Path, message: str) -> str:
    p = open_design(data, message)
    if not p:
        return "There is no design open to review."
    pid, rev = p["id"], "r%02d" % p["head"]
    use("t1", "get_project", {"project": pid})
    st = studio(data)
    try:
        state = st.state(pid)
    finally:
        st.kernel.stop()
    checks = ((state.get("checks") or {}).get("checks")) or []
    result("t1", [{"type": "text", "text": json.dumps({"project": pid, "head": p["head"], "checks": [
        "%s  %s: %s" % (c.get("status"), c.get("label"), c.get("value")) for c in checks]})}])
    use("t2", "render", {"project": pid, "view": "sheet"})
    r = subprocess.run([sys.executable, "-m", "form", "tool", "render", json.dumps({"project": pid, "view": "sheet"})],
                       capture_output=True, text=True, cwd=ROOT, env={**os.environ, "FORM_DATA": str(data)})
    m = re.search(r"File: (.*?\.png)", r.stdout.replace("\\n", "\n"))
    cap = f"{p['name']} - {rev}. Rendered from the kernel tessellation." + (f" File: {m.group(1)}" if m else "")
    result("t2", [{"type": "image", "source": {}}, {"type": "text", "text": cap}])
    passed = [c for c in checks if c.get("status") == "PASS"]
    look = [c for c in checks if c.get("status") not in ("PASS", "NA", None)]
    by = {c.get("id"): c for c in checks}
    lines = [f"I looked at **{rev}** from four sides and read its checks: {len(passed)} pass"
             + (f", {len(look)} want a look." if look else ", nothing fails.")]
    if look:
        lines.append("")
        for i, c in enumerate(look[:4], 1):
            detail = (c.get("detail") or "").split(". ")[0].strip().rstrip(".")
            lines.append(f"{i}. **{c.get('label')}** is `{c.get('value')}`" + (f". {detail}." if detail else "."))
    wall = by.get("min_wall") or next((c for c in checks if "wall" in (c.get("label") or "").lower()), None)
    lines += ["", "What I would keep as it is:", ""]
    if wall:
        lines.append(f"- {wall.get('label')}: `{wall.get('value')}`, measured on the solid.")
    for c in passed[:2]:
        if c is not wall:
            lines.append(f"- {c.get('label')}: `{c.get('value')}`.")
    lines += ["", "The fit is modelled from assumed sizes. Measure the phone with its case before you print, and I will "
              "set the pocket to what you measured."]
    return "\n".join(lines)


CONCEPTS = {
    "Cradle with a back rest": (
        "Box(v['size'], 70, 8, align=A) + Pos(0, 24, 8) * Rot(-14, 0, 0) * Box(v['size'], 7, 96, align=A)"
        " + Pos(0, -22, 8) * Box(v['size'], 8, 14, align=A)",
        "Leans the phone back at 14° on a wide foot; the lip in front holds it and leaves room for a cable."),
    "Slotted block": (
        "Box(v['size'], 60, 34, align=A) - Pos(0, 4, 12) * Rot(-12, 0, 0) * Box(v['size'] + 2, 12, 40, align=A)",
        "One solid block with a leaning slot: heavy, nothing to snap off, prints without support."),
    "Round puck": (
        "Cylinder(v['size'] / 2, 26, align=A) - Pos(0, 4, 10) * Rot(-12, 0, 0) * Box(v['size'] + 2, 12, 40, align=A)",
        "A weighted disc with the same slot: no corners to catch a sleeve, turns to face you."),
}


def source(title: str, expr: str, why: str) -> str:
    return (f'"""{title}: a concept for a phone stand."""\n'
            "from build123d import Align, Box, Cylinder, Pos, Rot\n"
            "from form.recipes.base import Feature, Param, Recipe, Stage\n"
            "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\n"
            "class Design(Recipe):\n"
            f"    title, summary = {title!r}, {why!r}\n"
            "    params = [Param('size', 'Width', 78, 60, 110, 1, 'mm', 'form', 'body')]\n"
            "    features = [Feature('body', 'Body', 'structure')]\n\n"
            "    def build(self, v):\n"
            f"        return [Stage('body', {expr})]\n")


def purpose_of(message: str):
    m = re.search(r"^Purpose: (.*)$", message, re.M)
    return None if not m else ("model" if "3D model" in m.group(1) else "print")


def concepts(data: Path, message: str) -> str:
    from form import concepts as concepts_mod
    from form import conversations
    items = [{"title": t, "rationale": why, "source": source(t, expr, why)} for t, (expr, why) in CONCEPTS.items()]
    use("t5", "propose_concepts", {"name": "Desk phone stand", "concepts": [{"title": i["title"]} for i in items]})
    st = studio(data)
    try:
        board = concepts_mod.create(st, "Desk phone stand", items, "A phone stand for the desk, with room for the charging cable.",
                                    purpose=purpose_of(message), by="agent")
    finally:
        st.kernel.stop()
    conversations.made(data, None, "concept", "propose_concepts", group=board["id"])
    for m in board["members"]:
        conversations.made(data, m["project"], "concept", "propose_concepts", group=board["id"])
    result("t5", [{"type": "text", "text": json.dumps(board, default=str)}])
    return ("A phone stand can go three quite different ways, so I built each one in the kernel for you to compare by "
            "its real size and volume:\n\n"
            + "\n".join(f"- **{m['letter']} · {m['title']}**: {CONCEPTS[m['title']][1]}" for m in board["members"])
            + "\n\nPick one to continue with, or tell me what to mix.")


def measure(data: Path) -> str:
    from form import ask
    p = newest(data)
    if not p:
        return "There is no design to measure for yet."
    head = next(r for r in p["revisions"] if r["n"] == p["head"])
    param = "device_thickness" if "device_thickness" in head["values"] else next(iter(head["values"]))
    value = head["values"][param]
    q = ask.measure_question("How thick is your phone with its case?", p["id"], param,
                             where="Across the thickest part, near the bottom edge, case on", tolerance_mm=0.1,
                             diagram={"shape": "box", "axis": "y"}, current=value,
                             why="The slot is cut to this number plus the clearance; a millimetre off and the phone rattles or does not go in.")
    use("t6", "ask_measurement", {"project": p["id"], "param": param, "question": q["question"]})
    folder = os.environ.get(ask.ENV_DIR)
    if not folder:
        res = ask.unreachable(q)
    else:
        qid = ask.post(Path(folder), q, 300)
        t0 = time.time()
        while True:
            st, extra = ask.state(Path(folder), qid)
            if st != "open":
                break
            if time.time() - t0 > 300:
                ask.close(Path(folder), qid, "timeout")
            time.sleep(0.1)
        res = ask.measure_result(q, st, extra)
    result("t6", [{"type": "text", "text": json.dumps(res)}])
    if res.get("answered") and res.get("value") is not None:
        return (f"Thank you. The slot now follows **{res['value']:g} mm**, recorded as measured with {res.get('method')}; "
                "the part and its fit were built again.")
    return "No number came back, so the slot keeps its assumed size for now."


def attached(message: str) -> str:
    lines = message.splitlines()
    if "Attached files:" not in lines:
        return ""
    names = []
    for ln in lines[lines.index("Attached files:") + 1:]:
        if not ln.startswith("- "):
            break
        names.append(Path(ln[2:].rsplit(" (", 1)[0]).name[7:])
    return ", ".join(names)


def main():
    data, session, model, message = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    sid = session if session != "-" else "sess-" + uuid.uuid4().hex[:8]
    out({"type": "system", "subtype": "init", "session_id": sid, "model": model})
    first = message.splitlines()[0] if message.strip() else ""
    if re.match(r"\s*review\b", first, re.I):
        text, spent, turns = review(data, message), 0.31, 3
    elif re.match(r"\s*concepts\b", first, re.I):
        text, spent, turns = concepts(data, message), 0.42, 2
    elif re.match(r"\s*measure\b", first, re.I):
        text, spent, turns = measure(data), 0.12, 2
    else:
        got = attached(message)
        text, spent, turns = ("I have your message" + (f" and {got}" if got else "") + ". I will start from it."), 0.05, 1
    say(text)
    out({"type": "result", "total_cost_usd": spent, "num_turns": turns, "session_id": sid})
    return 0


if __name__ == "__main__":
    sys.exit(main())
