"""The Bench (wave A) lists the work of the waves after it, and a change made by hand makes its results stale.

Mass and inertia and the materials with their sources (wave C, form/massprops.py) and the feature tree's state
(wave B, form/modelling.py) are Bench entries through studies.PROVIDERS. A hand edit (suppress, a picked fillet) is
one revision of the design's code, so every study computed for the revision before it is stale by construction, and
the Features entry says what the hand edit did. Against the real kernel, in a scratch data folder."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from form import materials, massprops, modelling, studies  # noqa: E402
from test_modelling import PLATE  # noqa: E402
from test_studio import make_studio  # noqa: E402


class Providers(unittest.TestCase):
    def test_the_later_waves_register_on_the_bench(self):
        self.assertIn("form.massprops", studies.PROVIDERS)
        self.assertIn("form.modelling", studies.PROVIDERS)
        reg = {s.id: s for s in studies.registry()}
        for sid in ("mass", "materials", "features"):
            self.assertIn(sid, reg)
            self.assertEqual(reg[sid].group, "study")
        self.assertEqual(reg["mass"].tool, "mass_properties")
        self.assertEqual(reg["mass"].evidence, massprops.EVIDENCE_BREP)
        self.assertEqual((reg["mass"].label, reg["mass"].tool), (massprops.BENCH["label"], massprops.BENCH["mcp"]))
        self.assertTrue(reg["materials"].live and reg["features"].live)
        self.assertIn("features", studies.APPLIES)


class HandEditsMakeTheBenchStale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.st = make_studio(Path(cls.tmp.name))
        cls.pid = cls.st.create_design("Bench plate", PLATE, purpose="model")["id"]
        materials.set_appearance(cls.st, cls.pid, "", "keep", "AL-6061")

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()
        cls.tmp.cleanup()

    def p(self):
        return self.st.load(self.pid)

    def e(self, sid):
        return next(x for x in studies.listing(self.st, self.p())["entries"] if x["id"] == sid)

    def test_1_mass_runs_and_is_current(self):
        self.assertEqual(self.e("mass")["state"], "never")
        r = studies.start(self.st, self.pid, "mass", wait=True)
        e = r["entry"]
        self.assertEqual(e["state"], "current")
        self.assertEqual(e["rev"], self.p()["head"])
        self.assertIn(" g · computed", e["headline"])
        self.assertEqual(e["evidence"], massprops.EVIDENCE_BREP)
        want = massprops.compute(self.st, self.p())["total"]["mass_g"]
        self.assertAlmostEqual(e["data"]["total"]["mass_g"], want, places=6)
        m = self.e("materials")
        self.assertEqual(m["state"], "current")
        self.assertIn("AL-6061", [x["id"] for x in studies.show(self.st, self.p(), "materials")["data"]["materials"]])
        f = self.e("features")
        self.assertEqual(f["state"], "current")
        self.assertEqual(f["headline"], "4 built")

    def test_2_a_suppress_by_hand_makes_mass_stale_and_shows_on_the_features_line(self):
        before = self.p()["head"]
        self.assertEqual(self.e("mass")["state"], "current")
        modelling.commit(self.st, self.p(), [{"op": "suppress", "feature": "rib"}])
        self.assertGreater(self.p()["head"], before)
        e = self.e("mass")
        self.assertEqual(e["state"], "stale")
        self.assertEqual(e["rev"], before)                       # it says which revision it describes
        f = self.e("features")
        self.assertEqual(f["headline"], "3 built · 1 suppressed")
        self.assertIn("rib", studies.show(self.st, self.p(), "features")["data"]["suppressed"])

    def test_3_a_material_change_is_a_new_key_never_the_old_result(self):
        al = studies.start(self.st, self.pid, "mass", wait=True)["entry"]
        self.assertEqual(al["state"], "current")
        self.assertNotEqual(massprops.study_key(self.st, self.p()), "")
        k_al = al["key"]
        materials.set_appearance(self.st, self.pid, "", "keep", "PLA")
        e = studies.show(self.st, self.p(), "mass")
        self.assertNotEqual(e["key"], k_al)
        # the geometry of this revision is measured already, so the Bench reads the new material's mass from it
        # (plain Python, no kernel): current for the new key, never the aluminium number
        self.assertEqual(e["state"], "current")
        self.assertIn("PLA", e["headline"])
        self.assertLess(e["data"]["total"]["mass_g"], al["data"]["total"]["mass_g"])

    def test_4_restoring_by_hand_brings_back_the_earlier_result_only_when_the_inputs_match(self):
        modelling.commit(self.st, self.p(), [{"op": "restore", "feature": "rib"}])
        self.assertEqual(self.e("features")["headline"], "4 built")
        self.assertIn(self.e("mass")["state"], ("stale", "current"))
        e = self.e("mass")
        if e["state"] == "current":                              # same code and material as a run before: say so
            self.assertNotEqual(e["rev"], self.p()["head"])
            self.assertIn("inputs are the same", e.get("note", ""))


if __name__ == "__main__":
    os.environ.setdefault("FORM_SKIP_UI", "1")
    unittest.main()
