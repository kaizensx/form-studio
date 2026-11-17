"""Chat, interactive: model names learned from what the CLIs report, the agent asking the person (ask_user) across
processes, follow-up suggestions, what a reply changed, and the adapters for more agent CLIs (stream parsing from
samples in each CLI's documented shape). No model is called."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from form import ask, chat  # noqa: E402
from form.agents import ADAPTERS  # noqa: E402
from form.agents.base import Run  # noqa: E402
from form.agents.copilot import CopilotParser  # noqa: E402
from form.agents.cursor import CursorParser  # noqa: E402
from form.agents.models import Learned, pretty  # noqa: E402
from form.agents.opencode import OpenCodeParser  # noqa: E402
from form.agents.qwen import QwenParser  # noqa: E402
from tests.test_conversations import Fake, wait  # noqa: E402


def feed(parser, lines):
    out = []
    for ln in lines:
        out += parser.feed(json.dumps(ln) if not isinstance(ln, str) else ln)
    return out + parser.finish()


def kinds(evs):
    return [e["t"] for e in evs if e["t"] != "live"]


class ModelNames(unittest.TestCase):
    def test_ids_become_versioned_names(self):
        cases = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-4-5-20250929": "Sonnet 4.5", "claude-3-5-sonnet-20241022": "Sonnet 3.5",
                 "claude-opus-4-1[1m]": "Opus 4.1 (1M)", "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Haiku 4.5",
                 "claude-sonnet-4@20250514": "Sonnet 4", "gemini-2.5-pro": "Gemini 2.5 Pro", "gpt-5.1-codex": "GPT-5.1 Codex",
                 "qwen3-coder-plus": "Qwen3 Coder Plus", "anthropic/claude-sonnet-4-5": "Sonnet 4.5",
                 "Claude 4.5 Sonnet": "Claude 4.5 Sonnet", "": ""}
        for raw, want in cases.items():
            self.assertEqual(pretty(raw), want, raw)

    def test_learned_alias_shows_its_version_in_the_picker(self):
        with tempfile.TemporaryDirectory() as d:
            L = Learned(Path(d))
            st = {"id": "claude", "label": "Claude Code", "models": [
                {"id": "default", "label": "Default", "note": ""}, {"id": "opus", "label": "Opus", "alias": True, "note": ""},
                {"id": "sonnet", "label": "Sonnet", "alias": True, "note": ""}]}
            self.assertEqual([m["label"] for m in L.decorate(st)["models"]], ["Default", "Opus", "Sonnet"])
            L.learn("claude", "opus", "claude-opus-5-5")
            L.learn("claude", "default", "claude-opus-5-5")
            ms = Learned(Path(d)).decorate(st)["models"]            # a new process reads the same file
            self.assertEqual([m["label"] for m in ms], ["Default · Opus 5.5", "Opus 5.5", "Sonnet"])
            self.assertIn("claude-opus-5-5", ms[1]["note"])
            self.assertEqual(ms[1]["resolved"], "claude-opus-5-5")

    def test_chat_learns_the_model_from_the_stream_and_names_it_on_the_reply(self):
        with tempfile.TemporaryDirectory() as t:
            data = Path(t)
            c = chat.Chat({"chat": {"agent": "fake"}}, data, "/nonexistent", adapters={"fake": Fake(data)})
            job = wait(c.send("hello", model="opus", ask=False))
            self.assertEqual(job.state, "done")
            items = c.conversation(job.conversation)["items"]
            start = next(e for e in items if e["t"] == "start")
            end = next(e for e in items if e["t"] == "end")
            self.assertEqual((start["model"], start["label"]), ("fake-opus-1", "Fake Opus 1"))
            self.assertEqual((end["model"], end["label"]), ("fake-opus-1", "Fake Opus 1"))
            self.assertEqual(Learned(data).get("fake", "opus")["id"], "fake-opus-1")

    def test_codex_model_is_read_from_its_own_session_file(self):
        with tempfile.TemporaryDirectory() as home:
            day = Path(home) / "sessions" / "2026" / "11" / "17"
            day.mkdir(parents=True)
            tid = "01a1ea15-43a5-71b2-8824-f1a19309745e"
            (day / f"rollout-2026-11-17T16-17-05-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid}}) + "\n"
                + json.dumps({"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}) + "\n", encoding="utf-8")
            (Path(home) / "models_cache.json").write_text(json.dumps({"models": [{"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol"}]}))
            with mock.patch.dict(os.environ, {"CODEX_HOME": home}):
                cx = ADAPTERS["codex"]
                self.assertEqual(cx.resolve_model(tid), "gpt-6.1-sol")
                self.assertEqual(cx.model_label("gpt-6.1-sol"), "GPT-6.1-Sol")
                self.assertIsNone(cx.resolve_model("../../etc"))


class AskFiles(unittest.TestCase):
    def test_question_is_checked(self):
        with self.assertRaises(ask.AskError):
            ask.question("  ")
        q = ask.question("Which side?", ["Left", "Left", "Right"], multi=True, free=False)
        self.assertEqual((q["choices"], q["multi"], q["free"]), (["Left", "Right"], True, False))
        self.assertTrue(ask.question("Measure it?", [])["free"], "an open question is answered in words")
        self.assertEqual(ask.question("Delete it?", kind="confirm")["choices"], ["Yes", "No"])
        with self.assertRaises(ask.AskError):
            ask.question("Too many?", [str(i) for i in range(9)])

    def test_answer_round_trip_and_rules(self):
        with tempfile.TemporaryDirectory() as d:
            q = ask.question("How thick?", ["9 mm", "11 mm"], free=False)
            qid = ask.post(Path(d), q)
            self.assertEqual(ask.state(Path(d), qid), ("open", None))
            with self.assertRaises(ask.AskError):
                ask.answer(Path(d), qid, "about 10", [])                # words are not allowed here
            with self.assertRaises(ask.AskError):
                ask.answer(Path(d), qid, "", ["12 mm"])                 # not an offered choice
            a = ask.answer(Path(d), qid, "", ["11 mm", "9 mm"])
            self.assertEqual(a["choices"], ["11 mm"], "one choice when only one is allowed")
            st, got = ask.state(Path(d), qid)
            self.assertEqual(st, "answered")
            r = ask.result(q, st, got)
            self.assertEqual((r["answered"], r["answer"]), (True, "11 mm"))
            with self.assertRaises(ask.AskError):
                ask.answer(Path(d), qid, "", ["9 mm"])                  # answered once
            self.assertFalse(ask.close(Path(d), qid, "timeout"))

    def test_closed_questions_say_why(self):
        with tempfile.TemporaryDirectory() as d:
            q = ask.question("How wide?")
            qid = ask.post(Path(d), q)
            self.assertEqual(ask.close_all(Path(d), "stopped"), [qid])
            st, x = ask.state(Path(d), qid)
            r = ask.result(q, st, x)
            self.assertEqual((r["answered"], r["reason"]), (False, "stopped"))
            self.assertIn("assumed", r["note"])

    def test_mcp_tool_without_a_chat_tells_the_agent_to_ask_itself(self):
        from form import mcp_server
        env = {k: v for k, v in os.environ.items() if k != ask.ENV_DIR}
        with mock.patch.dict(os.environ, env, clear=True):
            res = asyncio.run(mcp_server.build().call_tool("ask_user", {"question": "How wide is it?", "choices": ["70", "75"]}))
        text = json.dumps(res, default=str)
        self.assertIn("no_user", text)
        self.assertIn("own interface", text)

    def test_mcp_tool_waits_for_the_answer_from_another_process(self):
        from form import mcp_server
        with tempfile.TemporaryDirectory() as d:
            def person():                                         # the app: sees the question file, answers it
                t0 = time.time()
                while time.time() - t0 < 10:
                    qs = [q for q in ask.questions(Path(d)) if q["state"] == "open"]
                    if qs:
                        ask.answer(Path(d), qs[0]["id"], "measured with calipers", ["75.6 mm"])
                        return
                    time.sleep(0.05)
            th = threading.Thread(target=person)
            th.start()
            with mock.patch.dict(os.environ, {ask.ENV_DIR: d, ask.ENV_TIMEOUT: "20"}):
                res = asyncio.run(mcp_server.build().call_tool(
                    "ask_user", {"question": "Device width?", "choices": ["75.6 mm", "76 mm"], "why": "Sets the cradle."}))
            th.join()
            text = json.dumps(res, default=str)
            self.assertIn("75.6 mm", text)
            self.assertIn("calipers", text)
            self.assertIn('\\"answered\\": true', text.replace('"answered": true', '\\"answered\\": true'))

    def test_mcp_tool_gives_up_after_its_timeout(self):
        from form import mcp_server
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {ask.ENV_DIR: d, ask.ENV_TIMEOUT: "5"}), \
                    mock.patch.object(ask, "timeout_from_env", return_value=0.3):
                res = asyncio.run(mcp_server.build().call_tool("ask_user", {"question": "Width?"}))
            self.assertIn("timeout", json.dumps(res, default=str))
            self.assertEqual(ask.questions(Path(d))[0]["state"], "closed")

    def test_terminal_answers(self):
        q = {"choices": ["9 mm", "11 mm", "13 mm"], "multi": False, "free": True}
        self.assertEqual(chat.ask_parse("2", q), (["11 mm"], ""))
        self.assertEqual(chat.ask_parse("1, 3", dict(q, multi=True)), (["9 mm", "13 mm"], ""))
        self.assertEqual(chat.ask_parse("about 10", q), ([], "about 10"))
        self.assertEqual(chat.ask_parse("7", q), ([], "7"), "a number that is not a choice is an answer in words")


class AskFake(Fake):
    def run_env(self, run):
        d = (run.mcp.get("env") or {}).get(ask.ENV_DIR)
        return {ask.ENV_DIR: d} if d else {}


class AskInChat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.chat = chat.Chat({"chat": {"agent": "fake", "ask_timeout_s": 60}}, self.data, "/nonexistent",
                              adapters={"fake": AskFake(self.data)})

    def tearDown(self):
        for j in self.chat.running():
            self.chat.stop(j.id)
            wait(j, 5)
        self.tmp.cleanup()

    def waiting(self, job, timeout=15):
        t0 = time.time()
        while not job.waiting and job.state == "running" and time.time() - t0 < timeout:
            time.sleep(0.05)
        return job.waiting

    def test_question_shows_waits_and_takes_the_answer(self):
        job = self.chat.send("please ask me", ask=True)
        q = self.waiting(job)
        self.assertIsNotNone(q, "the question reaches the conversation")
        self.assertEqual(q["choices"], ["9 mm", "11 mm", "13 mm"])
        conv = self.chat.conversation(job.conversation)
        self.assertEqual(conv["asking"]["id"], q["id"])
        self.assertEqual(self.chat.list()[0]["state"], "asking")
        self.assertEqual(conv["preview"].split(":")[0], "Question")
        self.chat.answer(job.conversation, q["id"], "", ["11 mm"])
        wait(job)
        self.assertEqual(job.state, "done")
        items = self.chat.conversation(job.conversation)["items"]
        self.assertEqual([e["t"] for e in items if e["t"] in ("ask", "answer")], ["ask", "answer"])
        self.assertTrue(any("You answered: 11 mm" in e.get("text", "") for e in items if e["t"] == "text"))
        with self.assertRaises(chat.ConversationError):
            self.chat.answer(job.conversation, q["id"], "", ["9 mm"])

    def test_stop_closes_the_question(self):
        job = self.chat.send("ask me", ask=True)
        q = self.waiting(job)
        self.assertIsNotNone(q)
        self.chat.stop(job.id)
        wait(job)
        items = self.chat.conversation(job.conversation)["items"]
        closed = [e for e in items if e["t"] == "answer"]
        self.assertEqual(closed[-1].get("closed"), "stopped")

    def test_without_a_person_the_agent_is_told_to_ask_itself(self):
        job = wait(self.chat.send("ask me", ask=False))
        items = self.chat.conversation(job.conversation)["items"]
        self.assertFalse(any(e["t"] == "ask" for e in items))
        self.assertTrue(any("no answer" in e.get("text", "") for e in items if e["t"] == "text"))

    def test_suggestions_and_change(self):
        pid = "dock-1"
        (self.data / pid).mkdir()
        (self.data / pid / "project.json").write_text(json.dumps({"head": 3}), encoding="utf-8")
        real = self.chat._event

        def bump(job, line):                       # the agent commits a revision while it works
            if line and '"result"' in line:
                (self.data / pid / "project.json").write_text(json.dumps({"head": 4}), encoding="utf-8")
            return real(job, line)
        with mock.patch.object(self.chat, "_event", bump):
            job = wait(self.chat.send("suggest something", project=pid, ask=False))
        items = self.chat.conversation(job.conversation)["items"]
        sug = [e for e in items if e["t"] == "suggest"]
        self.assertEqual(sug[0]["options"], ["Make the walls 2 mm", "Show me the bottom"])
        end = next(e for e in items if e["t"] == "end")
        self.assertEqual(end["change"], {"project": pid, "from": 3, "to": 4})


class MoreAgents(unittest.TestCase):
    def run_for(self, **kw):
        tmp = Path(tempfile.mkdtemp())
        return Run(message="hi", system="SYS", cwd=tmp, scratch=tmp, mcp={"command": "/x/form-mcp", "args": ["--no-bench"], "env": {"A": "1"}},
                   tool_timeout_s=1200, **kw)

    def test_all_registered_and_report_status_without_a_cli(self):
        for aid in ("cursor", "opencode", "qwen", "copilot"):
            a = ADAPTERS[aid]
            with mock.patch("shutil.which", return_value=None):
                st = a.status({})
            self.assertFalse(st["available"])
            self.assertTrue(st["why"])
            self.assertTrue(a.verified.startswith("not run"), "untested adapters say so")

    def test_qwen(self):
        cmd = ADAPTERS["qwen"].command(self.run_for(model="qwen3-coder-plus", session="s1"), "qwen")
        self.assertEqual(cmd[:3], ["qwen", "-p", "hi"])
        conf = json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]["form"]
        self.assertEqual((conf["timeout"], conf["trust"], conf["command"]), (1200000, True, "/x/form-mcp"))
        self.assertIn("--append-system-prompt", cmd)
        self.assertEqual(cmd[cmd.index("-r") + 1], "s1")
        evs = feed(QwenParser(), [
            {"type": "system", "subtype": "init", "session_id": "s9", "model": "qwen3-coder-plus"},
            {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "u1", "name": "mcp__form__render", "input": {"view": "sheet"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1", "is_error": False, "content": "ok"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
            {"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": "s9", "error": {"message": "quota"}}])
        self.assertEqual(kinds(evs), ["start", "tool", "result", "text", "end"])
        self.assertEqual(evs[0]["model"], "qwen3-coder-plus")
        self.assertEqual(next(e for e in evs if e["t"] == "tool")["name"], "render")
        self.assertEqual(evs[-1]["error"], "quota")

    def test_opencode(self):
        a = ADAPTERS["opencode"]
        run = self.run_for(model="anthropic/claude-sonnet-4-5", web=False)
        env = json.loads(a.run_env(run)["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(env["mcp"]["form"]["command"], ["/x/form-mcp", "--no-bench"])
        self.assertEqual(env["mcp"]["form"]["timeout"], 1200000)
        self.assertEqual(env["permission"], {"*": "deny", "form_*": "allow"})
        cmd = a.command(run, "opencode")
        self.assertEqual(cmd[:4], ["opencode", "run", "--format", "json"])
        self.assertTrue(cmd[-1].startswith("SYS"), "the standing instructions open the first message")
        evs = feed(OpenCodeParser(), [
            {"type": "step_start", "sessionID": "ses_1", "part": {"type": "step-start"}},
            {"type": "tool_use", "sessionID": "ses_1", "part": {"type": "tool", "callID": "c1", "tool": "form_render",
                                                                "state": {"status": "completed", "input": {"view": "iso"}, "output": "File: x.png"}}},
            {"type": "tool_use", "sessionID": "ses_1", "part": {"type": "tool", "callID": "c2", "tool": "bash",
                                                                "state": {"status": "error", "input": {}, "error": "denied"}}},
            {"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "Here it is."}},
            {"type": "step_finish", "sessionID": "ses_1", "part": {"type": "step-finish", "cost": 0.012, "tokens": {}}}])
        self.assertEqual(kinds(evs), ["session", "start", "tool", "result", "tool", "result", "text", "end"])
        tools = [e for e in evs if e["t"] == "tool"]
        self.assertEqual([t["name"] for t in tools], ["render", "bash"])
        res = [e for e in evs if e["t"] == "result"]
        self.assertEqual([r["ok"] for r in res], [True, False])
        self.assertAlmostEqual(evs[-1]["cost_usd"], 0.012)
        self.assertEqual(evs[-1]["session"], "ses_1")

    def test_cursor(self):
        run = self.run_for(model="sonnet-4.5")
        cmd = ADAPTERS["cursor"].command(run, "cursor-agent")
        self.assertIn("--approve-mcps", cmd)
        self.assertEqual(json.loads((run.cwd / ".cursor" / "mcp.json").read_text())["mcpServers"]["form"]["command"], "/x/form-mcp")
        perms = json.loads((run.cwd / ".cursor" / "cli.json").read_text())["permissions"]
        self.assertIn("Shell(*)", perms["deny"])
        self.assertEqual(perms["allow"][0], "Mcp(form:*)")
        evs = feed(CursorParser(), [
            {"type": "system", "subtype": "init", "session_id": "c-1", "model": "Claude 4.5 Sonnet"},
            {"type": "assistant", "timestamp_ms": 1, "message": {"content": [{"type": "text", "text": "Look"}]}, "session_id": "c-1"},
            {"type": "assistant", "timestamp_ms": 2, "message": {"content": [{"type": "text", "text": "ing."}]}, "session_id": "c-1"},
            {"type": "assistant", "model_call_id": "m", "message": {"content": [{"type": "text", "text": "Looking."}]}, "session_id": "c-1"},
            {"type": "tool_call", "subtype": "started", "call_id": "k1",
             "tool_call": {"mcpToolCall": {"providerIdentifier": "form", "toolName": "render", "args": {"view": "sheet"}}}},
            {"type": "tool_call", "subtype": "completed", "call_id": "k1",
             "tool_call": {"mcpToolCall": {"providerIdentifier": "form", "toolName": "render", "result": {"success": {"content": "ok"}}}}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}, "session_id": "c-1"},
            {"type": "result", "subtype": "success", "is_error": False, "result": "Looking. Done.", "session_id": "c-1"}])
        self.assertEqual(kinds(evs), ["start", "text", "tool", "result", "text", "end"])
        self.assertEqual([e["text"] for e in evs if e["t"] == "text"], ["Looking.", "Done."])
        self.assertEqual(next(e for e in evs if e["t"] == "tool")["name"], "render")
        self.assertTrue(next(e for e in evs if e["t"] == "result")["ok"])

    def test_copilot(self):
        run = self.run_for(model="gpt-5", effort="high", images=["/tmp/a.png"])
        cmd = ADAPTERS["copilot"].command(run, "copilot")
        self.assertIn("--allow-tool=form", cmd)
        self.assertIn("--deny-tool=shell", cmd)
        conf = json.loads(cmd[cmd.index("--additional-mcp-config") + 1])["mcpServers"]["form"]
        self.assertEqual((conf["type"], conf["timeout"]), ("local", 1200000))
        self.assertEqual(cmd[cmd.index("--attachment") + 1], "/tmp/a.png")
        evs = feed(CopilotParser(), [
            {"type": "session.start", "data": {"sessionId": "g1", "selectedModel": "gpt-5"}},
            {"type": "assistant.message_delta", "data": {"messageId": "m", "deltaContent": "Work"}},
            {"type": "assistant.message", "data": {"messageId": "m", "content": "Working on it.", "model": "gpt-5"}},
            {"type": "tool.execution_start", "data": {"toolCallId": "x1", "toolName": "form-render", "mcpServerName": "form", "mcpToolName": "render", "arguments": {}}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "x1", "success": False, "error": {"message": "no project"}}},
            {"type": "assistant.usage", "data": {"model": "gpt-5.1"}},
            {"type": "result", "exitCode": 0}])
        self.assertEqual(kinds(evs), ["start", "text", "tool", "result", "end"])
        self.assertEqual(next(e for e in evs if e["t"] == "tool")["name"], "render")
        self.assertEqual(next(e for e in evs if e["t"] == "result")["text"], "no project")
        self.assertEqual(evs[-1]["model"], "gpt-5.1", "the model that answered last is named")
        self.assertIsNone(evs[-1]["error"])

    def test_codex_and_gemini_wait_for_slow_tools(self):
        run = self.run_for()
        cx = ADAPTERS["codex"].command(run, "codex")
        self.assertIn("mcp_servers.form.tool_timeout_sec=1200", cx)
        ADAPTERS["gemini"].command(run, "gemini")
        g = json.loads((run.cwd / ".gemini" / "settings.json").read_text())["mcpServers"]["form"]
        self.assertEqual(g["timeout"], 1200000)


if __name__ == "__main__":
    unittest.main()
