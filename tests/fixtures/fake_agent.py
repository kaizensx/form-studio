"""A stand-in for an agent CLI, for tests. Speaks Claude Code's stream-json. No model, no network.

    fake_agent.py <data_dir> <session-or-"-"> <model> <message>

Behaviour is chosen by words in the message: "slow" waits until terminated; "make" creates a project folder and
reports it from a create_project tool; "render" reports a render PNG; "boom" exits 1. A session id that starts with
"gone" is refused the way a CLI refuses a session it no longer has.
"""
import json
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
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "mcp__form__render",
                                                           "input": {"project": pid, "view": "sheet"}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": [
            {"type": "image", "source": {}}, {"type": "text", "text": f"Part - r01. Rendered from the kernel tessellation. File: {f}"}]}]}})
    out({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}})
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "You said: "}}})
    out({"type": "stream_event", "event": {"type": "content_block_stop"}})
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "You said: " + message.splitlines()[0]}]}})
    out({"type": "result", "total_cost_usd": 0.25, "num_turns": 2, "session_id": sid})
    return 0


if __name__ == "__main__":
    sys.exit(main())
