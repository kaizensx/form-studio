"""Asking the person through the MCP client's own form (elicitation, form mode), with the SDK's Client.

Each case runs twice: over MCP 2026-07-28 (the tool returns an InputRequiredResult and the client calls it again
with the answer) and over the handshake era (the server sends elicitation/create on the session). A client that did
not declare elicitation gets exactly what it got before. Also: tool descriptions and server instructions stay within
what Claude Code reads (4,096 characters), and the always-loaded tools carry anthropic/alwaysLoad."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mcp_types as t
from mcp import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import ask as ask_mod  # noqa: E402
from form import elicit, mcp_server  # noqa: E402

MODES = ("auto", "legacy")          # in process, "auto" speaks 2026-07-28; "legacy" is the initialize handshake


def data(res):
    if res.structured_content is not None:
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads("".join(c.text for c in res.content if getattr(c, "type", "") == "text"))


class Person:
    """Plays the person at the client's form: answers with one action and content, and keeps what it was shown."""

    def __init__(self, action="accept", content=None):
        self.action, self.content, self.seen = action, content, []

    async def __call__(self, context, params):
        self.seen.append(params)
        return t.ElicitResult(action=self.action, content=self.content if self.action == "accept" else None)


class Elicitation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {"FORM_DATA": self.tmp.name, "FORM_REFINE": "off"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop(ask_mod.ENV_DIR, None)
        os.environ.pop("FORM_CONVERSATION", None)
        mcp_server.S["studio"] = None
        self.srv = mcp_server.build()

    def tearDown(self):
        if mcp_server.S["studio"] is not None:
            mcp_server.studio().kernel.stop()
        mcp_server.S["studio"] = None
        self.env.stop()
        self.tmp.cleanup()

    def call(self, tool, args, person=None, mode="auto", setup=None):
        async def go():
            kw = {"elicitation_callback": person} if person is not None else {}
            async with Client(self.srv, mode=mode, **kw) as c:
                if setup:
                    await setup(c)
                return await c.call_tool(tool, args)
        return asyncio.run(go())

    def project(self, name="Box"):
        r = asyncio.run(self.srv.call_tool("create_project", {"name": name, "recipe": "storage_box", "run": False}))
        return data(r)["project"]

    # -- delete_project --------------------------------------------------------------------------------------
    def test_delete_accept_moves_the_folder(self):
        for mode in MODES:
            pid = self.project()
            person = Person("accept", {"confirm": True})
            r = data(self.call("delete_project", {"project": pid}, person, mode))
            self.assertTrue(r["ok"], (mode, r))
            self.assertIn(".trash", r["trash"])
            self.assertFalse((Path(self.tmp.name) / pid).exists())
            msg = person.seen[0].message
            self.assertIn(str(Path(self.tmp.name) / ".trash"), msg)
            self.assertEqual(person.seen[0].requested_schema["properties"]["confirm"]["type"], "boolean")

    def test_delete_decline_cancel_and_unticked_keep_the_project(self):
        for mode in MODES:
            for person in (Person("decline"), Person("cancel"), Person("accept", {"confirm": False})):
                pid = self.project()
                res = self.call("delete_project", {"project": pid}, person, mode)
                self.assertFalse(res.is_error)
                r = data(res)
                self.assertEqual((r["ok"], r["id"]), (False, pid))
                self.assertIn("did not confirm", r["refused"])
                self.assertTrue((Path(self.tmp.name) / pid / "project.json").exists(), (mode, person.action))

    def test_delete_without_the_capability_is_unchanged(self):
        pid = self.project()
        r = data(self.call("delete_project", {"project": pid}))
        self.assertTrue(r["ok"])
        self.assertNotIn("refused", r)
        self.assertFalse((Path(self.tmp.name) / pid).exists())

    def test_delete_in_form_studio_chat_never_shows_a_form(self):
        pid = self.project()
        person = Person("decline")
        with mock.patch.dict(os.environ, {ask_mod.ENV_DIR: str(Path(self.tmp.name) / "asks")}):
            r = data(self.call("delete_project", {"project": pid}, person))
        self.assertTrue(r["ok"])
        self.assertEqual(person.seen, [])

