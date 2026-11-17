"""Conversations: saved chats, agent adapters, attachments. A fake agent CLI stands in for Claude Code; no model runs."""
import json
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from form import chat  # noqa: E402
from form.agents import ADAPTERS  # noqa: E402
from form.agents.base import Adapter, Run  # noqa: E402
from form.agents.claude import Claude, ClaudeParser  # noqa: E402
from form.agents.codex import Codex, CodexParser, _toml  # noqa: E402
from form.agents.gemini import GeminiParser  # noqa: E402
from form.conversations import ConversationError, Conversations, title_from  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_agent.py"


class Fake(Adapter):
    """Runs tests/fixtures/fake_agent.py; records every command it was asked to build."""
    id, label, cli = "fake", "Fake agent", "python"
    images, cost = True, True

    def __init__(self, data: Path):
        self.data, self.runs = data, []

    def executable(self, cfg):
        return sys.executable

    def models(self, cfg, exe):
        return [{"id": "default", "label": "Default", "note": ""}, {"id": "small", "label": "Small", "note": ""}]

    def command(self, run: Run, exe: str):
        self.runs.append(run)
        return [exe, str(FAKE), str(self.data), run.session or "-", run.model, run.message]

    def parser(self):
        return ClaudeParser()


def wait(job, timeout=20):
    t0 = time.time()
    while job.state == "running" and time.time() - t0 < timeout:
        time.sleep(0.02)
    return job


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir()
        self.fake = Fake(self.data)
        self.cfg = {"chat": {"agent": "fake", "model": "default", "effort": ""}, "_path": str(Path(self.tmp.name) / "studio.toml")}
        self.chat = chat.Chat(self.cfg, self.data, "/nonexistent/form-mcp", adapters={"fake": self.fake})

    def tearDown(self):
        for j in self.chat.running():
            self.chat.stop(j.id)
            wait(j, 5)
        self.tmp.cleanup()


