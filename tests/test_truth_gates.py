"""Truth gates: a reply cannot end on a FAIL it did not report, and the money shown is the money spent.

A stand-in agent (tests/fixtures/fake_agent.py) speaks Claude Code's stream-json; no model runs. The cost fixtures are
the end events of two real conversations (their reported total_cost_usd values, in order), not invented numbers.
"""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from form import chat, verdict  # noqa: E402
from form.agents.base import Adapter, Run  # noqa: E402
from form.agents.claude import ClaudeParser, cost_scope  # noqa: E402
from form.conversations import Conversations, migrate_once, run_cost  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_agent.py"

# total_cost_usd of each end event, in order, as two conversations saved them (Claude Code, one resumed session each;
# the second then went on with Codex, which reports no money). The app showed their sum: $18.47 and $46.97.
SOFA = [0.6648620000000001, 0.7698348, 1.2906322000000001, 1.5080958000000002, 2.2230090000000002,
        2.4910902000000004, 4.3118908000000005, 5.214611000000001]
SHOWER = [1.3715521999999998, 2.2449312, 4.547636600000001, None, 6.369638800000001, 6.992473400000001,
          7.248505000000001, 7.696872400000001, 10.4996456]


class Fake(Adapter):
    id, label, cli = "fake", "Fake agent", "python"
    images, cost = True, True

    def __init__(self, data: Path):
        self.data, self.runs = data, []

    def executable(self, cfg):
        return sys.executable

    def models(self, cfg, exe):
        return [{"id": "default", "label": "Default", "note": ""}]

    def command(self, run: Run, exe: str):
        self.runs.append(run)
        return [exe, str(FAKE), str(self.data), run.session or "-", run.model, run.message]

    def parser(self):
        return ClaudeParser()


def wait(job, timeout=30):
    t0 = time.time()
    while job.state == "running" and time.time() - t0 < timeout:
        time.sleep(0.02)
    return job


class ChatBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir()
        self.fake = Fake(self.data)
        self.cfg = {"chat": {"agent": "fake", "model": "default", "effort": ""},
                    "_path": str(Path(self.tmp.name) / "studio.toml")}
        self.chat = chat.Chat(self.cfg, self.data, "/nonexistent/form-mcp", adapters={"fake": self.fake})

    def tearDown(self):
        for j in self.chat.running():
            self.chat.stop(j.id)
            wait(j, 5)
        self.tmp.cleanup()

    def items(self, job):
        return self.chat.conversation(job.conversation)["items"]


