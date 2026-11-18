"""API agents (form/agents/api.py): providers detected from keys and local servers, models read from each provider's
models endpoint, and the agent loop run against a fake provider (tests/fixtures/fake_provider.py) through Form Studio's
real MCP server. Also the version table for agent CLIs (form/agents/compat.py). No model is called."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import chat, fsutil, secrets  # noqa: E402
from form.agents import ADAPTERS, compat  # noqa: E402
from form.agents import providers as prov  # noqa: E402
from form.agents.api import ApiAdapter, simplify, tool_specs  # noqa: E402
from tests.fixtures.fake_provider import FakeProvider  # noqa: E402
from tests.test_conversations import wait  # noqa: E402

KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY",
        "XAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "OLLAMA_HOST")


class Env(unittest.TestCase):
    """A private secrets file, none of the developer's keys, and MCP servers that import this checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in KEYS}
        env.update({"FORM_SECRETS": str(self.root / "secrets.json"), "PYTHONPATH": str(ROOT), "FORM_DATA": str(self.data),
                    "FORM_PROVIDERS_OFFLINE": "1"})
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        prov.forget()
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        self.env.stop()
        prov.forget()
        fsutil.rmtree(self.tmp.name)                # retried: on Windows the tool server's folder frees a moment after it ends
        self.tmp.cleanup()

    def serve(self, **kw) -> FakeProvider:
        s = FakeProvider(**kw)
        self.servers.append(s)
        return s

    def chat_with(self, pid: str, url: str, **extra) -> chat.Chat:
        cfg = {"chat": {"agent": pid, f"{pid}_url": url, **extra}, "data": {"dir": str(self.data)}}
        return chat.Chat(cfg, self.data, "/nonexistent/form-mcp", adapters={pid: ApiAdapter(prov.PROVIDERS[pid])})


class Detection(Env):
    def test_local_server_is_found_on_its_url_and_lists_its_models(self):
        srv = self.serve(models=[{"id": "qwen3:8b"}, {"id": "nomic-embed-text"}])
        cfg = {"chat": {"ollama_url": srv.url}}
        st = ApiAdapter(prov.PROVIDERS["ollama"]).status(cfg)
        self.assertTrue(st["available"], st)
        self.assertEqual(st["kind"], "api")
        ids = [m["id"] for m in st["models"]]
        self.assertEqual(ids, ["default", "qwen3:8b"], "an embedding model is not a chat model")
        self.assertIn("qwen3:8b", st["models"][0]["label"] + st["models"][0]["note"])

    def test_nothing_listening_means_not_available_with_how_to_start_it(self):
        srv = self.serve()
        url = srv.url
        srv.close()
        self.servers.remove(srv)
        st = ApiAdapter(prov.PROVIDERS["lmstudio"]).status({"chat": {"lmstudio_url": url}})
        self.assertFalse(st["available"])
        self.assertIn("LM Studio", st["why"])

    def test_key_from_the_environment_or_the_secrets_file(self):
        srv = self.serve(models=[{"id": "openai/gpt-x", "supported_parameters": ["tools", "reasoning"],
                                  "architecture": {"input_modalities": ["text", "image"]}, "created": 2},
                                 {"id": "some/no-tools", "supported_parameters": [], "created": 3}], key="sk-or-test")
        cfg = {"chat": {"openrouter_url": srv.url}}
        a = ApiAdapter(prov.PROVIDERS["openrouter"])
        self.assertFalse(a.status(cfg)["available"], "no key yet")
        secrets.set_value("openrouter_api_key", "sk-or-test")
        prov.forget()
        st = a.status(cfg)
        self.assertTrue(st["available"], st)
        self.assertEqual([m["id"] for m in st["models"]], ["default", "openai/gpt-x"], "a model without tool calls is left out")
        self.assertEqual(st["models"][1]["efforts"], ["low", "medium", "high"])
        self.assertEqual(st["signin"]["how"], "Key stored by Form Studio")
        self.assertNotIn("sk-or-test", json.dumps(st))
        secrets.clear("openrouter_api_key")
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
            prov.forget()
            st = a.status(cfg)
            self.assertTrue(st["available"])
            self.assertEqual(st["signin"]["how"], "Key from OPENROUTER_API_KEY")

    def test_refused_key_is_said_plainly(self):
        srv = self.serve(models=[{"id": "m"}], key="right")
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "wrong"}):
            st = ApiAdapter(prov.PROVIDERS["mistral"]).status({"chat": {"mistral_url": srv.url}})
        self.assertFalse(st["available"])
        self.assertIn("refused", st["why"])

    def test_gemini_ids_lose_the_models_prefix_and_google_key_counts(self):
        srv = self.serve(models=[{"id": "models/gemini-x-pro", "owned_by": "google"}, {"id": "models/text-embedding-9"}])
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "g"}):
            st = ApiAdapter(prov.PROVIDERS["google"]).status({"chat": {"google_url": srv.url}})
        self.assertEqual([m["id"] for m in st["models"]][1:], ["gemini-x-pro"])

    def test_anthropic_capabilities_give_images_and_efforts(self):
        srv = self.serve(wire="anthropic", key="k", models=[
            {"id": "claude-x-1", "display_name": "Claude X 1", "created_at": "2026-01-01T00:00:00Z", "max_tokens": 64000,
             "capabilities": {"image_input": {"supported": True},
                              "effort": {"supported": True, "low": {"supported": True}, "max": {"supported": False}}}}])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            st = ApiAdapter(prov.PROVIDERS["anthropic"]).status({"chat": {"anthropic_url": srv.url}})
        self.assertEqual(st["models"][1], {"id": "claude-x-1", "label": "Claude X 1", "note": "claude-x-1", "efforts": ["low"],
                                           "images": True})
        self.assertEqual(st["models"][0]["label"], "Default · Claude X 1")
        self.assertEqual(srv.headers, [])           # listing is a GET; nothing was posted

    def test_every_agent_is_listed_and_chat_status_stays_quick(self):
        self.assertTrue({"anthropic", "openai", "google", "openrouter", "mistral", "xai", "deepseek", "groq", "ollama",
                         "lmstudio", "llamacpp"} <= set(ADAPTERS))
        t0 = time.time()
        st = chat.status({"chat": {"ollama_url": "http://127.0.0.1:9/v1", "lmstudio_url": "http://127.0.0.1:9/v1",
                                   "llamacpp_url": "http://127.0.0.1:9/v1"}, "data": {"dir": str(self.data)}})
        self.assertLess(time.time() - t0, 8)
        kinds = {a["id"]: a["kind"] for a in st["agents"]}
        self.assertEqual(kinds["claude"], "cli")
        self.assertEqual(kinds["ollama"], "api")

    def test_schema_is_simplified_for_strict_endpoints(self):
        s = {"type": "object", "title": "T", "properties": {"h": {"anyOf": [{"type": "string"}, {"type": "null"}],
                                                                  "default": None, "title": "H"}}}
        self.assertEqual(simplify(s, True), {"type": "object", "properties": {"h": {"type": "string"}}})
        self.assertEqual(simplify(s, False), s)
        spec = tool_specs(prov.PROVIDERS["anthropic"], [{"name": "render", "description": "Look", "inputSchema": s}])[0]
        self.assertEqual((spec["name"], spec["eager_input_streaming"]), ("render", True))