class Store(Base):
    def test_roundtrip_reloads_exactly(self):
        s = Conversations(self.data)
        m = s.create("dock", "claude", "opus", "high")
        evs = [{"t": "user", "text": "Make it 2 mm thicker.\nAnd keep the fillet."}, {"t": "start", "model": "claude-x"},
               {"t": "tool", "id": "a", "name": "render", "input": "view=sheet"}, {"t": "result", "id": "a", "ok": True, "image": True, "text": "ok"},
               {"t": "text", "text": "Done — wall is 4 mm."}, {"t": "act", "by": "codex", "text": "Looking at the top view"},
               {"t": "end", "cost_usd": 0.5, "turns": 3}, {"t": "error", "text": "x"}]
        for e in evs:
            s.append(m["id"], e)
        again = Conversations(self.data).get(m["id"])            # a new process would do exactly this
        self.assertEqual([{k: v for k, v in e.items() if k != "ts"} for e in again["items"]], evs)
        self.assertEqual((again["project"], again["agent"], again["model"], again["effort"]), ("dock", "claude", "opus", "high"))
        self.assertEqual((again["title"], again["messages"], again["cost_usd"], again["resolved_model"]),
                         ("Make it 2 mm thicker", 1, 0.5, "claude-x"))
        self.assertEqual(Conversations(self.data).get(m["id"], 6)["items"][0]["t"], "end")
        self.assertTrue((self.data / ".conversations" / m["id"] / "events.jsonl").is_file())

    def test_titles(self):
        self.assertEqual(title_from("  ## A case for a Raspberry Pi 5.  \nmore"), "A case for a Raspberry Pi 5")
        long = title_from("A very long request that keeps going well past what fits in a narrow column header")
        self.assertTrue(long.endswith("…") and len(long) <= 54 and not long[:-1].endswith(" "))
        self.assertEqual(title_from(""), "New conversation")
        s = Conversations(self.data)
        m = s.create()
        s.rename(m["id"], "  Dock   v2 ")
        s.append(m["id"], {"t": "user", "text": "first message"})
        self.assertEqual(s.meta(m["id"])["title"], "Dock v2")           # a name you gave is never replaced
        with self.assertRaises(ConversationError):
            s.rename(m["id"], "   ")

    def test_latest_is_right_when_the_clock_does_not_tick(self):
        """Windows' clock is coarse: three writes can share one time.time(). The most recent must still win."""
        from unittest import mock
        with mock.patch("time.time", return_value=1_800_000_000.0):
            s = Conversations(self.data)
            a, b = s.create("dock"), s.create("dock")
            s.append(a["id"], {"t": "user", "text": "one"})
            s.append(a["id"], {"t": "text", "text": "two"})
            s.append(b["id"], {"t": "user", "text": "three"})
            self.assertEqual(s.latest("dock")["id"], b["id"])

    def test_list_filter_search_pin_delete(self):
        s = Conversations(self.data)
        a, b, c = s.create("dock"), s.create("dock"), s.create(None)
        s.append(a["id"], {"t": "user", "text": "Add a cable channel"})
        s.append(a["id"], {"t": "text", "text": "The channel is 6 mm wide; bridged roof is assumed printable."})
        s.append(b["id"], {"t": "user", "text": "Lighter please"})
        s.append(c["id"], {"t": "user", "text": "A gridfinity bin"})
        self.assertEqual({m["id"] for m in s.list("dock")}, {a["id"], b["id"]})
        self.assertEqual(len(s.list()), 3)
        self.assertEqual([m["id"] for m in s.list(q="cable")], [a["id"]])
        hit = s.list(q="bridged roof")                                    # found in the reply text, not the title
        self.assertEqual([m["id"] for m in hit], [a["id"]])
        self.assertEqual(s.list(q="nothing-like-this"), [])
        self.assertEqual(s.latest("dock")["id"], b["id"])
        s.pin(a["id"])
        self.assertEqual(s.list()[0]["id"], a["id"])
        s.delete(b["id"])
        self.assertEqual({m["id"] for m in s.list("dock")}, {a["id"]})
        with self.assertRaises(ConversationError):
            s.get(b["id"])
        with self.assertRaises(ConversationError):
            s.get("../../etc")

    def test_attach(self):
        s = Conversations(self.data)
        m = s.create()
        src = Path(self.tmp.name) / "My sketch (1).PNG"
        src.write_bytes(b"\x89PNG....")
        rec = s.attach(m["id"], src)
        self.assertEqual((rec["kind"], rec["name"], rec["size"]), ("image", "My sketch (1).PNG", 8))
        f = s.attachment(m["id"], rec["file"])
        self.assertEqual(f.parent, (self.data / ".conversations" / m["id"] / "files").resolve())
        self.assertEqual(s.attach(m["id"], name="pi5.step", data=b"ISO-10303-21;")["kind"], "cad")
        self.assertEqual(s.attach(m["id"], name="sheet.pdf", data=b"%PDF")["kind"], "pdf")
        with self.assertRaises(ConversationError):
            s.attach(m["id"], name="notes.exe", data=b"x")
        with self.assertRaises(ConversationError):
            s.attachment(m["id"], "../meta.json")
        self.assertEqual([a["id"] for a in s.attachments(m["id"], [rec["id"], "zzzzzz", "../.."])], [rec["id"]])


