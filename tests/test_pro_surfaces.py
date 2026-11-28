"""The pro-density surfaces' engine side (form/proapi.py, form/geomdiff.py, form/resultview.py).

The compare sheet's record of two revisions: which features were added, removed, changed (and why), suppressed or the
same; the parameters that changed; the design source as a line diff. The geometric diff now also carries both
solids' boxes and body counts. The PMI section reads what the drawing declares without drawing it."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-pro-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import config, edits, geomdiff, modelling, proapi  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

PLATE = '''
from build123d import Box, Cylinder, Pos
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param


class Design(FeatureDesign):
    title = "Plate"
    params = [Param("w", "Width", 60, 30, 110, 1, "mm", "form", "body"),
              Param("hole_d", "Hole", 5, 2, 10, 0.1, "mm", "form", "holes")]

    @feature("Body")
    def body(self, v, body):
        return Box(v["w"], 40, 10)

    @feature("Holes", role="interface")
    def holes(self, v, body):
        return body - Pos(v["w"] / 4, 0, 0) * Cylinder(v["hole_d"] / 2, 20)

    @feature("Rib")
    def rib(self, v, body):
        return body + Pos(0, 0, 8) * Box(v["w"], 4, 6)

    def drawing(self, v):
        return {"datums": [{"letter": "A", "at": {"feature": "body", "normal": [0, 0, -1]}}],
                "fits": [{"param": "hole_d", "class": "H7"}], "notes": ["Break sharp edges"]}
'''


class ScriptDiff(unittest.TestCase):
    """No kernel: the line diff the Script view draws."""

    def test_rows(self):
        a = "\n".join(f"line {i}" for i in range(20))
        b = a.replace("line 10", "line ten") + "\nline 20"
        d = proapi.script_diff(a, b)
        self.assertEqual((d["added"], d["removed"]), (2, 1))
        kinds = [r["t"] for r in d["rows"]]
        self.assertIn("gap", kinds, "two changes far apart are two hunks")
        dl = next(r for r in d["rows"] if r["t"] == "del")
        self.assertEqual((dl["a"], dl["b"], dl["text"]), (11, None, "line 10"))
        ad = [r for r in d["rows"] if r["t"] == "add"]
        self.assertEqual([r["b"] for r in ad], [11, 21])
        self.assertTrue(proapi.script_diff(a, a)["same"])


class Compare(unittest.TestCase):
    """The kernel builds: one design, a value change, a feature added by hand, one suppressed."""

    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        p = cls.st.create_design("Plate", PLATE, purpose="model")
        cls.pid = p["id"]
        cls.st.commit(cls.st.load(cls.pid), {"hole_d": 6.5}, note="bigger hole")              # r02
        p = cls.st.load(cls.pid)
        modelling.commit(cls.st, p, [{"op": "suppress", "feature": "rib"}], p["head"], "you")    # r03
        p = cls.st.load(cls.pid)
        code = ('@feature("Boss")\ndef boss(self, v, body):\n'
                '    from build123d import Cylinder, Pos\n    return body + Pos(-20, 0, 8) * Cylinder(4, 6)\n')
        edits.edit(cls.st, p, [{"op": "insert", "feature": "boss", "code": code, "label": "Boss"}], p["head"],
                   "Added a boss", "you", False, None, "warn")                                     # r04

    def test_values(self):
        c = proapi.compare(self.st, self.st.load(self.pid), 1, 2)
        self.assertEqual([(x["key"], x["from"], x["to"], x["feature"]) for x in c["params"]], [("hole_d", 5, 6.5, "holes")])
        st = {f["id"]: f for f in c["features"]}
        self.assertEqual(st["holes"]["state"], "changed")
        self.assertIn("Hole", st["holes"]["why"])
        self.assertEqual(st["body"]["state"], "same")
        self.assertTrue(c["script"]["same"], "a value change leaves the source as it was")

    def test_features_and_script(self):
        c = proapi.compare(self.st, self.st.load(self.pid), 2, 4)
        st = {f["id"]: f["state"] for f in c["features"]}
        self.assertEqual(st, {"body": "same", "holes": "same", "rib": "suppressed", "boss": "added"})
        added = [r["text"] for r in c["script"]["rows"] if r["t"] == "add"]
        self.assertTrue(any("def boss" in t for t in added), added)
        back = proapi.compare(self.st, self.st.load(self.pid), 4, 2)
        self.assertEqual({f["id"]: f["state"] for f in back["features"]}["boss"], "removed")
        with self.assertRaises(StudioError):
            proapi.compare(self.st, self.st.load(self.pid), 2, 2)

    def test_geomdiff_sizes_and_bodies(self):
        p = self.st.load(self.pid)
        d = geomdiff.compute(self.st, p, 1, 2)
        self.assertEqual((d["solids_a"], d["solids_b"]), (1, 1))
        size = [hi - lo for lo, hi in zip(*d["bbox_a"])]
        self.assertAlmostEqual(size[0], 60, 2)
        self.assertAlmostEqual(size[2], 16, 2, "the plate spans z -5..5 and the rib reaches z 11")
        self.assertLess(d["net_mm3"], 0, "a bigger hole takes material away")

    def test_pmi(self):
        m = proapi.pmi(self.st, self.st.load(self.pid))
        self.assertEqual([x["letter"] for x in m["datums"]], ["A"])
        self.assertEqual([(x["param"], x["class"], x["by"]) for x in m["fits"]], [("hole_d", "H7", "design")])
        self.assertEqual([x["text"] for x in m["notes"]], ["Break sharp edges"])
        self.assertEqual(m["count"], 3)


if __name__ == "__main__":
    unittest.main()