    # -- ask_user --------------------------------------------------------------------------------------------
    def test_ask_user_accept_a_choice(self):
        for mode in MODES:
            person = Person("accept", {"answer": "11 mm"})
            r = data(self.call("ask_user", {"question": "How thick is the phone?", "choices": ["9 mm", "11 mm"],
                                            "why": "It sets the slot."}, person, mode))
            self.assertEqual((r["answered"], r["answer"], r["choices"], r["text"]), (True, "11 mm", ["11 mm"], ""), mode)
            sch = person.seen[0].requested_schema
            self.assertEqual([o["const"] for o in sch["properties"]["answer"]["oneOf"]], ["9 mm", "11 mm"])
            self.assertIn("text", sch["properties"])
            self.assertIn("It sets the slot.", person.seen[0].message)

    def test_ask_user_multi_select_and_free_text(self):
        person = Person("accept", {"answer": ["Left", "Top", "Nope"], "text": "and a lip"})
        r = data(self.call("ask_user", {"question": "Which sides open?", "choices": ["Left", "Right", "Top"],
                                        "multi_select": True}, person))
        self.assertEqual(r["choices"], ["Left", "Top"])
        self.assertEqual(r["answer"], "Left, Top — and a lip")
        self.assertEqual(person.seen[0].requested_schema["properties"]["answer"]["type"], "array")
        person = Person("accept", {"text": "75.6 mm"})
        r = data(self.call("ask_user", {"question": "How wide is it?"}, person))
        self.assertEqual((r["answered"], r["text"]), (True, "75.6 mm"))
        self.assertEqual(person.seen[0].requested_schema["required"], ["text"])

    def test_ask_user_decline_and_cancel_are_answers_not_errors(self):
        for mode in MODES:
            for action, reason in (("decline", "declined"), ("cancel", "cancelled")):
                res = self.call("ask_user", {"question": "Which side?", "choices": ["Left", "Right"]}, Person(action), mode)
                self.assertFalse(res.is_error)
                r = data(res)
                self.assertEqual((r["answered"], r["reason"]), (False, reason))
                self.assertIn("assumed", r["note"])

    def test_ask_user_without_the_capability_is_unchanged(self):
        args = {"question": "Which side?", "choices": ["Left", "Right"]}
        expected = ask_mod.unreachable(ask_mod.question("Which side?", ["Left", "Right"]))
        for mode in MODES:
            res = self.call("ask_user", args, None, mode)
            self.assertEqual(data(res), expected)
            self.assertEqual(json.loads(res.content[0].text), expected)

    def test_a_made_up_answer_on_the_first_call_is_not_taken(self):
        """2026-07-28: an answer counts only with the sealed state this server minted."""
        person = Person("accept", {"answer": "Right"})
        fake = {"answer": t.ElicitResult(action="accept", content={"answer": "Left"})}

        async def go():
            async with Client(self.srv, elicitation_callback=person) as c:
                return await c.call_tool("ask_user", {"question": "Which side?", "choices": ["Left", "Right"]},
                                         input_responses=fake)
        r = data(asyncio.run(go()))
        self.assertEqual(r["choices"], ["Right"])            # the form was still shown, and its answer counts
        self.assertEqual(len(person.seen), 1)

    # -- ask_measurement -------------------------------------------------------------------------------------
    def test_ask_measurement_commits_with_how_it_was_measured(self):
        pid = self.project()
        p = mcp_server.studio().load(pid)
        param = next(iter(mcp_server.studio().rev(p)["values"]))
        spec = mcp_server.studio().recipe(p).spec(param)
        v = round((spec.min + spec.max) / 2, 2)
        for method, source in (("caliper", "measured"), ("datasheet", "specified")):
            person = Person("accept", {"value": v, "method": method})
            r = data(self.call("ask_measurement", {"project": pid, "param": param, "question": "How wide?"}, person))
            self.assertEqual((r["answered"], r["value"], r["source"]), (True, v, source), r)
            self.assertTrue(r["rev"])
            sch = person.seen[0].requested_schema["properties"]
            self.assertEqual((sch["value"]["minimum"], sch["value"]["maximum"]), (spec.min, spec.max))
            self.assertEqual([o["const"] for o in sch["method"]["oneOf"]], ["caliper", "ruler", "datasheet"])
            v = round(v + 0.5, 2)
        head = mcp_server.studio().rev(mcp_server.studio().load(pid))
        self.assertEqual(head["provenance"][param]["source"], "specified")

