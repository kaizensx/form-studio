"""Linked conversations: threads, forks, migration of older conversations, and a design that moves on (a copy, a
picked concept, a design the agent made, a variant) keeping its conversation linked. A fake agent CLI stands in for
the model; designs are built by the real kernel where a test needs one."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import concepts, config, variants  # noqa: E402
from form.conversations import ConversationError, Conversations  # noqa: E402
from form.studio import Studio  # noqa: E402
from tests.test_conversations import Base, wait  # noqa: E402


class Threads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.s = Conversations(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def _talk(self, project="dock"):
        m = self.s.create(project, "claude", "opus", "high")
        for e in ({"t": "user", "text": "Make it thicker"}, {"t": "text", "text": "Walls are 3 mm now."},
                  {"t": "user", "text": "And a cable slot"}, {"t": "text", "text": "Slot added, 6 mm wide."}):
            self.s.append(m["id"], e)
        return m

    def test_a_new_conversation_is_its_own_thread(self):
        m = self.s.create()
        self.assertEqual((m["thread"], m["parent"], m["fork_event"], m["fork_reason"]), (m["id"], None, None, ""))

    def test_fork_copies_up_to_an_event_and_stays_in_the_thread(self):
        a = self._talk()
        f = self.s.attach(a["id"], name="ref.png", data=b"\x89PNG\r\n\x1a\nxx")
        b = self.s.fork(a["id"], at_event=1, reason="try a lighter one")
        self.assertNotEqual(b["id"], a["id"])
        self.assertEqual((b["thread"], b["parent"], b["fork_event"], b["fork_reason"]), (a["id"], a["id"], 1, "try a lighter one"))
        self.assertEqual((b["project"], b["agent"], b["model"], b["effort"], b["session"]), ("dock", "claude", "opus", "high", None))
        self.assertEqual([e["text"] for e in self.s.events(b["id"])], ["Make it thicker", "Walls are 3 mm now."])
        self.assertEqual((b["messages"], b["events"], b["title"]), (1, 2, self.s.meta(a["id"])["title"]))
        self.assertEqual(self.s.attachment(b["id"], f["file"]).read_bytes(), b"\x89PNG\r\n\x1a\nxx")
        # the original is untouched; a fork of the fork is still in the root's thread
        self.assertEqual(len(self.s.events(a["id"])), 4)
        c = self.s.fork(b["id"], project="dock-copy")
        self.assertEqual((c["thread"], c["parent"], c["project"]), (a["id"], b["id"], "dock-copy"))
        self.assertEqual([m["id"] for m in self.s.thread(c["id"])], [a["id"], b["id"], c["id"]])
        self.assertEqual({m["id"] for m in self.s.list(thread=a["id"])}, {a["id"], b["id"], c["id"]})
        self.assertEqual(self.s.list(thread="000000000000"), [])
        with self.assertRaises(ConversationError):
            self.s.fork(a["id"], at_event=99)
        with self.assertRaises(ConversationError):
            self.s.fork("nope")

    def test_search_returns_one_row_per_thread(self):
        a = self._talk()
        self.s.fork(a["id"])
        other = self.s.create("box")
        self.s.append(other["id"], {"t": "user", "text": "A cable tidy"})
        hits = self.s.list(q="cable")
        self.assertEqual(len(hits), 2)
        self.assertEqual(len({h["thread"] for h in hits}), 2)
        self.assertEqual(len(self.s.list()), 3)             # without a search every branch is listed

    def test_older_conversations_are_migrated(self):
        d = self.data / ".conversations" / "0123456789ab"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": "0123456789ab", "title": "Old talk", "project": "dock",
                                                 "updated": 1, "created": 1, "messages": 1}), encoding="utf-8")
        (d / "events.jsonl").write_text(json.dumps({"t": "user", "text": "hi"}) + "\n", encoding="utf-8")
        m = self.s.meta("0123456789ab")
        self.assertEqual((m["thread"], m["parent"], m["fork_event"], m["fork_reason"]), ("0123456789ab", None, None, ""))
        on_disk = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["thread"], "0123456789ab")            # written back once
        self.assertEqual([x["id"] for x in self.s.list(thread="0123456789ab")], ["0123456789ab"])
        b = self.s.fork("0123456789ab")
        self.assertEqual(b["thread"], "0123456789ab")

    def test_link_follows_the_design_and_remembers(self):
        a = self._talk("concept-a")
        self.s.link(a["id"], "picked")
        self.s.link(a["id"], "picked")
        m = self.s.link(a["id"], "later")
        self.assertEqual((m["project"], m["projects"]), ("later", ["concept-a", "picked"]))
        self.assertEqual([x["id"] for x in self.s.list("later")], [a["id"]])


class AgentMadeDesign(Base):
    def test_a_design_made_in_a_conversation_takes_it_along(self):
        m = self.chat.store.create("old-design", agent="fake")
        j = wait(self.chat.send("make one and render it", m["id"]))
        self.assertEqual(j.state, "done", j.error)
        meta = self.chat.store.meta(m["id"])
        self.assertTrue(meta["project"].startswith("made-"))          # the same conversation, now about the new design
        self.assertEqual(meta["projects"], ["old-design"])
        self.assertEqual(self.chat.store.latest(meta["project"])["id"], m["id"])

    def test_a_branch_hands_its_agent_a_transcript(self):
        j = wait(self.chat.send("First question"))
        b = self.chat.store.fork(j.conversation, reason="another way")
        wait(self.chat.send("Second question", b["id"]))
        self.assertIsNone(self.fake.runs[-1].session)
        self.assertIn("continues from an earlier one", self.fake.runs[-1].message)
        self.assertIn("User: First question", self.fake.runs[-1].message)


class DesignsMoveOn(unittest.TestCase):
    """A copy, a picked concept and a variant record where they came from and keep the conversation linked."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-threads-"))
        cls.data = cls.tmp / "data"
        cls.data.mkdir()
        cls.env = mock.patch.dict(os.environ, {"FORM_DATA": str(cls.data), "FORM_CONFIG": str(cls.tmp / "none.toml")})
        cls.env.start()
        cls.st = Studio(config.load())
        cls.store = Conversations(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_duplicate_records_lineage_and_branches_the_conversation(self):
        p = self.st.create("Desk hook", "storage_box", "", {})
        c = self.store.create(p["id"])
        self.store.append(c["id"], {"t": "user", "text": "Make it deeper"})
        cp = self.st.duplicate_project(p["id"])
        q = self.st.load(cp["id"])
        self.assertEqual(q["lineage"], {"root": p["id"], "parent": p["id"], "parent_rev": p["head"], "via": "duplicate"})
        mine = self.store.list(cp["id"])
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]["thread"], mine[0]["parent"], mine[0]["fork_reason"]), (c["id"], c["id"], "duplicate"))
        self.assertEqual(self.store.events(mine[0]["id"])[0]["text"], "Make it deeper")
        # a copy of the copy still names the first design as its root
        cp2 = self.st.duplicate_project(cp["id"])
        self.assertEqual(self.st.load(cp2["id"])["lineage"]["root"], p["id"])
        self.assertEqual(self.store.list(cp2["id"])[0]["thread"], c["id"])
        self.assertEqual(next(x for x in self.st.list() if x["id"] == cp["id"])["lineage"]["via"], "duplicate")

    def test_a_picked_concept_keeps_the_conversation_that_proposed_it(self):
        from tests.test_start import TINY
        c = self.store.create(None)
        self.store.append(c["id"], {"t": "user", "text": "concepts for a clip"})
        b = concepts.create(self.st, "Clip", TINY[:2])
        self.store.update(c["id"], concepts=[b["id"]])                # what the chat records when propose_concepts runs
        other = self.store.create(b["members"][0]["project"])         # one opened on a concept that was not picked
        picked = b["members"][1]["project"]
        concepts.pick(self.st, b["id"], picked)
        self.assertEqual(self.store.meta(c["id"])["project"], picked)
        self.assertEqual(self.store.meta(other["id"])["project"], picked)
        self.assertEqual(self.st.load(picked)["lineage"], {"root": picked, "parent": None, "parent_rev": None,
                                                            "via": "concept", "group": b["id"]})

    def test_a_variant_records_lineage_and_its_conversation(self):
        p = self.st.create("Bin", "storage_box", "", {})
        key = sorted(self.st.rev(self.st.load(p["id"]))["values"])[0]
        cid = self.store.create(p["id"])["id"]
        with mock.patch.dict(os.environ, {"FORM_CONVERSATION": cid}):
            v = variants.save(self.st, self.st.load(p["id"]), "Thick",
                              {key: self.st.rev(self.st.load(p["id"]))["values"][key] + 1})
        rec = next(x for x in self.st.load(p["id"])["variants"] if x["id"] == v["id"])
        self.assertEqual(rec["lineage"], {"root": p["id"], "parent": p["id"], "parent_rev": p["head"], "via": "variant"})
        self.assertEqual(rec["conversation"], cid)


if __name__ == "__main__":
    unittest.main()
