"""One request, one design: a conversation lists every design it made or touched (`designs`), the MCP server records
each design a tool makes against $FORM_CONVERSATION, the designs one request makes share one family, a brief serves
several designs, several meshes become one design with parts, drafts never show up as empty conversations, and older
conversations get `designs` rebuilt from their events."""
import ast
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import conversations as conv_mod  # noqa: E402
from form.conversations import CREATOR_TOOLS, Conversations  # noqa: E402

try:
    import build123d  # noqa: F401
    HAVE_KERNEL = True
except ImportError:
    HAVE_KERNEL = False


def _project(data: Path, pid: str, name: str = "", lineage=None) -> None:
    from form.studio import SCHEMA
    (data / pid).mkdir(parents=True, exist_ok=True)
    p = {"schema": SCHEMA, "id": pid, "name": name or pid, "recipe": "storage_box", "created": time.time(), "head": 1,
         "revisions": [], "brief": {"text": "", "references": []}}
    if lineage:
        p["lineage"] = lineage
    (data / pid / "project.json").write_text(json.dumps(p), encoding="utf-8")


def _data(res):
    """A tool result as data: its structured content, else the JSON of its first text block."""
    sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        return sc.get("result", sc) if set(sc) == {"result"} else sc
    text = next(c.text for c in res.content if getattr(c, "type", "") == "text")
    return json.loads(text)


def _families(data: Path) -> set:
    out = set()
    for d in data.iterdir():
        f = d / "project.json"
        if f.is_file():
            p = json.loads(f.read_text(encoding="utf-8"))
            if not p.get("concept"):
                out.add((p.get("lineage") or {}).get("root") or p["id"])
    return out