class Sending(Base):
    def test_send_saves_stream_and_resumes(self):
        j = wait(self.chat.send("Hello there"))
        self.assertEqual(j.state, "done", j.error)
        c = self.chat.conversation(j.conversation)
        self.assertEqual([e["t"] for e in c["items"]], ["user", "start", "text", "end"])
        self.assertEqual((c["title"], c["agent"], c["resolved_model"], c["cost_usd"], c["state"]),
                         ("Hello there", "fake", "fake-default-1", 0.25, "idle"))
        self.assertEqual(c["items"][1]["asked"], "default")
        self.assertTrue(c["session"].startswith("sess-"))
        self.assertIsNone(self.fake.runs[0].session)
        self.assertEqual(self.fake.runs[0].cwd, self.data / ".conversations" / j.conversation)
        j2 = wait(self.chat.send("Again", j.conversation, model="small"))
        self.assertEqual(self.fake.runs[1].session, c["session"])           # continued in the CLI's own session
        self.assertEqual(self.fake.runs[1].message, "Again")                 # so no transcript is pasted in
        c2 = self.chat.conversation(j.conversation)
        self.assertEqual((c2["messages"], c2["cost_usd"], c2["model"], c2["resolved_model"]), (2, 0.5, "small", "fake-small-1"))
        self.assertEqual(self.chat.conversation(j.conversation, c["next"])["items"][0]["text"], "Again")
        self.assertEqual(j2.public()["conversation"], j.conversation)

    def test_lost_session_is_retried_with_a_transcript(self):
        j = wait(self.chat.send("First question"))
        self.chat.store.update(j.conversation, session="gone-1")
        j2 = wait(self.chat.send("Second question", j.conversation))
        self.assertEqual(j2.state, "done", j2.error)
        self.assertEqual([r.session for r in self.fake.runs], [None, "gone-1", None])
        self.assertIn("User: First question", self.fake.runs[2].message)
        self.assertIn("Assistant: You said: First question", self.fake.runs[2].message)
        kinds = [e["t"] for e in self.chat.store.events(j.conversation)]
        self.assertEqual(kinds, ["user", "start", "text", "end", "user", "start", "text", "end"])
        self.assertTrue(self.chat.store.meta(j.conversation)["session"].startswith("sess-"))

    def test_session_is_not_passed_to_another_agent(self):
        other = Fake(self.data)
        other.id = "other"
        self.chat.adapters["other"] = other
        j = wait(self.chat.send("One"))
        wait(self.chat.send("Two", j.conversation, agent="other"))
        self.assertIsNone(other.runs[0].session)
        self.assertIn("User: One", other.runs[0].message)
        self.assertEqual(self.chat.store.meta(j.conversation)["session_agent"], "other")

    def test_one_at_a_time_per_conversation_three_at_once(self):
        jobs = [self.chat.send(f"slow {i}") for i in range(3)]
        with self.assertRaisesRegex(RuntimeError, "already running"):
            self.chat.send("slow 4")
        with self.assertRaisesRegex(RuntimeError, "still answering"):
            self.chat.send("more", jobs[0].conversation)
        t0 = time.time()
        while not jobs[0].live and time.time() - t0 < 10:
            time.sleep(0.02)
        self.assertEqual(self.chat.conversation(jobs[0].conversation)["live"]["text"], "Working")
        self.assertEqual({m["state"] for m in self.chat.list()}, {"running"})
        self.assertTrue(self.chat.stop(jobs[0].conversation))                # by conversation id
        wait(jobs[0], 10)
        self.assertEqual(jobs[0].state, "stopped")
        last = self.chat.store.events(jobs[0].conversation)[-1]
        self.assertEqual((last["t"], last["stopped"]), ("end", True))
        wait(self.chat.send("now there is room"))                            # a slot is free again
        for j in jobs[1:]:
            self.chat.stop(j.id)

    def test_failure_is_saved_as_an_error(self):
        j = wait(self.chat.send("boom"))
        self.assertEqual(j.state, "failed")
        evs = self.chat.store.events(j.conversation)
        self.assertEqual(evs[-1]["t"], "error")
        self.assertIn("fell over", evs[-1]["text"])

    def test_created_project_attaches_and_render_is_linked(self):
        j = wait(self.chat.send("make one and render it"))
        self.assertEqual(j.state, "done", j.error)
        meta = self.chat.store.meta(j.conversation)
        self.assertTrue(meta["project"].startswith("made-"))
        res = [e for e in self.chat.store.events(j.conversation) if e["t"] == "result"]
        self.assertEqual(res[0]["project"], meta["project"])
        self.assertEqual(res[1]["img"], {"project": meta["project"], "file": "abc-sheet-all-v1.png"})
        self.assertNotIn("full", res[1])
        self.assertEqual(self.chat.store.latest(meta["project"])["id"], j.conversation)

    def test_attachments_reach_the_agent_as_paths(self):
        m = self.chat.store.create(agent="fake")
        a = self.chat.store.attach(m["id"], name="sketch.png", data=b"\x89PNG")
        b = self.chat.store.attach(m["id"], name="pi.step", data=b"ISO")
        wait(self.chat.send("What is this?", m["id"], attachments=[a["id"], b["id"]]))
        run = self.fake.runs[0]
        fdir = self.data / ".conversations" / m["id"] / "files"
        self.assertEqual(run.images, [fdir / a["file"]])
        self.assertEqual(len(run.files), 2)
        self.assertIn(str(fdir / a["file"]) + " (image)", run.message)
        self.assertIn("import_reference", run.message)
        user = self.chat.store.events(m["id"])[0]
        self.assertEqual([x["name"] for x in user["attachments"]], ["sketch.png", "pi.step"])

    def test_legacy_start_continues_by_session(self):
        j = wait(self.chat.start("hi"))
        j2 = wait(self.chat.start("again", None, j.session))
        self.assertEqual(j2.conversation, j.conversation)
        self.assertEqual([e["t"] for e in j2.public()["events"]], ["user", "start", "text", "end"])