class EndOfRunGate(ChatBase):
    def test_reply_that_ends_on_an_unreported_fail_gets_one_continuation(self):
        j = wait(self.chat.send("failcheck make the shower holder"))
        self.assertEqual(j.state, "done", j.error)
        self.assertEqual(len(self.fake.runs), 2)                       # the reply, then exactly one continuation
        evs = self.items(j)
        gates = [e for e in evs if e["t"] == "gate"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["fails"], {"wall-test": ["Thinnest wall: 0.00 mm [computed]"]})
        self.assertTrue(self.fake.runs[1].message.startswith("Form Studio check before this reply ends"))
        self.assertIn("FAIL Thinnest wall: 0.00 mm", self.fake.runs[1].message)
        self.assertEqual(self.fake.runs[1].session, self.fake.runs[0].session or j.session)  # same agent session
        texts = [e["text"] for e in evs if e["t"] == "text"]
        self.assertEqual(texts[0], "Designed.")
        self.assertIn("FAILS at 0.00 mm", texts[-1])                     # the reply ends reporting it
        self.assertEqual(self.chat.unreported(j), {})
        self.assertEqual(sum(1 for e in evs if e["t"] == "end"), 2)

    def test_an_agent_that_ignores_the_gate_gets_no_second_one(self):
        j = wait(self.chat.send("failcheck stubborn"))
        self.assertEqual(j.state, "done", j.error)
        self.assertEqual(len(self.fake.runs), 2)                       # capped: one continuation, never a loop
        self.assertEqual(sum(1 for e in self.items(j) if e["t"] == "gate"), 1)
        self.assertEqual(self.chat.unreported(j), {"wall-stubborn": ["Thinnest wall: 0.00 mm [computed]"]})

    def test_a_reply_that_reports_the_fail_ends_normally(self):
        j = wait(self.chat.send("failcheck ack"))
        self.assertEqual(j.state, "done", j.error)
        self.assertEqual(len(self.fake.runs), 1)
        self.assertFalse(any(e["t"] == "gate" for e in self.items(j)))

    def test_no_fail_no_gate(self):
        j = wait(self.chat.send("Hello there"))
        self.assertEqual((j.state, len(self.fake.runs)), ("done", 1))

    def test_gate_can_be_turned_off(self):
        self.cfg["chat"]["fail_gate"] = False
        j = wait(self.chat.send("failcheck"))
        self.assertEqual((j.state, len(self.fake.runs)), ("done", 1))

    def test_each_run_saves_its_own_spend(self):
        j = wait(self.chat.send("failcheck"))                         # two runs of one session: totals 0.4, 0.8
        ends = [e for e in self.items(j) if e["t"] == "end"]
        self.assertEqual([e["cost_usd"] for e in ends], [0.4, 0.4])
        self.assertEqual([e["cost_total_usd"] for e in ends], [0.4, 0.8])
        j2 = wait(self.chat.send("Again", j.conversation))
        self.assertEqual(j2.cost, 0.25)
        meta = Conversations(self.data).meta(j.conversation)
        self.assertAlmostEqual(meta["cost_usd"], 1.05)
        self.assertAlmostEqual(meta["session_costs"][j.session], 1.05)


class Verdicts(unittest.TestCase):
    def test_digest_lines_dicts_and_proof_sheets(self):
        lines = ["PASS  One valid solid: 1 solid  [computed]", "WARN  Overhangs: 12 mm²  [computed]",
                 "FAIL  Thinnest wall: 0.00 mm  [computed]"]
        led = verdict.lead({"project": "p", "checks": lines})
        self.assertEqual(list(led)[:2], ["verdict", "blocking"])
        self.assertEqual((led["verdict"], led["blocking"]), ("FAIL", ["Thinnest wall: 0.00 mm  [computed]"]))
        self.assertEqual(verdict.lead({"checks": lines[:2]})["verdict"], "WARN")
        self.assertEqual(verdict.lead({"name": "x"})["verdict"], "UNCHECKED")
        rows = [{"status": "FAIL", "label": "Ratchet locks", "value": "tooth 0.3 mm < clearance 0.4 mm",
                 "evidence": "computed"}]
        self.assertEqual(verdict.fails(json.dumps({"project": "q", "checks": rows}))[0]["rows"],
                         ["Ratchet locks: tooth 0.3 mm < clearance 0.4 mm [computed]"])
        proof = {"project": "r", "proof": {"rows": [{"claim": "Thread engages", "verdict": "FAIL", "value": "0 mm³"}]}}
        self.assertEqual(verdict.fails(json.dumps(proof))[0]["rows"], ["Thread engages: 0 mm³"])
        nested = {"head": 3, "project": {"project": "s", "verdict": "PASS", "blocking": [], "checks": lines[:1]}}
        self.assertEqual(verdict.fails(json.dumps(nested)), [{"project": "s", "verdict": "PASS", "rows": []}])
        self.assertEqual(verdict.fails("Rendered.\n" + json.dumps({"project": "t", "checks": lines}))[0]["project"], "t")

    def test_a_later_passing_report_clears_the_fail(self):
        c = chat.Chat({"chat": {}}, Path(tempfile.mkdtemp()), "x", adapters={})
        job = chat.ChatJob("m", "p", None)
        c._note_verdicts(job, {"ok": True}, json.dumps({"project": "p", "checks": ["FAIL  Wall: 0.00 mm  [computed]"]}))
        self.assertEqual(c.unreported(job), {"p": ["Wall: 0.00 mm  [computed]"]})
        c._note_verdicts(job, {"ok": True}, json.dumps({"project": "p", "checks": ["PASS  Wall: 2.00 mm  [computed]"]}))
        self.assertEqual(c.unreported(job), {})

    def test_acknowledgement(self):
        rows = ["Thinnest wall: 0.00 mm [computed]"]
        self.assertFalse(verdict.acknowledged(rows, "Designed. Have a look."))
        self.assertTrue(verdict.acknowledged(rows, "The wall check fails at 0.00 mm."))
        self.assertTrue(verdict.acknowledged(rows, "Thinnest wall is 0 mm: I will thicken it next."))


