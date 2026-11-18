"""Standard features at a picked face (form/feature_helpers.py): screw bosses and snap-fit hooks written into the design's
source, built in the kernel, with their volumes compared with an independent build123d computation."""
import math
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-features-")

from build123d import Align, Box, Cylinder, Pos  # noqa: E402

from form import config, engrave, feature_helpers as fh  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

from test_maker_tools import BLOCK  # noqa: E402

C = (Align.CENTER, Align.CENTER, Align.MIN)


class Specs(unittest.TestCase):
    def test_standard_holes_and_checks(self):
        f = fh.spec("boss", (0, 0, 0), (0, 0, 1), size="M3", hole="tapped")
        self.assertEqual(f["hole_d"], 2.5)
        self.assertEqual(fh.spec("boss", (0, 0, 0), (0, 0, 1), size="M4", hole="clearance")["hole_d"], 4.5)
        row = fh.checks(f, 0.4)[0]
        self.assertAlmostEqual(float(row["value"].split()[0]), (f["outer_d"] - 2.5) / 2, places=2)
        self.assertEqual(row["status"], "PASS")
        thin = fh.spec("boss", (0, 0, 0), (0, 0, 1), size="M3", outer_d=3.0)
        self.assertEqual(fh.checks(thin, 0.4)[0]["status"], "FAIL")

    def test_hook_strain_formula(self):
        f = fh.spec("snap_hook", (0, 0, 0), (0, 0, 1), length=10, thickness=2, lip=1)
        rows = fh.checks(f, 0.4)
        self.assertAlmostEqual(rows[0]["strain"], 1.5 * 2 * 1 / 100)
        self.assertEqual(rows[0]["status"], "FAIL")             # 3 % against the 2 % rule of thumb
        self.assertEqual(rows[0]["evidence"], "heuristic")
        ok = fh.checks(f, 0.4, allow_strain=0.05)[0]
        self.assertEqual((ok["status"], ok["evidence"]), ("PASS", "computed"))

    def test_refuses_bad_input(self):
        for kw in ({"size": "M9"}, {"hole": "glued"}, {"height": 0}, {"outer_d": 2, "size": "M3"}):
            with self.assertRaises(StudioError):
                fh.spec("boss", (0, 0, 0), (0, 0, 1), **kw)
        with self.assertRaises(StudioError):
            fh.spec("rivet", (0, 0, 0), (0, 0, 1))
        with self.assertRaises(StudioError):
            fh.spec("boss", (0, 0, 0), (0, 0, 0))

    def test_block_round_trips_next_to_text(self):
        f = fh.spec("boss", (0, 0, 10), (0, 0, 1))
        f["id"] = "boss_1"
        src = fh.join(BLOCK, [f])
        mk = engrave.mark("HI", (0, -15, 5), (0, -1, 0))
        mk["id"] = "text_1"
        src = engrave.join(src, [mk])
        self.assertEqual(fh.split(src)[1], [f])
        self.assertEqual(engrave.split(src)[1], [mk])
        self.assertEqual(fh.join(engrave.join(src, []), []).strip(), BLOCK.strip())


class OnTheKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Block", BLOCK)["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def _volume(self, p):
        return self.st.analysis(p)["brep"]["volume_mm3"] if hasattr(self.st, "analysis") else None

    def test_1_boss_and_hook_are_features(self):
        st = self.st
        p = st.load(self.pid)
        r = fh.add(st, p, "boss", (15, 0, 10), (0, 0, 1), expect_head=p["head"], size="M3", hole="insert", height=6)
        self.assertEqual(r["features"][0]["id"], "boss_1")
        p = st.load(self.pid)
        r = fh.add(st, p, "snap_hook", (-20, 0, 10), (0, 0, 1), length=12)
        p = st.load(self.pid)
        self.assertEqual([f["id"] for f in fh.list_features(st, p)], ["boss_1", "hook_1"])
        self.assertIn("boss_1", [f.id for f in st.recipe(p).features])
        feats = {m["feature"] for m in st.view(p)["mesh"]}
        self.assertTrue({"boss_1", "hook_1"} <= feats)
        # independent: the boss on the block, built here; its volume is the solid's growth
        b = Box(60, 30, 10, align=C)
        ref = b + Pos(15, 0, 10 - fh.OVERLAP) * Cylinder(4.4, 6 + fh.OVERLAP, align=C) - Pos(15, 0, 10) * Cylinder(2.0, 6.01, align=C)
        v = fh.volumes(fh.list_features(st, p)[0])
        self.assertAlmostEqual(v["hole_mm3"], math.pi * 2.0 ** 2 * 6.01, delta=0.05)
        self.assertAlmostEqual(ref.volume - b.volume, v["added_mm3"] - math.pi * 4.4 ** 2 * fh.OVERLAP - v["hole_mm3"], delta=0.5)

    def test_2_off_the_part_is_refused(self):
        st = self.st
        p = st.load(self.pid)
        with self.assertRaises(StudioError):
            fh.add(st, p, "boss", (300, 0, 10), (0, 0, 1))
        self.assertEqual(st.load(self.pid)["head"], p["head"])

    def test_3_remove(self):
        st = self.st
        p = st.load(self.pid)
        fh.remove(st, p, "boss_1")
        p = st.load(self.pid)
        self.assertEqual([f["id"] for f in fh.list_features(st, p)], ["hook_1"])


if __name__ == "__main__":
    unittest.main()