class Http(Base):
    """The routes the app calls, through the real handler."""

    def call(self, method, path, body=None, raw=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=30)
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data, headers={"Content-Type": "application/octet-stream" if raw is not None else "application/json"} if data is not None else {})
        r = c.getresponse()
        payload = r.read()
        c.close()
        return r.status, (json.loads(payload) if r.getheader("Content-Type", "").startswith("application/json") else payload)

    def test_routes(self):
        import threading
        from http.server import ThreadingHTTPServer
        from types import SimpleNamespace
        from form.server import make_handler
        acts = []
        st = SimpleNamespace(cfg=self.cfg, root=self.data, chat=self.chat, setup_app=object(),
                             activity=lambda pid, kind, text, by="agent", **k: acts.append((pid, kind, by)))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        try:
            code, s = self.call("GET", "/api/chat")
            self.assertEqual((code, s["default"]["agent"], s["agents"][0]["id"]), (200, "fake", "fake"))
            code, m = self.call("POST", "/api/conversations", {"project": None})
            self.assertEqual((code, m["agent"], m["messages"]), (200, "fake", 0))
            cid = m["id"]
            code, a = self.call("POST", f"/api/conversations/{cid}/attach?name=photo%20one.png", raw=b"\x89PNG-bytes")
            self.assertEqual((code, a["attachments"][0]["kind"]), (200, "image"))
            code, raw = self.call("GET", f"/api/conversations/{cid}/file/{a['attachments'][0]['file']}")
            self.assertEqual((code, raw), (200, b"\x89PNG-bytes"))
            code, r = self.call("POST", f"/api/conversations/{cid}/send", {"message": "make one and render it", "attachments": [a["attachments"][0]["id"]]})
            self.assertEqual((code, r["conversation"]), (200, cid))
            wait(self.chat.jobs[r["id"]])
            self.assertEqual(acts[0][1:], ("chat", "you"))
            code, c = self.call("GET", f"/api/conversations/{cid}?from=1")
            self.assertEqual((code, c["state"], c["items"][0]["t"], c["next"]), (200, "idle", "start", c["events"]))
            img = next(e["img"] for e in c["items"] if e.get("img"))
            code, png = self.call("GET", f"/api/conversations/render/{img['project']}/{img['file']}")
            self.assertEqual((code, png[:4]), (200, b"\x89PNG"))
            self.assertEqual(self.call("GET", "/api/conversations/render/x/..%2Fproject.png")[0], 404)
            code, lst = self.call("GET", f"/api/conversations?project={c['project']}")
            self.assertEqual([x["id"] for x in lst["conversations"]], [cid])
            self.assertEqual(self.call("GET", "/api/conversations?q=render")[1]["conversations"][0]["id"], cid)
            self.assertEqual(self.call("POST", f"/api/conversations/{cid}/rename", {"title": "Dock"})[1]["title"], "Dock")
            self.assertTrue(self.call("POST", f"/api/conversations/{cid}/pin", {"on": True})[1]["pinned"])
            self.assertEqual(self.call("POST", f"/api/conversations/{cid}/note", {"by": "codex", "text": "Looking"})[1]["t"], "act")
            self.assertEqual(self.call("POST", f"/api/conversations/{cid}/settings", {"model": "small"})[1]["model"], "small")
            self.assertEqual(self.call("POST", f"/api/conversations/{cid}/stop", {})[1], {"stopped": False})
            code, r2 = self.call("POST", "/api/conversations/send", {"message": "A new one"})
            self.assertNotEqual(r2["conversation"], cid)
            wait(self.chat.jobs[r2["id"]])
            code, old = self.call("POST", "/api/chat", {"message": "old page"})                 # the web bench still works
            wait(self.chat.jobs[old["id"]])
            self.assertEqual(self.call("GET", f"/api/chat/{old['id']}")[1]["state"], "done")
            self.assertEqual(self.call("POST", f"/api/conversations/{cid}/delete", {})[1], {"deleted": cid})
            self.assertEqual(self.call("GET", f"/api/conversations/{cid}")[0], 404)
            self.assertEqual(self.call("POST", "/api/conversations/send", {"message": "  "})[0], 400)
        finally:
            self.httpd.shutdown()
            self.httpd.server_close()


