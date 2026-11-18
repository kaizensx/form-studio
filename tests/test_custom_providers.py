"""Providers added by URL (form/agents/custom.py) and the model lists the picker shows (form/agents/models.py, api.py).

Every server here is the stand-in in tests/fixtures/fake_provider.py on a free port: detection of each wire format
(OpenAI-, Anthropic-, Gemini-style, Ollama), the errors a person can hit (refused key, wrong address, nothing
listening), saving (the key in the owner-only secrets file, never in providers.json or any answer), the provider as
an agent in chat, a model test on request, and `form providers`. Then the model list: OpenRouter-sized lists, a
Default that is the model last used (or none), and Default labels taken from what each agent itself reported."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import agents, chat, secrets  # noqa: E402
from form.agents import custom  # noqa: E402
from form.agents import providers as prov  # noqa: E402
from form.agents.api import ApiAdapter  # noqa: E402
from form.agents.models import Learned, Recent  # noqa: E402
from tests.fixtures.fake_provider import FakeProvider  # noqa: E402
from tests.test_api_agents import KEYS  # noqa: E402
from tests.test_conversations import wait  # noqa: E402

TOOLS = ["tools", "temperature"]


class Env(unittest.TestCase):
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
        self.tmp.cleanup()

    def serve(self, **kw) -> FakeProvider:
        s = FakeProvider(**kw)
        self.servers.append(s)
        return s


class Detect(Env):
    def test_openai_compatible_found_from_the_bare_address(self):
        srv = self.serve(prefix="/v1", strict=True, models=[
            {"id": "big-coder", "supported_parameters": TOOLS}, {"id": "small-chat", "supported_parameters": TOOLS},
            {"id": "text-embed-3"}])
        got = custom.detect(srv.root)
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["wire"], got["base"], got["count"], got["tools"]), ("openai", srv.root + "/v1", 2, "yes"))
        self.assertEqual(got["message"], "Connected: OpenAI-compatible, 2 models, tools supported")
        self.assertEqual(got["warnings"], [], "the chat endpoint answered the empty request with 400")
        self.assertEqual(srv.requests, [], "detection generates nothing")

    def test_a_pasted_endpoint_url_or_a_server_at_the_root_or_under_api_v1(self):
        for prefix in ("", "/api/v1", "/v1"):
            srv = self.serve(prefix=prefix, strict=True, models=[{"id": "m1"}])
            got = custom.detect(srv.url + "/chat/completions")
            self.assertTrue(got["ok"], (prefix, got))
            self.assertEqual(got["base"], srv.root + prefix)
            self.assertEqual(got["tools"], "unknown", "this server says nothing about tools")
            self.assertIn("tool support not listed", got["message"])

    def test_anthropic_compatible(self):
        srv = self.serve(wire="anthropic", strict=True, key="sk-ant-test", models=[
            {"id": "claude-x-1", "display_name": "Claude X 1", "capabilities": {"image_input": {"supported": True}}}])
        got = custom.detect(srv.url, "sk-ant-test")
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["wire"], got["format"], got["images"]), ("anthropic", "Anthropic-compatible", 1))
        self.assertNotIn("sk-ant-test", json.dumps(got))

    def test_gemini_style_list_uses_its_openai_endpoint(self):
        srv = self.serve(prefix="/v1beta", shape="gemini", key="g", models=[{"id": "gemini-x-pro"}])
        got = custom.detect(srv.url, "g")
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["wire"], got["base"], got["format_id"]), ("openai", srv.url + "/openai", "gemini"))

    def test_ollama_capabilities_say_which_models_call_tools(self):
        srv = self.serve(ollama=True, models=[{"id": "qwen9:8b", "capabilities": ["completion", "tools"]},
                                              {"id": "tiny:1b", "capabilities": ["completion"]}])
        got = custom.detect(srv.root)
        self.assertTrue(got["ok"], got)
        self.assertEqual({m["id"]: m["tools"] for m in got["models"]}, {"qwen9:8b": True, "tiny:1b": False})
        self.assertEqual(got["tools"], "some")
        self.assertIn("tools supported by 1 of 2", got["message"])

    def test_metadata_without_tools_is_said_before_saving(self):
        srv = self.serve(models=[{"id": "a", "supported_parameters": ["temperature"]}])
        got = custom.detect(srv.url)
        self.assertTrue(got["ok"])
        self.assertEqual(got["tools"], "no")
        self.assertTrue(any("tools" in w for w in got["warnings"]))

    def test_refused_key_wrong_address_and_nothing_listening(self):
        srv = self.serve(key="right", models=[{"id": "m"}])
        bad = custom.detect(srv.url, "wrong")
        self.assertEqual((bad["ok"], bad["error"]), (False, "auth"))
        self.assertIn("refused the key (401)", bad["message"])
        none = custom.detect(srv.url)
        self.assertIn("needs an API key", none["hint"])
        odd = self.serve(prefix="/weird/place", strict=True, models=[{"id": "m"}])
        nf = custom.detect(odd.root + "/somewhere")
        self.assertEqual(nf["error"], "not_found")
        self.assertIn("No models list was found", nf["message"])
        gone = self.serve()
        url = gone.url
        gone.close()
        self.servers.remove(gone)
        off = custom.detect(url)
        self.assertEqual(off["error"], "connect")
        self.assertIn("Could not connect", off["message"])
        self.assertEqual(custom.detect("ftp://x")["error"], "bad_url")
        empty = self.serve(models=[])
        self.assertEqual(custom.detect(empty.url)["error"], "no_models")

    def test_addresses_are_tidied(self):
        self.assertEqual(custom.normalize("localhost:8000/v1/models"), "http://localhost:8000/v1")
        self.assertEqual(custom.normalize("api.example.com/v1/"), "https://api.example.com/v1")
        self.assertEqual(custom.candidates("https://h.example")[:2], ["https://h.example", "https://h.example/v1"])


class SaveAndUse(Env):
    def _add(self, **kw):
        srv = self.serve(**kw)
        return srv, custom.save("Team proxy", srv.url, kw.get("key"))

    def test_saved_with_the_key_private_and_never_shown(self):
        srv, done = self._add(key="sk-proxy-secret", models=[{"id": "m1", "supported_parameters": TOOLS}])
        pid = done["provider"]["id"]
        self.assertEqual(pid, "custom-team-proxy")
        self.assertTrue(done["provider"]["key_set"])
        stored = json.loads((self.root / "providers.json").read_text())
        self.assertNotIn("sk-proxy-secret", json.dumps(stored), "the URL file never holds the key")
        self.assertEqual(json.loads((self.root / "secrets.json").read_text())[secrets.custom_name("team-proxy")], "sk-proxy-secret")
        if os.name == "posix":
            self.assertEqual((self.root / "providers.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((self.root / "secrets.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("sk-proxy-secret", json.dumps(custom.listing()))
        # a second one with the same name gets its own id; editing keeps the key when none is pasted
        _, two = self._add(models=[{"id": "x"}])
        self.assertEqual(two["provider"]["id"], "custom-team-proxy-2")
        again = custom.save("Renamed", srv.url, "", pid=pid)
        self.assertEqual((again["provider"]["name"], again["provider"]["key_set"]), ("Renamed", True))
        custom.remove(pid)
        self.assertNotIn(secrets.custom_name("team-proxy"), json.loads((self.root / "secrets.json").read_text()))
        self.assertEqual([p["id"] for p in custom.listing()], ["custom-team-proxy-2"])

    def test_it_is_an_agent_in_chat_and_answers_through_the_real_tools(self):
        srv, done = self._add(key="k", models=[{"id": "proxy-model", "supported_parameters": TOOLS}], script=[
            {"text": "Looking.", "tools": [("form_overview", {})]}, {"text": "Done looking."}])
        pid = done["provider"]["id"]
        ads = agents.refresh({})
        self.assertIn(pid, ads)
        c = chat.Chat({"chat": {"agent": pid}, "data": {"dir": str(self.data)}}, self.data, "/nonexistent", adapters=ads)
        st = next(a for a in c.status()["agents"] if a["id"] == pid)
        self.assertTrue(st["available"], st)
        self.assertEqual((st["label"], st["custom"], st["models"][0]["id"]), ("Team proxy", True, "default"))
        self.assertIn("the only model", st["models"][0]["note"])
        self.assertNotIn('"k"', json.dumps(st))
        job = wait(c.send("What can you make?", ask=False), 90)
        self.assertEqual(job.state, "done", job.error)
        self.assertEqual(srv.headers[0].get("authorization") or srv.headers[0].get("Authorization"), "Bearer k")
        self.assertTrue(any(m["role"] == "tool" for m in srv.requests[1]["messages"]))
        self.assertEqual(Recent(self.data).last(pid), "proxy-model", "a provider's Default is the model last used")
        custom.remove(pid)
        agents.refresh(ads)
        self.assertNotIn(pid, ads)

    def test_testing_a_model_for_tools_is_saved_with_it(self):
        srv, done = self._add(models=[{"id": "m1"}, {"id": "m2"}], script=[
            {"tools": [("ping", {})]}, {"text": "pong, without the tool"}, {"status": 400, "error": "tools are not supported"}])
        pid = done["provider"]["id"]
        self.assertEqual(custom.probe(pid, "m1")["result"], True)
        self.assertEqual(srv.requests[0]["tools"][0]["function"]["name"], "ping")
        self.assertIsNone(custom.probe(pid, "m2")["result"], "an answer without the call proves nothing")
        no = custom.probe(pid, "m2")
        self.assertEqual(no["result"], False)
        self.assertIn("does not take tool calls", no["message"])
        rows = {m["id"]: m for m in ApiAdapter(prov.get(pid)).status({})["models"]}
        self.assertEqual((rows["m1"]["tools"], rows["m2"]["tools"]), (True, False))
        self.assertIn("no tool calls", rows["m2"]["note"])

    def test_form_providers_reads_the_key_from_stdin_only(self):
        srv = self.serve(key="sk-cli-key", models=[{"id": "m1"}])
        env = dict(os.environ)
        r = subprocess.run([sys.executable, "-m", "form", "providers", "add", srv.url, "--name", "Lab box"], input="sk-cli-key\n",
                           capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("sk-cli-key", r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["provider"]["id"], out["detected"]["wire"]), ("custom-lab-box", "openai"))
        r = subprocess.run([sys.executable, "-m", "form", "providers", "list"], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        self.assertEqual([p["name"] for p in json.loads(r.stdout)["providers"]], ["Lab box"])
        r = subprocess.run([sys.executable, "-m", "form", "providers", "test", "custom-lab-box"], capture_output=True, text=True,
                           env=env, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])
        r = subprocess.run([sys.executable, "-m", "form", "providers", "remove", "custom-lab-box"], capture_output=True, text=True,
                           env=env, cwd=ROOT, timeout=60)
        self.assertEqual(json.loads(r.stdout)["providers"], [])


class ModelLists(Env):
    ROUTER = [
        {"id": "openai/gpt-z", "name": "OpenAI: GPT-Z", "created": 30, "supported_parameters": TOOLS,
         "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
        {"id": "openai/gpt-z:batch", "name": "OpenAI: GPT-Z (batch)", "created": 30, "supported_parameters": TOOLS},
        {"id": "anthropic/claude-q", "name": "Anthropic: Claude Q", "created": 10, "supported_parameters": TOOLS},
        {"id": "anthropic/claude-r", "name": "Anthropic: Claude R", "created": 20, "supported_parameters": TOOLS},
        {"id": "zeta/open-1:free", "name": "Zeta: Open 1 (free)", "created": 40, "supported_parameters": TOOLS,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "aleph/chat-only", "name": "Aleph: Chat only", "created": 50, "supported_parameters": ["temperature"]}]

    def router(self):
        srv = self.serve(key="k", models=self.ROUTER, script=[{"text": "hi"}])
        cfg = {"chat": {"openrouter_url": srv.url}, "data": {"dir": str(self.data)}}
        return srv, cfg, ApiAdapter(prov.PROVIDERS["openrouter"])

    def test_big_lists_are_filtered_grouped_and_have_no_surprise_default(self):
        srv, cfg, a = self.router()
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}):
            st = a.status(cfg)
            ids = [m["id"] for m in st["models"]]
            self.assertEqual(ids, ["anthropic/claude-r", "anthropic/claude-q", "openai/gpt-z", "zeta/open-1:free"],
                             "no batch variant, no model without tools; well-known vendors first, newest first in each")
            self.assertTrue(st["pick"], "nothing used yet: the picker asks")
            rows = {m["id"]: m for m in st["models"]}
            self.assertEqual((rows["anthropic/claude-r"]["label"], rows["anthropic/claude-r"]["vendor_label"]), ("Claude R", "Anthropic"))
            self.assertTrue(rows["zeta/open-1:free"]["free"])
            self.assertFalse(rows["openai/gpt-z"]["free"])
            self.assertIn("free", rows["zeta/open-1:free"]["note"])
            job_cfg = dict(cfg)
            c = chat.Chat(job_cfg, self.data, "/nonexistent", adapters={"openrouter": a})
            job = wait(c.send("hi", agent="openrouter", ask=False), 30)
            self.assertEqual(job.state, "failed")
            self.assertIn("Pick a model for OpenRouter", job.error)
            self.assertEqual(srv.requests, [], "nothing was sent to a model nobody chose")
            Recent(self.data).use("openrouter", "openai/gpt-z")
            st = a.status(cfg)
            self.assertFalse(st["pick"])
            self.assertEqual((st["models"][0]["id"], st["models"][0]["label"]), ("default", "Default · GPT-Z"))
            self.assertIn("last used with OpenRouter", st["models"][0]["note"])
            got = Learned(self.data).decorate(st, Recent(self.data))
            self.assertEqual((got["recent"], got["last_model"]), (["openai/gpt-z"], "openai/gpt-z"))

    def test_recent_is_learned_from_saved_replies_but_not_from_failures(self):
        from form.conversations import Conversations
        s = Conversations(self.data)
        m = s.create(None, "claude", "opus")
        s.append(m["id"], {"t": "start", "model": "claude-opus-5-5", "agent": "claude", "asked": "opus", "ts": 5})
        s.append(m["id"], {"t": "end", "agent": "claude", "ts": 6})
        s.append(m["id"], {"t": "start", "model": "x", "agent": "openrouter", "asked": "bad/model", "ts": 7})
        s.append(m["id"], {"t": "end", "agent": "openrouter", "ts": 8})
        s.append(m["id"], {"t": "error", "text": "no such model"})
        r = Recent(self.data)
        r.seed(Learned(self.data))
        self.assertEqual(r.all().keys(), {"claude"})
        self.assertEqual(r.last("claude"), "opus")

    def test_default_shows_the_version_the_agents_own_config_or_report_names(self):
        L = Learned(self.data)
        codex = {"id": "codex", "label": "Codex", "models": [
            {"id": "default", "label": "Default", "note": "From your Codex config: gpt-6.1-sol", "configured": "gpt-6.1-sol",
             "configured_label": "GPT-6.1-Sol"}]}
        self.assertEqual(L.decorate(codex)["models"][0]["label"], "Default · GPT-6.1-Sol")
        L.learn("codex", "default", "gpt-6.1-sol")
        row = L.decorate(codex)["models"][0]
        self.assertEqual((row["label"], row["resolved"]), ("Default · GPT-6.1-Sol", "gpt-6.1-sol"))
        claude = {"id": "claude", "label": "Claude Code", "models": [
            {"id": "default", "label": "Default", "note": "", "configured": "opus"},
            {"id": "opus", "label": "Opus", "alias": True, "note": ""}]}
        L.learn("claude", "opus", "claude-opus-5-5")
        self.assertEqual([m["label"] for m in L.decorate(claude)["models"]], ["Default · Opus 5.5", "Opus 5.5"])
        plain = {"id": "claude", "label": "Claude Code", "models": [{"id": "default", "label": "Default", "note": ""}]}
        self.assertEqual(L.decorate(plain)["models"][0]["label"], "Default",
                         "Opus answered when asked for opus; that says nothing about Default")
        self.assertEqual(L.decorate({"id": "gemini", "label": "Gemini CLI", "models": plain["models"]})["models"][0]["label"],
                         "Default", "never another agent's model")

    def test_codex_default_comes_from_its_config_and_model_cache(self):
        home = self.root / "codex"
        home.mkdir()
        (home / "config.toml").write_text('model = "gpt-9-sol"\n')
        (home / "models_cache.json").write_text(json.dumps({"models": [{"slug": "gpt-9-sol", "display_name": "GPT-9-Sol", "visibility": "list"}]}))
        from form.agents.codex import Codex
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            rows = Codex().models({}, "/bin/true")
        self.assertEqual((rows[0]["configured"], rows[0]["configured_label"]), ("gpt-9-sol", "GPT-9-Sol"))
        self.assertEqual(Learned(self.data).decorate({"id": "codex", "label": "Codex", "models": rows})["models"][0]["label"],
                         "Default · GPT-9-Sol")

    def test_chat_reads_what_it_learned_from_its_own_data_folder(self):
        Learned(self.data).learn("claude", "opus", "claude-opus-5-5")

        class Cli:
            id, label, inline, kind = "claude", "Claude Code", False, "cli"

            def status(self, cfg):
                return {"id": "claude", "label": "Claude Code", "available": True, "cli": "x", "kind": "cli",
                        "models": [{"id": "opus", "label": "Opus", "alias": True, "note": ""}], "efforts": []}
        c = chat.Chat({"chat": {}, "data": {"dir": str(self.root / "elsewhere")}}, self.data, "/x", adapters={"claude": Cli()})
        st = c.status()["agents"][0]
        self.assertEqual((st["models"][0]["label"], st["last_model"]), ("Opus 5.5", "opus"))


if __name__ == "__main__":
    unittest.main()
