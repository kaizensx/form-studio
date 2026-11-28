"""A hand feature redefined from its property card (form/feature_redefine.py): its choices read back from its code,
and a change written as edit ops that are previewed in the kernel (nothing saved) and committed as one revision.

A cut through a 60 x 40 x 10 plate goes blind, up to next, up to a face, offset from it, mid-plane, reversed, with a
draft, a second direction and a thin wall, each at the volume worked out by hand; a parameter an option no longer
reads is removed, one it newly reads is added; a revolve goes mid-plane and two ways; a split keeps the other side
and a boolean changes its operation. The route POST /model's sibling, POST /redefine, does the same over HTTP."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-redefine-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from form import config, feature_redefine, modelling, modelling_api  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from test_modelling_more import TOP, circle, rect  # noqa: E402

PI = math.pi


class Redefine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    def setUp(self):
        self.p = modelling.start_from_sketch(self.st, self.id().split(".")[-1], rect(60, 40, name="w"), "extrude",
                                             depth=10)

    def load(self):
        return self.st.load(self.p["id"])

    def vol(self):
        return self.st.head_summary(self.load())["volume_mm3"]

    def add(self, kind, **o):
        p = self.load()
        pl = modelling.plan(self.st, p, kind, [], **o)
        modelling.commit(self.st, p, pl["ops"], p["head"], planned=pl)
        return pl["feature"]

    def options(self, fid):
        p = self.load()
        return feature_redefine.options(self.st.source_text(p), fid, self.st.rev(p)["values"])

    def preview(self, fid, change, values=None):
        p = self.load()
        ops, note = feature_redefine.ops(self.st, p, fid, change, values)
        return modelling.preview(self.st, p, ops), note

    def commit(self, fid, change, values=None):
        p = self.load()
        r = modelling_api.route_post(self.st, p, "redefine", {"feature": fid, "change": change, "values": values or {},
                                                              "expect_head": p["head"]})
        return r

    def test_1_cut_end_conditions_change(self):
        fid = self.add("cut", sketch=circle(3, (15, 20), TOP, name="r"), depth=4)
        o = self.options(fid)
        self.assertEqual((o["kind"], o["end_shown"], o["mode"]), ("cut", "blind", "cut"))
        a, v0 = PI * 9, self.vol()
        cases = [({"end": "through"}, a * 10), ({"end": "next"}, a * 10), ({"end": "mid"}, a * 2),
                 ({"end": "face", "to_at": [30, 20, 0]}, a * 10),
                 ({"end": "offset", "to_at": [30, 20, 0], "offset": 2}, a * 8)]
        for change, want in cases:
            pv, note = self.preview(fid, change)
            self.assertTrue(pv["ok"], (change, pv))
            self.assertAlmostEqual(pv["volume_mm3"]["after"], v0 + a * 4 - want, delta=0.05, msg=change)
            self.assertTrue(note.startswith("Changed Cut 1"), note)
        self.assertEqual(self.vol(), v0)                                   # previews save nothing

    def test_2_commit_adds_and_removes_parameters(self):
        fid = self.add("cut", sketch=circle(3, (15, 20), TOP, name="r"), depth=4)
        a, v0 = PI * 9, self.vol()
        r = self.commit(fid, {"end": "offset", "to_at": [30, 20, 0], "offset": 2})
        self.assertIn("offset from a face", r["said"])
        self.assertAlmostEqual(self.vol(), v0 + a * 4 - a * 8, delta=0.05)
        vals = self.st.rev(self.load())["values"]
        self.assertEqual(vals[f"{fid}_offset"], 2)
        o = self.options(fid)
        self.assertEqual((o["end"], o["offset"], o["offset_key"], o["has_to"]), ("offset", 2, f"{fid}_offset", True))
        # the face stays when only the offset moves (a value), and when the choice changes it is kept
        r = self.commit(fid, {"draft": 5}, {f"{fid}_offset": 3})
        vals = self.st.rev(self.load())["values"]
        self.assertEqual((vals[f"{fid}_offset"], vals[f"{fid}_draft"]), (3, 5))
        self.assertLess(v0 + a * 4 - self.vol(), a * 7)                    # tapered, and 3 mm short of the face
        r = self.commit(fid, {"end": "through", "draft": None})
        vals = self.st.rev(self.load())["values"]
        self.assertNotIn(f"{fid}_offset", vals)
        self.assertNotIn(f"{fid}_draft", vals)
        self.assertAlmostEqual(self.vol(), v0 + a * 4 - a * 10, delta=0.05)

    def test_3_pad_direction_two_and_thin(self):
        fid = self.add("extrude", sketch=rect(20, 10, 5, 5, TOP), depth=8)
        v0 = self.vol()
        pv, _ = self.preview(fid, {"end": "blind", "thin": 1, "thin_mode": "mid"})
        self.assertAlmostEqual(pv["volume_mm3"]["after"] - (v0 - 200 * 8), (21 * 11 - 19 * 9) * 8, delta=0.05)
        pv, _ = self.preview(fid, {"end": "blind", "end2": "blind", "depth2": 4})
        self.assertAlmostEqual(pv["volume_mm3"]["after"], v0, delta=0.05)            # direction 2 is inside the plate
        r = self.commit(fid, {"end": "blind", "end2": "blind", "depth2": 4})
        self.assertIn(f"{fid}_depth2", self.st.rev(self.load())["values"])
        self.assertIn("direction 2", r["said"])
        self.commit(fid, {"end2": None})
        self.assertNotIn(f"{fid}_depth2", self.st.rev(self.load())["values"])

    def test_4_refused_with_the_reason(self):
        fid = self.add("cut", sketch=circle(3, (15, 20), TOP), depth=4)
        with self.assertRaises(StudioError) as e:
            self.preview(fid, {"end": "face"})
        self.assertIn("to_at", str(e.exception))
        pv, _ = self.preview(fid, {"end": "vertex", "to": [0, 0, 20]})
        self.assertFalse(pv["ok"])
        self.assertIn("not ahead of the sketch", pv["refused"])
        with self.assertRaises(StudioError):
            feature_redefine.ops(self.st, self.load(), "extrude_1x", {"end": "through"})

    def test_5_revolve_mid_and_two_ways(self):
        sk = {"plane": {"datum": "XZ", "offset": 0},
              "points": [[10, 0], [20, 0], [20, 30], [10, 30], [0, 0], [0, 40]], "fixed": [0, 4],
              "entities": [{"k": "line", "p": [0, 1]}, {"k": "line", "p": [1, 2]}, {"k": "line", "p": [2, 3]},
                           {"k": "line", "p": [3, 0]}, {"k": "line", "p": [4, 5], "construction": True}],
              "constraints": [{"k": "horizontal", "e": [0]}, {"k": "vertical", "e": [1]}, {"k": "horizontal", "e": [2]},
                              {"k": "vertical", "e": [3]}, {"k": "vertical", "e": [4]}]}
        p = modelling.start_from_sketch(self.st, "Ring", sk, "revolve", axis_entity=4, angle=90)
        self.p = p
        full = PI * (400 - 100) * 30
        self.assertAlmostEqual(self.vol(), full / 4, delta=0.5)
        o = self.options("revolve_1")
        self.assertEqual((o["kind"], o["end"]), ("revolve", "angle"))
        pv, _ = self.preview("revolve_1", {"angle2": 45})
        self.assertAlmostEqual(pv["volume_mm3"]["after"], full * 0.375, delta=0.5)
        self.commit("revolve_1", {"mid": True})
        self.assertTrue(self.options("revolve_1")["mid"])
        self.assertAlmostEqual(self.vol(), full / 4, delta=0.5)

    def test_6_split_and_boolean_choices(self):
        fid = self.add("split", plane="YZ", plane_offset=20, keep="above")
        self.assertAlmostEqual(self.vol(), 40 * 40 * 10, delta=0.05)
        self.assertEqual(self.options(fid)["keep"], "above")
        pv, note = self.preview(fid, {"keep": "below"})
        self.assertAlmostEqual(pv["volume_mm3"]["after"], 20 * 40 * 10, delta=0.05)
        self.assertIn("keep below", note)
        with self.assertRaises(StudioError):
            self.preview(fid, {"keep": "sideways"})
        h = self.load()["head"]
        with self.assertRaises(StudioError) as e:              # XZ, 20 mm along its normal, misses the plate
            self.commit(fid, {"plane": "XZ"})
        self.assertIn("does not cross", str(e.exception))
        self.assertEqual(self.load()["head"], h)
        self.commit(fid, {"keep": "both"})
        self.assertEqual(self.options(fid)["keep"], "both")
        self.assertAlmostEqual(self.vol(), 60 * 40 * 10, delta=0.05)
        bid = self.add("boolean", op="combine", target=[10, 20, 5], tools=[[40, 20, 5]])
        self.assertEqual(self.options(bid)["op"], "combine")
        pv, _ = self.preview(bid, {"op": "intersect"})
        self.assertFalse(pv["ok"])                               # two bodies side by side share nothing

    def test_7_tree_carries_the_options(self):
        fid = self.add("cut", sketch=circle(3, (15, 20), TOP), depth=0)
        rows = {r["id"]: r for r in modelling.tree(self.st, self.load())["features"]}
        self.assertEqual(rows[fid]["options"]["end_shown"], "through")
        self.assertEqual(rows["extrude_1"]["options"]["end_shown"], "blind")


if __name__ == "__main__":
    unittest.main()