    def test_ask_measurement_skipped_and_declined_change_nothing(self):
        pid = self.project()
        st = mcp_server.studio()
        param = next(iter(st.rev(st.load(pid))["values"]))
        head0 = st.load(pid)["head"]
        for person, reason in ((Person("accept", {"skipped": True}), "skipped"), (Person("decline"), "declined"),
                               (Person("accept", {"value": 1e9, "method": "ruler"}), "out_of_range")):
            r = data(self.call("ask_measurement", {"project": pid, "param": param, "question": "How wide?"}, person))
            self.assertEqual((r["answered"], r["reason"], r["rev"]), (False, reason, None))
        self.assertEqual(st.load(pid)["head"], head0)

    # -- install_software ------------------------------------------------------------------------------------
    def test_install_asks_with_the_command_and_a_decline_runs_nothing(self):
        with mock.patch("form.installer.run_blocking") as run:
            person = Person("decline")
            r = data(self.call("install_software", {"id": "recon.learned", "confirm": True}, person))
            self.assertFalse(run.called)
        self.assertEqual(r["installed"], False)
        self.assertIn("did not accept", r["refused"])
        msg = person.seen[0].message
        self.assertIn("CC BY-NC 4.0", msg)
        for c in r["would_run"]["commands"]:
            self.assertIn(c, msg)

    def test_install_without_the_capability_is_unchanged(self):
        r = data(self.call("install_software", {"id": "recon.learned"}))
        self.assertEqual(r["refused"], "confirm=True is required.")
        self.assertEqual(set(r), {"installed", "refused", "would_run", "tell_the_user"})

    # -- fetch_link ------------------------------------------------------------------------------------------
    def test_a_large_download_is_asked_first(self):
        url = "https://example.invalid/big.stl"
        with mock.patch.object(elicit, "link_size", return_value=250_000_000):
            person = Person("decline")
            r = data(self.call("fetch_link", {"url": url}, person))
        self.assertEqual((r["fetched"], r["size_bytes"]), (False, 250_000_000))
        self.assertIn("250 MB", person.seen[0].message)

    # -- what Claude Code reads ------------------------------------------------------------------------------
    def test_descriptions_instructions_and_always_loaded_tools(self):
        self.assertLessEqual(len(mcp_server.INSTRUCTIONS), 4096)
        tools = asyncio.run(self.srv.list_tools())
        always = set()
        for tool in tools:
            self.assertLessEqual(len(tool.description or ""), 4096, tool.name)
            if (tool.meta or {}).get("anthropic/alwaysLoad") is True:
                always.add(tool.name)
        self.assertEqual(always, set(mcp_server.ALWAYS_LOAD))

    def test_skills_and_tasks_extensions_register_when_present(self):
        import types
        from mcp.server.extension import Extension

        class Ext(Extension):
            def __init__(self, identifier):
                self.identifier = identifier

        got = {}
        skills = types.ModuleType("form.mcp_skills")
        skills.skills_extension = lambda: Ext("io.modelcontextprotocol/skills")
        tasks = types.ModuleType("form.mcp_tasks")
        tasks.tasks_extension = lambda getter: got.setdefault("getter", getter) and Ext("io.modelcontextprotocol/tasks")
        with mock.patch.dict(sys.modules, {"form.mcp_skills": skills, "form.mcp_tasks": tasks}):
            ids = [e.identifier for e in mcp_server.extensions()]
            mcp_server.build()
        self.assertEqual(ids, ["io.modelcontextprotocol/skills", "io.modelcontextprotocol/tasks"])
        self.assertIs(got["getter"], mcp_server.studio)

    def test_schemas_are_spec_valid(self):
        from mcp_types._v2025_11_25 import PrimitiveSchemaDefinition
        from pydantic import TypeAdapter
        a = TypeAdapter(PrimitiveSchemaDefinition)
        q = ask_mod.question("Which?", ["A", "B"], True)
        mq = ask_mod.measure_question("How wide?", "p", "w", current=3)
        for sch in (elicit.question_schema(q), elicit.question_schema(ask_mod.question("Which?", ["A", "B"])),
                    elicit.measurement_schema(mq, 1, 9), elicit.CONFIRM_DELETE, elicit.install_schema("MIT"),
                    elicit.DOWNLOAD_SCHEMA):
            for prop in sch["properties"].values():
                a.validate_python(prop)


if __name__ == "__main__":
    unittest.main()