class Loop(Env):
    """The whole loop: a message, tool calls through Form Studio's real MCP server, follow-ups, the saved history."""

    def test_openai_wire_through_real_tools_and_history_continues(self):
        srv = self.serve(models=[{"id": "local-model"}], script=[
            {"text": "Looking at what exists.", "tools": [("form_overview", {})]},
            {"tools": [("suggest_replies", {"options": ["Make a hook", "Show recipes"]})]},
            {"text": "There are built-in recipes.", "usage": {"prompt_tokens": 1200, "completion_tokens": 80}},
            {"text": "Still here."}])
        c = self.chat_with("ollama", srv.url)
        job = wait(c.send("What can you make?", ask=False), 300)
        self.assertEqual(job.state, "done", job.error)
        items = c.conversation(job.conversation)["items"]
        kinds = [e["t"] for e in items]
        self.assertEqual(kinds[:2], ["user", "start"])
        self.assertIn("suggest", kinds)
        tools = [e for e in items if e["t"] == "tool"]
        self.assertEqual([t["name"] for t in tools], ["form_overview", "suggest_replies"])
        res = next(e for e in items if e["t"] == "result" and e["name"] == "form_overview")
        self.assertTrue(res["ok"])
        self.assertEqual(next(e for e in items if e["t"] == "suggest")["options"], ["Make a hook", "Show recipes"])
        texts = [e["text"] for e in items if e["t"] == "text"]
        self.assertEqual(texts, ["Looking at what exists.", "There are built-in recipes."])
        end = next(e for e in items if e["t"] == "end")
        self.assertEqual((end["model"], end["agent"], end["steps"]), ("local-model", "ollama", 2))
        self.assertEqual(end["usage"]["input_tokens"], 10 + 10 + 1200)
        self.assertIsNone(end["cost_usd"], "this provider reports no price")
        # the second request carried the real tool output back, as a tool message
        second = srv.requests[1]["messages"]
        tool_msg = next(m for m in second if m["role"] == "tool")
        self.assertIn("recipes", tool_msg["content"])
        self.assertEqual(srv.requests[0]["messages"][0]["role"], "system")
        self.assertIn("Form Studio", srv.requests[0]["messages"][0]["content"])
        self.assertIn("form_overview", [t["function"]["name"] for t in srv.requests[0]["tools"]])
        # the next message continues the same API history
        job2 = wait(c.send("And now?", job.conversation, ask=False), 300)
        self.assertEqual(job2.state, "done", job2.error)
        msgs = srv.requests[-1]["messages"]
        self.assertEqual([m["role"] for m in msgs if m["role"] == "user"][-2:], ["user", "user"])
        self.assertIn("What can you make?", json.dumps(msgs))
        self.assertTrue(list((self.data / ".conversations" / job.conversation / ".api").glob("*.json")))

    def test_anthropic_wire_keeps_thinking_and_streams_tool_input(self):
        srv = self.serve(wire="anthropic", key="k", models=[{"id": "claude-x-1", "display_name": "Claude X 1",
                                                             "capabilities": {"image_input": {"supported": True}}}], script=[
            {"thinking": "Check the recipes first.", "text": "One moment.", "tools": [("describe_recipe", {"recipe": "hook"})]},
            {"text": "A hook has these parameters."}])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            c = self.chat_with("anthropic", srv.url)
            job = wait(c.send("What does a hook take?", ask=False), 300)
        self.assertEqual(job.state, "done", job.error)
        first, second = srv.requests
        self.assertEqual({k.lower(): v for k, v in srv.headers[0].items()}.get("anthropic-version"), prov.ANTHROPIC_VERSION)
        self.assertEqual(first["cache_control"], {"type": "ephemeral"})
        self.assertIn("Form Studio", first["system"])
        asst = second["messages"][1]
        self.assertEqual(asst["role"], "assistant")
        self.assertEqual(asst["content"][0], {"type": "thinking", "thinking": "Check the recipes first.", "signature": "sig-1"},
                         "thinking blocks go back unchanged")
        tu = next(b for b in asst["content"] if b["type"] == "tool_use")
        self.assertEqual(tu["input"], {"recipe": "hook"})
        tr = second["messages"][2]["content"][0]
        self.assertEqual((tr["type"], tr["tool_use_id"]), ("tool_result", tu["id"]))
        self.assertIn("hook", json.dumps(tr["content"]))
        items = c.conversation(job.conversation)["items"]
        end = next(e for e in items if e["t"] == "end")
        self.assertEqual(end["label"], "Claude X 1")
        self.assertEqual(end["usage"]["cache_read_tokens"], 80)

    def test_ask_user_reaches_the_conversation_and_the_answer_reaches_the_model(self):
        srv = self.serve(models=[{"id": "m"}], script=[
            {"tools": [("ask_user", {"question": "Which side opens?", "choices": ["Left", "Right"], "allow_text": False})]},
            {"text": "Left it is."}])
        c = self.chat_with("ollama", srv.url)
        job = c.send("Make a box", ask=True)
        t0 = time.time()
        while not job.waiting and time.time() - t0 < 300 and job.state == "running":
            time.sleep(0.05)
        self.assertTrue(job.waiting, job.error)
        self.assertEqual(job.waiting["question"], "Which side opens?")
        c.answer(job.conversation, job.waiting["id"], "", ["Left"])
        wait(job, 300)
        self.assertEqual(job.state, "done", job.error)
        tool_msg = next(m for m in srv.requests[1]["messages"] if m["role"] == "tool")
        self.assertIn("Left", tool_msg["content"])

    def test_refused_key_is_an_error_with_the_fix(self):
        srv = self.serve(models=[{"id": "m"}], script=[{"status": 401, "error": "Incorrect API key provided"}])
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k"}):
            c = self.chat_with("groq", srv.url)
            job = wait(c.send("hi", model="m", ask=False), 300)
        self.assertEqual(job.state, "failed")
        err = next(e for e in c.conversation(job.conversation)["items"] if e["t"] == "error")
        self.assertIn("refused the key", err["text"])
        self.assertIn("Settings", err["hint"])

    def test_stop_ends_the_run(self):
        srv = self.serve(models=[{"id": "m"}], script=[{"text": "Thinking about it", "hold": True}])
        c = self.chat_with("ollama", srv.url)
        job = c.send("slow one", ask=False)
        t0 = time.time()
        while not (job.live and job.live.get("kind") == "text") and time.time() - t0 < 300:
            time.sleep(0.05)
        self.assertTrue(c.stop(job.id))
        wait(job, 60)
        self.assertEqual(job.state, "stopped")

    def test_openrouter_cost_is_reported(self):
        srv = self.serve(models=[{"id": "x/y", "supported_parameters": ["tools"]}], key="k", script=[
            {"text": "Hello.", "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.0123}}])
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}):
            c = self.chat_with("openrouter", srv.url)
            job = wait(c.send("hi", ask=False), 300)
        self.assertEqual(job.state, "done", job.error)
        self.assertAlmostEqual(job.cost, 0.0123)
        self.assertEqual(srv.requests[0]["usage"], {"include": True})


class Shapes(unittest.TestCase):
    """A render from a tool goes back to the model in each provider's own shape, or is described when it cannot take it."""
    C = {"id": "c1", "name": "render", "args": {}}
    IMG = [{"mime": "image/png", "data": "iVBORw0KGgo="}]

    def test_anthropic_tool_result_carries_the_image(self):
        a = ApiAdapter(prov.PROVIDERS["anthropic"])
        msg = a._results(a.p, [(self.C, "Rendered. File: /x.png", self.IMG, False)], True)[0]
        blocks = msg["content"][0]["content"]
        self.assertEqual([b["type"] for b in blocks], ["text", "image"])
        self.assertEqual(blocks[1]["source"]["media_type"], "image/png")

    def test_openai_images_follow_the_tool_messages(self):
        a = ApiAdapter(prov.PROVIDERS["openai"])
        out = a._results(a.p, [(self.C, "Rendered.", self.IMG, False)], True)
        self.assertEqual([m["role"] for m in out], ["tool", "user"])
        self.assertTrue(out[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        text_only = a._results(a.p, [(self.C, "Rendered.", self.IMG, False)], False)
        self.assertEqual([m["role"] for m in text_only], ["tool"])
        self.assertIn("cannot take", text_only[0]["content"])

    def test_errors_are_explained(self):
        from form.agents.api import explain
        p = prov.PROVIDERS["openai"]
        self.assertIn("refused the key", explain(p, prov.ProviderError("x", status=401), "m")["message"])
        self.assertIn("does not offer", explain(p, prov.ProviderError("x", status=404), "m")["message"])
        self.assertIn("rate-limiting", explain(p, prov.ProviderError("x", status=429), "m")["message"])
        self.assertIn("loaded", explain(prov.PROVIDERS["ollama"], prov.ProviderError("x", status=404), "m")["message"])


class Versions(unittest.TestCase):
    def test_outside_the_tested_range(self):
        self.assertIsNone(compat.outside("codex", "0.164.3"))
        self.assertEqual(compat.outside("codex", "0.170.0"), "newer")
        self.assertEqual(compat.outside("codex", "0.120.1"), "older")
        self.assertIsNone(compat.outside("claude", "2.1.400"))
        self.assertIsNone(compat.outside("cursor", "9.9"), "no range: never blamed on the version")

    def test_named_only_when_the_failure_looks_like_an_interface_change(self):
        with mock.patch.object(compat, "version", return_value="0.170.0"):
            x = compat.diagnose("codex", "Codex", "codex", 2, "error: unexpected argument '--skip-git-repo-check' found", 0, 0, "1.2")
            self.assertIn("Codex 0.170.0", x["message"])
            self.assertIn("tested with Codex 0.164.x", x["message"])
            self.assertIn("Update Form Studio", x["hint"])
            self.assertIsNone(compat.diagnose("codex", "Codex", "codex", 1, "Not signed in", 0, 0),
                              "a different failure is not blamed on the version")
            self.assertIsNone(compat.diagnose("codex", "Codex", "codex", 0, "", 0, 5))
            y = compat.diagnose("codex", "Codex", "codex", 1, "", 4, 0)
            self.assertIn("cannot read", y["message"])
        with mock.patch.object(compat, "version", return_value="0.164.1"):
            self.assertIsNone(compat.diagnose("codex", "Codex", "codex", 2, "unknown option --json", 0, 0),
                              "inside the range the CLI's own error is shown as it is")

    def test_chat_shows_it_for_a_cli_that_refuses_a_flag(self):
        from tests.test_conversations import Fake
        with tempfile.TemporaryDirectory() as t:
            data = Path(t)
            fake = Fake(data)
            fake.id = "codex"
            fake.label = "Codex"
            fake.command = lambda run, exe: [exe, "-c", "import sys; print('error: unexpected argument --json', file=sys.stderr); sys.exit(2)"]
            c = chat.Chat({"chat": {"agent": "codex"}}, data, "/nonexistent", adapters={"codex": fake})
            with mock.patch.object(compat, "version", return_value="0.199.0"):
                job = wait(c.send("hi", ask=False))
            self.assertEqual(job.state, "failed")
            err = [e for e in c.conversation(job.conversation)["items"] if e["t"] == "error"][-1]
            self.assertIn("tested with Codex", err["text"])
            self.assertIn("0.199.0", err["text"])


if __name__ == "__main__":
    unittest.main()
