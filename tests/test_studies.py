"""The Bench (form/studies.py): one registry of every study, route and document, each entry's state from keys.

Against the real kernel (and the real slicer where one is installed): a registry round trip, the existing work wired
in, and the rule the Bench stands on: no entry shows current for a revision it was not computed from."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from form import studies  # noqa: E402
from form.studio import NODES  # noqa: E402
from test_studio import make_studio  # noqa: E402

CALLS = []


def _probe_run(ctx):
    CALLS.append(ctx.p["head"])
    return {"headline": f"{len(ctx.rev['values'])} values", "evidence": "computed", "data": {"n": len(ctx.rev["values"])}}


def _boom(ctx):
    raise RuntimeError("the study broke")


class Registry(unittest.TestCase):
    def test_builtin_entries_cover_the_existing_work(self):
        ids = {s.id for s in studies.registry()}
        for want in ("checks", "assembly", "proof", "map.thickness", "map.overhang", "fit", "critique", "slice",
                     "simulation", "orientation", "printers", "cost", "lighter", "exports", "threemf", "slicer_project",
                     "freecad", "project_file", "release", "doc.bom", "doc.print_report", "doc.measurement_plan",
                     "instructions", "views", "photo", "turntable", "share", "game"):
            self.assertIn(want, ids)
        for s in studies.registry():
            self.assertIn(s.group, studies.GROUPS)
            self.assertIn(s.by, studies.BY)
            self.assertTrue(s.label and s.doc and s.evidence, s.id)
            if s.by == "engine":
                self.assertTrue(s.run or s.node, s.id)
            for n in s.needs:
                self.assertTrue(n in studies.APPLIES or n in studies.READY, f"{s.id}: unknown need {n}")

    def test_register_validates(self):
        with self.assertRaises(ValueError):
            studies.register(studies.Study("x.bad", "toolbox", "Bad", "d", "computed", run=_probe_run))
        with self.assertRaises(ValueError):
            studies.register(studies.Study("x.bad", "study", "Bad", "d", "computed"))       # nothing runs it


class Bench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.st = make_studio(Path(cls.tmp.name))
        studies.register(studies.Study("test.values", "study", "Values", "Counts the values.", "computed", run=_probe_run,
                                       order=999))
        studies.register(studies.Study("test.boom", "document", "Boom", "Always fails.", "computed", run=_boom, order=999))
        p = cls.st.create("Bench box", "storage_box", purpose="print")
        cls.pid = p["id"]
        cls.st.run_sync(cls.pid)

    @classmethod
    def tearDownClass(cls):
        for sid in ("test.values", "test.boom"):
            studies._REG.pop(sid, None)
        cls.st.kernel.shutdown()
        cls.tmp.cleanup()

    def e(self, sid):
        return next(x for x in studies.listing(self.st, self.st.load(self.pid))["entries"] if x["id"] == sid)

    def test_0_chapters(self):
        """Every entry says which of the four chapters it is in: what shapes the design is Design, the rest by group."""
        es = {x["id"]: x for x in studies.listing(self.st, self.st.load(self.pid))["entries"]}
        self.assertEqual({es[i]["chapter"] for i in studies.DESIGN if i in es}, {"design"})
        self.assertEqual((es["checks"]["chapter"], es["exports"]["chapter"], es["doc.bom"]["chapter"]), ("check", "make", "document"))
        self.assertEqual({es[i]["chapter"] for i in studies.MAKE if i in es}, {"make"})
        self.assertTrue(all(x["chapter"] in ("design", "check", "make", "document") for x in es.values()))

    def test_1_round_trip(self):
        self.assertEqual(self.e("test.values")["state"], "never")
        r = studies.start(self.st, self.pid, "test.values", wait=True)
        self.assertEqual(r["job"]["state"], "done")
        e = self.e("test.values")
        self.assertEqual((e["state"], e["rev"]), ("current", 1))
        self.assertTrue(e["headline"].endswith("values"))
        shown = studies.show(self.st, self.st.load(self.pid), "test.values")
        self.assertEqual(shown["data"]["n"], len(self.st.rev(self.st.load(self.pid))["values"]))
        self.assertEqual([x["ok"] for x in shown["log"]], [True])
        n = len(CALLS)
        again = studies.start(self.st, self.pid, "test.values", wait=True)    # current: not run again
        self.assertTrue(again.get("cached"))
        self.assertEqual(len(CALLS), n)
        studies.start(self.st, self.pid, "test.values", force=True, wait=True)
        self.assertEqual(len(CALLS), n + 1)

    def test_2_a_failure_is_recorded_not_hidden(self):
        r = studies.start(self.st, self.pid, "test.boom", wait=True)
        self.assertEqual(r["job"]["state"], "failed")
        e = self.e("test.boom")
        self.assertEqual(e["state"], "failed")
        self.assertIn("the study broke", e["error"]["message"])

    def test_3_pipeline_entries_read_the_pipeline(self):
        for sid, node in (("checks", "checks"), ("exports", "exports")):
            self.assertEqual(self.e(sid)["state"], self.st.status(self.st.load(self.pid))[node]["state"])
        c = self.e("checks")
        self.assertEqual(c["state"], "current")
        self.assertRegex(c["headline"], r"\d+ pass")
        self.assertEqual(self.e("assembly")["state"], "current")      # the box and its lid are an assembly
        self.assertEqual(self.e("release")["by"], "person")

    def test_4_existing_work_runs_from_the_bench(self):
        for sid in ("map.thickness", "views", "doc.bom", "freecad"):
            r = studies.start(self.st, self.pid, sid, wait=True)
            job = r.get("job")
            self.assertTrue(r.get("cached") or job["state"] == "done", f"{sid}: {job}")
            e = self.e(sid)
            self.assertEqual(e["state"], "current", sid)
            for f in e.get("files") or []:
                self.assertTrue(Path(f).is_file(), f"{sid}: {f}")
        self.assertIn("mm thinnest", self.e("map.thickness")["headline"])
        # work done outside the Bench is found there without computing: the analysis map's own cache
        from form import analysis
        p = self.st.load(self.pid)
        self.assertIsNotNone(analysis.cached_map(self.st, p, "thickness"))

    def test_5_agent_and_person_entries_never_run_here(self):
        r = studies.start(self.st, self.pid, "critique")
        self.assertEqual((r["by"], r["tool"]), ("agent", "critique"))
        r = studies.start(self.st, self.pid, "release")
        self.assertEqual(r["by"], "person")
        self.assertEqual(self.st.load(self.pid)["approvals"], [])

    def test_6_a_commit_makes_every_study_of_the_old_revision_stale(self):
        studies.start(self.st, self.pid, "test.values", wait=True)
        before = {e["id"]: e for e in studies.listing(self.st, self.st.load(self.pid))["entries"]}
        cur = [i for i, e in before.items() if e["state"] == "current" and not e.get("live")]
        self.assertGreaterEqual(len(cur), 6)
        p = self.st.load(self.pid)
        self.st.commit(p, {"inner_w": p["revisions"][-1]["values"]["inner_w"] + 7}, "wider")
        after = {e["id"]: e for e in studies.listing(self.st, self.st.load(self.pid))["entries"]}
        head = self.st.load(self.pid)["head"]
        self.assertEqual(head, 2)
        for i in cur:
            if i in ("project_file",):
                continue
            a = after[i]
            self.assertNotEqual(a["state"], "current", f"{i} still current after the inputs changed")
            if a["state"] in ("stale",) or a.get("state_before") == "stale":
                self.assertEqual(a.get("rev"), 1, f"{i} names the revision it describes")
        for a in after.values():                         # the rule: nothing current for a revision it was not computed from
            if a["state"] == "current" and not a.get("live"):
                self.assertTrue(a["rev"] == head or a.get("note"), a)
        self.assertEqual(after["test.values"]["state"], "stale")
        self.assertEqual(after["checks"]["state"], "stale")

    def test_7_print_studies_do_not_apply_to_a_3d_model(self):
        p = self.st.create("Model box", "storage_box", purpose="model")
        rows = {e["id"]: e for e in studies.listing(self.st, p)["entries"]}
        for sid in ("slice", "simulation", "orientation", "printers", "cost", "map.overhang", "doc.print_report"):
            self.assertEqual(rows[sid]["state"], "n/a", sid)
            self.assertTrue(rows[sid]["why"])
        self.assertNotEqual(rows["map.thickness"]["state"], "n/a")
        with self.assertRaises(Exception):
            studies.start(self.st, p["id"], "slice")


class Headless(unittest.TestCase):
    def test_mcp_tools_are_registered(self):
        from form import mcp_server
        m = mcp_server.build()
        names = {t.name for t in asyncio.run(m.list_tools())}
        self.assertTrue({"list_studies", "run_study", "get_study"} <= names)

    def test_cli_lists_and_refuses_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, FORM_DATA=d, PYTHONPATH=str(ROOT))
            r = subprocess.run([sys.executable, "-m", "form", "study", "list", "nope"], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 2, r.stderr[-800:])
            self.assertIn("error", json.loads(r.stdout))
            st = make_studio(Path(d))
            try:
                p = st.create("Cli box", "storage_box")
            finally:
                st.kernel.shutdown()
            r = subprocess.run([sys.executable, "-m", "form", "study", "list", p["id"]], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            out = json.loads(r.stdout)
            self.assertEqual(out["head"], 1)
            self.assertTrue(all(e["state"] in studies.STATES for e in out["entries"]))
            self.assertIn("checks", {e["id"] for e in out["entries"]})


if __name__ == "__main__":
    unittest.main()
