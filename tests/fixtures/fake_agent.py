"""A stand-in for an agent CLI, for tests. Speaks Claude Code's stream-json. No model, no network.

    fake_agent.py <data_dir> <session-or-"-"> <model> <message>

Behaviour is chosen by words in the message: "slow" waits until terminated; "make" creates a project folder and
reports it from a create_project tool; "render" reports a render PNG; "outline" answers in Markdown (lists, code, a table); "boom" exits 1. A session id that starts with
"gone" is refused the way a CLI refuses a session it no longer has. "ask" asks a question the way Form Studio's ask_user
tool does (the same files, form/ask.py; the word "ask" in the first line; "approve" makes it an approval card, "words" a question without choices) and
waits for the answer; "suggest" offers follow-ups through suggest_replies.
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
    if re.search(r"\bsuggest\b", first):
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t4", "name": "mcp__form__suggest_replies",
                                                           "input": {"options": ["Make the walls 2 mm", "Show me the bottom"]}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t4", "content": [
            {"type": "text", "text": json.dumps({"shown": ["Make the walls 2 mm", "Show me the bottom"], "note": ""})}]}]}})
    out({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}})
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "You said: "}}})
    out({"type": "stream_event", "event": {"type": "content_block_stop"}})
    reply = "You said: " + message.splitlines()[0] + (f"\n\nYou answered: {answered}" if answered else "")
    if "outline" in message:
        reply += ("\n\n1. First step, written long enough that it has to wrap onto a second line in the conversation column\n"
                  "2. Second step\n   - a nested point\n     - and one below it\n\n- a **bold** bullet with `code`\n\n"
                  "```python\nform.run()\n```\n\n| Option | Yield |\n|---|--:|\n| Head | 66 % |\n")
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    out({"type": "result", "total_cost_usd": 0.25, "num_turns": 2, "session_id": sid})
    return 0


if __name__ == "__main__":
    sys.exit(main())