class Defaults(Base):
    def test_status_and_defaults(self):
        st = self.chat.status()
        self.assertTrue(st["available"])
        self.assertEqual(st["default"], {"agent": "fake", "model": "default", "effort": ""})
        self.assertEqual([m["id"] for m in st["agents"][0]["models"]], ["default", "small"])

    def test_set_defaults_changes_only_chat_keys(self):
        path = Path(self.cfg["_path"])
        path.write_text('# mine\n[data]\ndir = "~/FORM"  # keep\n\n[chat]\nweb = false\nmodel = "opus" # old\n\n[slicer]\nkind = "auto"\n', encoding="utf-8")
        cfg = dict(self.cfg, _adapters={"fake": self.fake, "claude": ADAPTERS["claude"]})
        import os
        old = os.environ.get("FORM_CONFIG")
        os.environ["FORM_CONFIG"] = str(path)
        try:
            r = chat.set_defaults(cfg, agent="fake", model="sonnet", effort="high")
        finally:
            os.environ.pop("FORM_CONFIG") if old is None else os.environ.__setitem__("FORM_CONFIG", old)
        self.assertTrue(r["saved"], r)
        text = path.read_text(encoding="utf-8")
        t = tomllib.loads(text)
        self.assertEqual(t["chat"], {"web": False, "model": "sonnet", "agent": "fake", "effort": "high"})
        self.assertEqual((t["data"], t["slicer"]), ({"dir": "~/FORM"}, {"kind": "auto"}))
        self.assertIn("# mine", text)
        self.assertIn("# old", text)
        self.assertTrue(path.with_name("studio.toml.bak-form-chat").is_file())
        self.assertEqual(tomllib.loads(chat.set_defaults_text("", {"agent": "codex"})), {"chat": {"agent": "codex"}})
        with self.assertRaises(ValueError):
            chat.set_defaults(cfg, agent="nope")