class Cost(unittest.TestCase):
    def test_claude_code_version_decides_what_the_total_covers(self):
        self.assertEqual(cost_scope("2.1.276"), "call")
        self.assertEqual(cost_scope("2.1.277"), "session")
        self.assertEqual(cost_scope(None), "session")
        p = ClaudeParser()
        p.feed(json.dumps({"type": "system", "subtype": "init", "session_id": "s", "claude_code_version": "2.1.300"}))
        end = p.feed(json.dumps({"type": "result", "total_cost_usd": 1.5, "session_id": "s"}))[0]
        self.assertEqual((end["cost_total_usd"], end["cost_scope"]), (1.5, "session"))

    def test_run_cost(self):
        self.assertEqual(run_cost(0.8, 0.4), 0.4)
        self.assertEqual(run_cost(0.3, None), 0.3)
        self.assertEqual(run_cost(0.3, 0.8), 0.3)                     # the count started over: the run's own

    def _conversation(self, root: Path, values, agents) -> str:
        s = Conversations(root)
        m = s.create("p", "claude", "opus", "")
        for v, a in zip(values, agents):
            s.append(m["id"], {"t": "user", "text": "x"})
            s.append(m["id"], {"t": "end", "cost_usd": v, "agent": a, **({"stopped": True} if v is None and a == "claude" else {})})
        return m["id"]

    def test_migration_recomputes_the_logged_conversations(self):
        root = Path(tempfile.mkdtemp(prefix="form-cost-"))
        try:
            sofa = self._conversation(root, SOFA, ["claude"] * len(SOFA))
            shower = self._conversation(root, SHOWER + [None, None], ["claude"] * len(SHOWER) + ["codex", "codex"])
            s = Conversations(root)
            self.assertAlmostEqual(s.meta(sofa)["cost_usd"], 18.474026, places=5)     # what was shown
            self.assertAlmostEqual(s.meta(shower)["cost_usd"], 46.971255, places=5)
            (root / ".form-migrations.json").write_text(json.dumps({"conversation_designs": {"ts": 1}}))
            migrate_once(root)
            self.assertEqual(round(s.meta(sofa)["cost_usd"], 2), 5.21)
            self.assertEqual(round(s.meta(shower)["cost_usd"], 2), 10.50)
            self.assertFalse(s.meta(shower)["cost_known"])                            # Codex said no money
            done = json.loads((root / ".form-migrations.json").read_text())
            self.assertIn("conversation_costs", done)
            backup = Path(done["conversation_costs"]["backup"])
            self.assertTrue((backup / sofa / "events.jsonl").is_file())
            ends = [e for e in s.events(sofa) if e["t"] == "end"]
            self.assertEqual([e["cost_total_usd"] for e in ends], SOFA)
            self.assertAlmostEqual(sum(e["cost_usd"] for e in ends), SOFA[-1], places=6)
            before = (root / ".conversations" / sofa / "events.jsonl").read_text()
            again = Conversations(root).migrate_costs()                               # idempotent
            self.assertEqual(again["changed"], [])
            self.assertEqual((root / ".conversations" / sofa / "events.jsonl").read_text(), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