class Designs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.s = Conversations(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_request_one_family_and_every_design_listed(self):
        c = self.s.create(agent="fake")
        self.s.append(c["id"], {"t": "user", "text": "make this editable"})
        for pid in ("wallet-base", "wallet-slider", "wallet-cascade"):
            _project(self.data, pid)
            conv_mod.made(self.data, pid, "made", "reconstruct", conversation=c["id"])
        meta = self.s.meta(c["id"])
        self.assertEqual([e["project"] for e in meta["designs"]], ["wallet-base", "wallet-slider", "wallet-cascade"])
        self.assertEqual({e["role"] for e in meta["designs"]}, {"made"})
        self.assertEqual({e["request"] for e in meta["designs"]}, {0})
        self.assertEqual(meta["project"], "wallet-cascade")                   # the newest is in front
        self.assertEqual(_families(self.data), {"wallet-base"})               # Home: one card
        p = json.loads((self.data / "wallet-slider" / "project.json").read_text())
        self.assertEqual(p["lineage"], {"root": "wallet-base", "parent": "wallet-base", "parent_rev": None, "via": "request"})
        self.assertEqual(p["origin"], {"conversation": c["id"], "request_event": 0, "tool": "reconstruct"})
        # the next request starts its own family; family=False (relation "new") never joins one
        self.s.append(c["id"], {"t": "user", "text": "now a hook"})
        _project(self.data, "hook")
        _project(self.data, "hook-two")
        conv_mod.made(self.data, "hook", "made", "create_design", conversation=c["id"])
        conv_mod.made(self.data, "hook-two", "made", "create_design", conversation=c["id"], family=False)
        self.assertEqual(_families(self.data), {"wallet-base", "hook", "hook-two"})
        # every conversation that touched a design leads back to it
        self.assertEqual(self.s.latest("wallet-base")["id"], c["id"])
        self.assertEqual([m["id"] for m in self.s.list(involving="wallet-slider")], [c["id"]])

    def test_without_a_conversation_nothing_is_recorded(self):
        _project(self.data, "solo")
        with mock.patch.dict(os.environ, {conv_mod.ENV_CONVERSATION: ""}):
            self.assertIsNone(conv_mod.made(self.data, "solo", "made", "create_design"))
        with mock.patch.dict(os.environ, {conv_mod.ENV_CONVERSATION: "not-an-id"}):
            self.assertIsNone(conv_mod.made(self.data, "solo", "made", "create_design"))

    def test_concepts_are_listed_not_put_in_front_and_trash_is_remembered(self):
        c = self.s.create(agent="fake")
        self.s.append(c["id"], {"t": "user", "text": "ideas please"})
        _project(self.data, "front")
        conv_mod.made(self.data, "front", "made", "create_design", conversation=c["id"])
        conv_mod.made(self.data, None, "concept", "propose_concepts", conversation=c["id"], group="abcdef0123")
        _project(self.data, "idea-a")
        conv_mod.made(self.data, "idea-a", "concept", "propose_concepts", conversation=c["id"], group="abcdef0123")
        meta = self.s.meta(c["id"])
        self.assertEqual(meta["project"], "front")
        self.assertEqual([(e.get("project"), e.get("group"), e["role"]) for e in meta["designs"]],
                         [("front", None, "made"), (None, "abcdef0123", "concept"), ("idea-a", "abcdef0123", "concept")])
        (self.data / ".trash").mkdir()
        shutil.move(str(self.data / "front"), str(self.data / ".trash" / "front-20261120T101010Z"))
        self.assertEqual(self.s.mark_trashed("front"), 1)
        ds = self.s.designs(c["id"])
        self.assertEqual((ds[0]["state"], ds[0]["name"]), ("trashed", "front"))

    def test_a_draft_is_never_an_empty_conversation(self):
        d = self.s.create(agent="fake", draft=True)
        self.s.attach(d["id"], name="part.stl", data=b"solid x\nendsolid x\n")
        self.assertTrue(self.s.is_draft(d["id"]))
        self.assertEqual(self.s.list(), [])                                       # attached, not sent: not listed
        self.assertFalse((self.data / ".conversations" / d["id"]).exists())
        self.s.append(d["id"], {"t": "user", "text": "make this editable"})        # sent: now a conversation
        self.assertFalse(self.s.is_draft(d["id"]))
        self.assertEqual([m["id"] for m in self.s.list()], [d["id"]])
        self.assertEqual(len(self.s.attachments(d["id"], [f.name[:6] for f in self.s.files_dir(d["id"]).iterdir()])), 1)
        # cancelled: an old draft is cleared, and no conversation with 0 messages is left behind
        e = self.s.create(agent="fake", draft=True)
        self.s.attach(e["id"], name="x.png", data=b"\x89PNG")
        old = time.time() - 8 * 86400
        os.utime(self.data / ".conversations" / ".drafts" / e["id"] / "meta.json", (old, old))
        self.assertEqual(self.s.prune_drafts(), [e["id"]])
        empty = [m for m in self.s.list(limit=1000) if not m.get("messages")]
        self.assertEqual(empty, [])

    def test_meta_writes_from_two_processes_never_lose_each_other(self):
        """The chat process appends events while the MCP server records designs: one lock across processes."""
        import subprocess
        c = self.s.create(agent="fake")
        self.s.append(c["id"], {"t": "user", "text": "go"})
        code = ("import sys; sys.path.insert(0, %r)\nfrom pathlib import Path\nfrom form.conversations import Conversations\n"
                "s = Conversations(Path(%r))\nfor i in range(60): s.record(%r, 'p%%d' %% i, 'made')\n") % (
            str(ROOT), str(self.data), c["id"])
        for i in range(60):
            _project(self.data, f"p{i}")
        proc = subprocess.Popen([sys.executable, "-c", code])
        for i in range(120):
            self.s.append(c["id"], {"t": "text", "text": f"line {i}"})
        self.assertEqual(proc.wait(60), 0)
        meta = self.s.meta(c["id"])
        self.assertEqual(len(meta["designs"]), 60)
        self.assertEqual(meta["events"], 121)


class Briefs(unittest.TestCase):
    def test_one_brief_serves_three_designs(self):
        from form import config, staged
        from form.studio import Studio
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FORM_DATA": d}):
            st = Studio(config.load())
            b = staged.save_brief(st, "Wallet", "Rebuild three parts of a sliding wallet.")
            staged.save_plan(st, b["id"], [{"id": f"f{i}", "label": "F", "how": "extrude"} for i in range(3)],
                             risks=["loft"])
            for name in ("Base", "Slider", "Cascade"):
                p = st.create(name, "storage_box")
                staged.require_plan(st, name, "", b["id"])                 # still there for the next one
                staged.attach_pending(st, p["id"], b["id"])
                self.assertEqual(st.load(p["id"])["design"]["brief"]["id"], b["id"])
            kept = json.loads((Path(d) / ".briefs" / f"{b['id']}.json").read_text())
            self.assertEqual(kept["used_by"], ["base", "slider", "cascade"])
            # a brief consumed before briefs were kept is found again on the design that took it
            (Path(d) / ".briefs" / f"{b['id']}.json").unlink()
            self.assertEqual(staged.load_brief(st, b["id"])["id"], b["id"])


class CreatorTools(unittest.TestCase):
    """Every MCP tool that returns a new project id links it to the conversation. A new creator tool that does not
    fails here."""
    CREATES = ("st.create(", "st.create_design", "st.duplicate_project", "st.reconstruct", "reconstruct_parts",
               "concepts_mod.create", "concepts_mod.pick", "bundle.import_file", "cand.run")

    def _tools(self) -> dict:
        tree = ast.parse((ROOT / "form" / "mcp_server.py").read_text(encoding="utf-8"))
        src = (ROOT / "form" / "mcp_server.py").read_text(encoding="utf-8")
        out = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and any(
                    isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in node.decorator_list):
                out[node.name] = ast.get_source_segment(src, node)
        return out

    def test_every_creator_tool_links(self):
        tools = self._tools()
        self.assertGreater(len(tools), 60)
        creators = {n for n, body in tools.items() if any(c in body for c in self.CREATES)}
        self.assertEqual(creators, set(CREATOR_TOOLS), "a tool that makes a design must be in CREATOR_TOOLS")
        for name in creators:
            self.assertIn("_made(", tools[name], f"{name} makes a design but does not record it (_made)")

    def test_registered_tools_match(self):
        import anyio
        from form import mcp_server

        async def names():
            return {t.name for t in await mcp_server.build().list_tools()}
        self.assertTrue(set(CREATOR_TOOLS) <= anyio.run(names))


@unittest.skipUnless(HAVE_KERNEL, "needs build123d")
class OverMCP(unittest.TestCase):
    """The real tools, in process, for one conversation ($FORM_CONVERSATION)."""

    def test_tools_link_and_create_design_asks_for_a_relation(self):
        import anyio
        sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
        import fake_agent
        from form import mcp_server
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            store = Conversations(data)
            c = store.create(agent="fake")
            store.append(c["id"], {"t": "user", "text": "a box, then a lid for it"})
            src = fake_agent._source("Block", fake_agent.TINY["Block"][0])
            lid = fake_agent._source("Disc", fake_agent.TINY["Disc"][0])
            with mock.patch.dict(os.environ, {"FORM_DATA": d, conv_mod.ENV_CONVERSATION: c["id"]}):
                mcp_server.S["studio"] = None
                srv = mcp_server.build()

                async def go():
                    r = await srv.call_tool("create_project", {"name": "Box", "recipe": "storage_box", "run": False})
                    box = _data(r)["project"]
                    try:
                        await srv.call_tool("create_design", {"name": "Lid", "source": lid, "run": False})
                        refused = ""
                    except Exception as e:
                        refused = str(e)
                    alt = await srv.call_tool("create_design", {"name": "Block", "source": src, "run": False,
                                                                "relation": "alternative"})
                    block = _data(alt)["project"]
                    part = await srv.call_tool("create_design", {"name": "Lid", "source": lid, "run": False,
                                                                 "relation": "part_of"})
                    dup = await srv.call_tool("duplicate_project", {"project": box})
                    return box, refused, block, _data(part), _data(dup)["id"]
                try:
                    box, refused, block, part, dup = anyio.run(go)
                finally:
                    mcp_server.studio().kernel.stop()
                    mcp_server.S["studio"] = None
            self.assertIn("relation", refused)
            self.assertEqual(part["relation"], "part_of")                     # a part of the design in front: no project
            meta = store.meta(c["id"])
            made = [e["project"] for e in meta["designs"] if e.get("project")]
            self.assertEqual(made, [box, block, dup])
            self.assertEqual(meta["project"], dup)
            pb = json.loads((data / block / "project.json").read_text())
            self.assertEqual(pb["lineage"]["root"], box)                      # one family for the request
            self.assertEqual((pb["lineage"]["via"], pb["multipart"]["parts"][1]["id"]), ("alternative", "lid"))
            pd = json.loads((data / dup / "project.json").read_text())
            self.assertEqual(pd["lineage"]["via"], "duplicate")               # a copy keeps its own lineage
            self.assertEqual(_families(data), {box})


@unittest.skipUnless(HAVE_KERNEL, "needs build123d")
class Replay(unittest.TestCase):
    """The owner's request: three meshes and "make this editable", through Form Studio's chat with the fake agent,
    which calls the real MCP tools."""

    @classmethod
    def setUpClass(cls):
        from tests import recon_fixtures as fx
        cls.src = Path(tempfile.mkdtemp(prefix="replay-src-"))
        cls.meshes = []
        for name, label in (("box_with_holes", "Wallet_Base"), ("stepped_bracket", "Wallet_Slider"),
                            ("filleted_bracket", "Wallet_Cascade")):
            f, _, _ = fx.export(name, cls.src)
            cls.meshes.append(f.rename(cls.src / f"{label}.stl"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def _send(self, text):
        from tests.test_conversations import Fake, wait
        from form import chat
        tmp = Path(tempfile.mkdtemp(prefix="replay-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        data = tmp / "data"
        data.mkdir()
        cfg = {"chat": {"agent": "fake", "model": "default", "effort": ""}, "_path": str(tmp / "studio.toml")}
        ch = chat.Chat(cfg, data, "/nonexistent/form-mcp", adapters={"fake": Fake(data)})
        d = ch.store.create(agent="fake", draft=True)                     # the files are attached first, as in the app
        ids = [ch.store.attach(d["id"], m)["id"] for m in self.meshes]
        j = wait(ch.send(text, d["id"], attachments=ids), 900)
        self.assertEqual(j.state, "done", j.error)
        return ch, data, j

    def test_old_way_one_family_every_design_linked(self):
        ch, data, j = self._send("make this editable")
        reply = next(e["text"] for e in reversed(ch.store.events(j.conversation)) if e["t"] == "text")
        self.assertIn("Refused without a relation: yes", reply)
        projects = {d.name for d in data.iterdir() if (d / "project.json").is_file()}
        self.assertEqual(len(projects), 5, reply)                             # three reconstructions, two designs
        meta = ch.store.meta(j.conversation)
        listed = {e["project"] for e in meta["designs"] if e.get("project")}
        self.assertEqual(len(meta["designs"]), len(projects))
        self.assertEqual(projects - listed, set())                            # 0 unlinked
        self.assertEqual(len(_families(data)), 1)                             # Home: one card
        # one brief served both designs
        briefs = [json.loads(f.read_text()) for f in (data / ".briefs").glob("b-*.json")]
        self.assertEqual(len(briefs), 1)
        self.assertEqual(len(briefs[0]["used_by"]), 2)
        self.assertEqual(briefs[0]["conversation"], j.conversation)
        self.assertEqual([m["id"] for m in ch.store.list()], [j.conversation])      # the draft became it, once sent

    def test_new_way_one_design_three_parts(self):
        ch, data, j = self._send("make this editable together")
        projects = [d.name for d in data.iterdir() if (d / "project.json").is_file()]
        self.assertEqual(len(projects), 1)
        p = json.loads((data / projects[0] / "project.json").read_text())
        self.assertEqual([q["id"] for q in p["multipart"]["parts"]], ["base", "slider", "cascade"])
        self.assertEqual(p["name"], "Wallet")
        self.assertEqual(len(p["brief"]["references"]), 6)                    # each solid read by its part, each mesh
        meta = ch.store.meta(j.conversation)
        self.assertEqual([(e["project"], e["role"]) for e in meta["designs"]], [(projects[0], "made")])
        self.assertEqual(meta["project"], projects[0])
        res = [e for e in ch.store.events(j.conversation) if e["t"] == "result" and e.get("name") == "reconstruct"]
        self.assertEqual(res[0].get("project"), projects[0])                  # the app follows it


class Migration(unittest.TestCase):
    """Older conversations: `designs` from their events, meta and the activity log. Built like the owner's data
    (shapes copied from real conversations; ids invented)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        cdir = self.data / ".conversations"
        t = 1795188849.0

        def conv(cid, meta, events):
            (cdir / cid).mkdir(parents=True)
            base = {"id": cid, "title": "x", "title_auto": True, "thread": cid, "parent": None, "fork_event": None,
                    "fork_reason": "", "project": None, "agent": "codex", "model": "m", "created": t, "updated": t + 900,
                    "pinned": False, "messages": 1, "events": len(events), "preview": ""}
            (cdir / cid / "meta.json").write_text(json.dumps({**base, **meta}))
            (cdir / cid / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        for pid in ("wallet-editable", "wallet-slider-editable", "wallet-cascade-editable", "wallet-cascade-parametric"):
            _project(self.data, pid)
        (self.data / ".trash" / "old-hook-20261117T152121Z").mkdir(parents=True)
        (self.data / ".trash" / "old-hook-20261117T152121Z" / "project.json").write_text(json.dumps({"name": "Old hook"}))
        (self.data / ".activity.jsonl").write_text(json.dumps(
            {"ts": t + 300, "project": "wallet-slider-editable", "kind": "reconstruct", "text": "Reconstructed from the mesh",
             "by": "engine"}) + "\n")
        r = lambda i, name, text, **k: {"t": "result", "id": i, "name": name, "ok": True, "text": text, "ts": t + 10, **k}  # noqa: E731
        conv("c78efb9beec4", {"project": "wallet-cascade-parametric", "projects": []}, [
            {"t": "user", "text": "make this editable", "ts": t},
            {"t": "tool", "id": "a", "name": "reconstruct", "input": "project_or_file=/x/Base.stl layer=2", "ts": t + 1},
            {"t": "tool", "id": "b", "name": "reconstruct", "input": "project_or_file=/x/Slider.stl", "ts": t + 2},
            {"t": "tool", "id": "c", "name": "reconstruct", "input": "project_or_file=/x/Cascade.stl", "ts": t + 3},
            r("a", "reconstruct", '{\n  "project": "wallet-editable",\n  "name": "W"'),
            {"t": "result", "id": "b", "name": "reconstruct", "ok": True, "text": "", "ts": t + 600},   # codex: no text
            r("c", "reconstruct", '{\n  "project": "wallet-cascade-editable"'),
            {"t": "tool", "id": "d", "name": "render", "input": "project=wallet-slider-editable view=sheet", "ts": t + 700},
            r("e", "create_design", '{  "project": "wallet-cascade-parametric",', project="wallet-cascade-parametric"),
            {"t": "tool", "id": "f", "name": "get_project", "input": "project=not-a-project", "ts": t + 800},
        ])
        conv("5c5600ae0bda", {"messages": 0, "updated": t}, [])                 # attached, never sent
        conv("c9d21220b6e0", {"project_was": {"id": "old-hook", "name": "Old hook"}}, [
            {"t": "user", "text": "fix the hook", "ts": t},
            {"t": "tool", "id": "a", "name": "commit_change", "input": "project=wallet-editable", "ts": t + 1}])
        self.s = Conversations(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_designs_rebuilt_drafts_and_one_family(self):
        dry = self.s.migrate(dry_run=True)
        self.assertEqual(dry["drafts"], ["5c5600ae0bda"])
        self.assertFalse(any((self.data / p / "project.json").read_text().count("lineage")
                             for p in ("wallet-slider-editable",)))                # a dry run writes nothing
        rep = self.s.migrate()
        self.assertEqual(rep["conversations"], 3)
        ds = self.s.designs("c78efb9beec4")
        self.assertEqual([(e["project"], e["role"], e["state"]) for e in ds],
                         [("wallet-editable", "made", "live"), ("wallet-slider-editable", "made", "live"),
                          ("wallet-cascade-editable", "made", "live"), ("wallet-cascade-parametric", "made", "live")])
        self.assertEqual(_families(self.data), {"wallet-editable"})
        self.assertEqual(self.s.list(), [m for m in self.s.list() if m.get("messages")])     # no empty conversation
        other = self.s.meta("c9d21220b6e0")
        self.assertEqual([(e["project"], e["state"]) for e in other["designs"]],
                         [("wallet-editable", "live"), ("old-hook", "trashed")])
        self.assertEqual(other["project"], "wallet-editable")         # it leads to its design again
        self.assertEqual(self.s.migrate()["families"], [])            # once is enough

    def test_migration_never_deletes_and_skips_what_it_cannot_read(self):
        """Data safety: malformed conversations are skipped and reported; attachments, linked designs and old drafts
        are never moved or erased; every meta.json it changes is backed up first; it runs once even when an item
        fails, and running it again changes nothing."""
        cdir = self.data / ".conversations"
        t = 1795188849.0

        def raw(cid, meta=None, text=None, events=""):
            (cdir / cid).mkdir(parents=True)
            if text is None:
                text = json.dumps({"id": cid, "title": "x", "project": None, "created": t, "updated": t,
                                   "pinned": False, "messages": 0, "events": 0, **(meta or {})})
            (cdir / cid / "meta.json").write_text(text)
            if events is not None:
                (cdir / cid / "events.jsonl").write_text(events)
        raw("aaaaaaaaaaa1", text="{not json")                                     # malformed: unreadable
        raw("aaaaaaaaaaa2", text="[1, 2]")                                        # malformed: not an object
        raw("aaaaaaaaaaa3", text=json.dumps({"id": "ffffffffffff", "messages": 0}))  # malformed: another id
        raw("aaaaaaaaaaa4", events=None)
        (cdir / "aaaaaaaaaaa4" / "events.jsonl").mkdir()                          # malformed: events unreadable
        raw("bbbbbbbbbbb1")                                                       # counters 0, but a file attached
        (cdir / "bbbbbbbbbbb1" / "files").mkdir()
        (cdir / "bbbbbbbbbbb1" / "files" / "abc123-part.stl").write_text("solid x\nendsolid x\n")
        raw("bbbbbbbbbbb2", {"project": "wallet-editable"})                       # counters 0, linked to a design
        raw("bbbbbbbbbbb3", {"designs": [{"project": "wallet-editable", "role": "made"}]})
        raw("bbbbbbbbbbb4", events=json.dumps({"t": "user", "text": "stale counters", "ts": t}) + "\n")
        old_draft = cdir / ".drafts" / "dddddddddddd"                             # an unsent draft from long ago
        old_draft.mkdir(parents=True)
        (old_draft / "meta.json").write_text(json.dumps({"id": "dddddddddddd", "messages": 0, "draft": True}))
        (old_draft / "files").mkdir()
        (old_draft / "files" / "abc123-photo.png").write_bytes(b"\x89PNG")
        old = time.time() - 30 * 86400
        os.utime(old_draft / "meta.json", (old, old))
        before = {p: p.read_bytes() for p in cdir.rglob("*") if p.is_file()}

        dry = self.s.migrate(dry_run=True)
        self.assertEqual({p: p.read_bytes() for p in cdir.rglob("*") if p.is_file()}, before, "a dry run writes nothing")
        self.assertFalse((self.data / ".backups").exists())
        self.assertEqual(dry["drafts"], ["5c5600ae0bda"])

        rep = conv_mod.migrate_once(self.data)
        self.assertEqual(sorted(x["id"] for x in rep["skipped"]),
                         ["aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa4"])
        self.assertEqual(rep["drafts"], ["5c5600ae0bda"], "only the one with nothing in it")
        for cid in ("aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa4", "bbbbbbbbbbb1", "bbbbbbbbbbb2",
                    "bbbbbbbbbbb3", "bbbbbbbbbbb4"):
            self.assertTrue((cdir / cid / "meta.json").is_file(), cid)
        self.assertEqual((cdir / "aaaaaaaaaaa1" / "meta.json").read_text(), "{not json", "a bad one is left as it was")
        self.assertTrue((cdir / "bbbbbbbbbbb1" / "files" / "abc123-part.stl").is_file())
        self.assertTrue((old_draft / "files" / "abc123-photo.png").is_file(), "the migration prunes no draft")
        self.assertFalse((self.data / ".trash" / "conversations").exists())
        # backups: every meta.json it changed, as it was before
        bdir = Path(rep["backup"])
        self.assertEqual(bdir.parent, self.data / ".backups")
        self.assertTrue(bdir.name.startswith("migration-"))
        for cid in ("5c5600ae0bda", "c78efb9beec4", "c9d21220b6e0"):
            self.assertEqual((bdir / cid / "meta.json").read_bytes(), before[cdir / cid / "meta.json"], cid)
        self.assertTrue((bdir / "projects" / "wallet-slider-editable" / "project.json").is_file())
        # recorded as done although four failed: no retry at the next start, and a second run changes nothing
        done = json.loads((self.data / ".form-migrations.json").read_text())
        self.assertEqual(len(done[conv_mod.MIGRATION_KEY]["skipped"]), 4)
        self.assertIsNone(conv_mod.migrate_once(self.data))
        snap = {p: p.read_bytes() for p in self.data.rglob("*") if p.is_file() and ".backups" not in p.parts}
        again = self.s.migrate()
        self.assertEqual((again["drafts"], again["rebuilt"], again["families"]), ([], [], []))
        self.assertIsNone(again["backup"])
        self.assertEqual({p: p.read_bytes() for p in self.data.rglob("*") if p.is_file() and ".backups" not in p.parts},
                         snap, "running it again changes nothing")

    def test_a_migration_that_fails_outright_is_still_recorded(self):
        with mock.patch.object(Conversations, "migrate", side_effect=RuntimeError("boom")):
            rep = conv_mod.migrate_once(self.data)
        self.assertIn("boom", rep["error"])
        self.assertIsNone(conv_mod.migrate_once(self.data), "it does not retry at every start")

    def test_old_drafts_go_to_the_trash_not_away(self):
        d = self.s.create(agent="fake", draft=True)
        self.s.attach(d["id"], name="x.png", data=b"\x89PNG")
        old = time.time() - 8 * 86400
        os.utime(self.data / ".conversations" / ".drafts" / d["id"] / "meta.json", (old, old))
        self.assertEqual(self.s.prune_drafts(), [d["id"]])
        moved = list((self.data / ".trash" / "conversations").iterdir())
        self.assertEqual(len(moved), 1)
        self.assertTrue(moved[0].name.startswith(d["id"] + "-"))
        self.assertEqual([f.read_bytes() for f in (moved[0] / "files").iterdir()], [b"\x89PNG"])

    @unittest.skipUnless(os.environ.get("FORM_MIGRATION_COPY"), "set FORM_MIGRATION_COPY to a COPY of a data folder")
    def test_on_a_copy_of_real_data(self):
        """Every conversation with a project id in its events lists it. Runs on a copy; the copy is copied again."""
        import re
        src = Path(os.environ["FORM_MIGRATION_COPY"])
        self.assertNotEqual(src.resolve(), (Path.home() / "FORM").resolve(), "never on the real folder")
        work = self.data / "copy"
        shutil.copytree(src, work)
        s = Conversations(work)
        s.migrate()
        for m in s.list(limit=10000):
            ids = set()
            for e in s.events(m["id"]):
                if e.get("project"):
                    ids.add(e["project"])
                ids |= set(re.findall(r"\bproject(?:_or_file)?=([a-z0-9][a-z0-9-]{0,60})(?=\s|$)", str(e.get("input") or "")))
            ids = {i for i in ids if conv_mod._state_of(work, i)[0] != "gone"}
            listed = {e.get("project") for e in m.get("designs") or []}
            self.assertEqual(ids - listed, set(), m["id"])


if __name__ == "__main__":
    unittest.main()