class Adapters(unittest.TestCase):
    HELP = ("  --effort <level>     Effort level for the current session\n                       (low, medium, high, xhigh, max)\n"
            "  --model <model>      Model for the current session. Provide\n     an alias for the latest model (e.g.\n"
            "     'fable', 'opus', or 'sonnet') or a\n     model's full name.\n  -n, --name <name>   x\n  --restricted   y\n")

    def test_claude_lists_only_documented_aliases(self):
        from form.agents import base
        base._HELP[("/x/claude", ())] = self.HELP
        c = Claude()
        self.assertEqual([m["id"] for m in c.models({}, "/x/claude")], ["default", "fable", "opus", "sonnet", "haiku"])
        self.assertEqual(c.efforts({}, "/x/claude"), ["low", "medium", "high", "xhigh", "max"])

    def test_claude_command(self):
        from form.agents import base
        base._HELP[("/x/claude", ())] = self.HELP
        with tempfile.TemporaryDirectory() as d:
            run = Run(message="hi", system="SYS", model="sonnet", effort="high", session="s-1", cwd=Path(d) / "conv", scratch=Path(d),
                      mcp={"command": "/a b/form-mcp", "args": ["--no-bench"], "env": {}}, web=True, files=[Path(d) / "conv/files/x.png"])
            cmd = Claude().command(run, "/x/claude")
            self.assertEqual(cmd[:3], ["/x/claude", "-p", "hi"])
            for flag, val in (("--model", "sonnet"), ("--effort", "high"), ("--resume", "s-1"), ("--tools", "WebSearch,WebFetch,Read")):
                self.assertEqual(cmd[cmd.index(flag) + 1], val)
            allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
            self.assertIn("mcp__form__*", allowed)
            self.assertIn("Read(/" + (Path(d) / "conv").as_posix() + "/**)", allowed)      # only the conversation's folder
            self.assertIn("--restricted", cmd)
            self.assertNotIn("Bash", " ".join(cmd))
            self.assertEqual(json.loads((Path(d) / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["form"]["command"], "/a b/form-mcp")
            run.model, run.effort, run.session, run.files = "default", "", None, []
            cmd = Claude().command(run, "/x/claude")
            self.assertTrue("--model" not in cmd and "--effort" not in cmd and "--resume" not in cmd)
            self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch")

    def test_codex_command_and_stream(self):
        run = Run(message="hi", system="SYS", model="some-model", effort="high", session=None, cwd=Path("."), scratch=Path("."),
                  mcp={"command": "/a b/form-mcp", "args": ["--no-bench"], "env": {"FORM_DATA": "/d \"q\""}}, images=[Path("/t/a.png")])
        cmd = Codex().command(run, "codex")
        self.assertEqual(cmd[:3], ["codex", "exec", "--json"])
        self.assertIn('mcp_servers.form.command="/a b/form-mcp"', cmd)
        self.assertIn('mcp_servers.form.args=["--no-bench"]', cmd)
        self.assertEqual(tomllib.loads("x = " + _toml({"FORM_DATA": '/d "q"'}))["x"], {"FORM_DATA": '/d "q"'})
        self.assertIn('sandbox_mode="read-only"', cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], "some-model")
        self.assertEqual(cmd[-2:], ["--", "SYS\n\nhi"])
        run.session, run.images = "th-1", []
        cmd = Codex().command(run, "codex")
        self.assertEqual((cmd[:3], cmd[-2:]), (["codex", "exec", "resume"], ["th-1", "hi"]))
        p = CodexParser()
        lines = [
            {"type": "thread.started", "thread_id": "th-1"}, {"type": "turn.started"},
            {"type": "item.started", "item": {"id": "i1", "type": "mcp_tool_call", "server": "form", "tool": "render", "arguments": {"view": "sheet"}, "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "i1", "type": "mcp_tool_call", "server": "form", "tool": "render", "status": "completed",
                                                "result": {"content": [{"type": "image"}, {"type": "text", "text": "ok File: /x.png"}]}}},
            {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "Done."}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
        ]
        evs = [e for ln in lines for e in p.feed(json.dumps(ln)) if e["t"] != "live"]
        self.assertEqual([e["t"] for e in evs], ["session", "start", "tool", "result", "text", "end"])
        self.assertEqual((evs[2]["name"], evs[2]["input"], evs[3]["image"], evs[5]["cost_usd"], evs[5]["turns"], evs[5]["session"]),
                         ("render", "view=sheet", True, None, 1, "th-1"))
        self.assertEqual(p.feed("not json"), [])

    def test_gemini_stream(self):
        p = GeminiParser()
        lines = [{"type": "init", "session_id": "g1", "model": "some-gemini"},
                 {"type": "message", "role": "user", "content": "hi"},
                 {"type": "message", "role": "assistant", "content": "Let me ", "delta": True},
                 {"type": "message", "role": "assistant", "content": "look.", "delta": True},
                 {"type": "tool_use", "tool_name": "mcp__form__render", "tool_id": "t1", "parameters": {"view": "iso"}},
                 {"type": "tool_result", "tool_id": "t1", "status": "success", "output": "ok"},
                 {"type": "message", "role": "assistant", "content": "Done.", "delta": True},
                 {"type": "result", "status": "success", "stats": {}}]
        evs = [e for ln in lines for e in p.feed(json.dumps(ln)) if e["t"] != "live"]
        self.assertEqual([(e["t"], e.get("text", e.get("name"))) for e in evs],
                         [("start", None), ("text", "Let me look."), ("tool", "render"), ("result", "ok"), ("text", "Done."), ("end", None)])

    def test_unavailable_agent_says_why(self):
        st = ADAPTERS["gemini"].status({"chat": {"gemini_cli": "definitely-not-installed-xyz"}})
        self.assertEqual((st["available"], st["models"]), (False, []))
        self.assertIn("Install", st["why"])



class AgentDefaults(unittest.TestCase):
    """Found by a live Codex run: FORM passed Claude's default model ("opus") to Codex, which refused it."""

    def test_codex_notice_is_not_an_error(self):
        from form.agents.codex import CodexParser
        out = CodexParser().feed(json.dumps({"type": "item.completed", "item": {
            "id": "i1", "type": "error", "message": "Under-development features enabled: chronicle."}}))
        self.assertEqual([e["t"] for e in out], ["act"])
        self.assertIn("Under-development", out[0]["text"])

    def test_default_model_belongs_to_the_default_agent(self):
        src = (Path(__file__).resolve().parents[1] / "form" / "chat.py").read_text(encoding="utf-8")
        self.assertIn('mine = agent == d["agent"]', src)
        self.assertIn('(d["model"] if mine else "")', src)

if __name__ == "__main__":
    unittest.main()
