"""Function checks: a thread that engages is told apart from a plain hole, a ratchet that locks from one whose teeth
are lower than its play. Real kernel (build123d); no app, no agent."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build123d import Align, Box, Cylinder, Pos  # noqa: E402

from form import function_checks as fc  # noqa: E402
from form import parts  # noqa: E402
from form.craft import mechanisms as mech  # noqa: E402
from form.recipes.assembly import Mate  # noqa: E402

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def _nut(cutter_shape, h=10):
    """A 16 mm block whose top is z = 0, with the cutter (opening at z = 0, going down) taken out."""
    return Pos(0, 0, -h) * Box(16, 16, h, align=BOTTOM) - cutter_shape


class InternalThreadHelper(unittest.TestCase):
    """parts.thread(external=False) returned a plain bore: OCCT's cut of the bore by the helical ridges failed
    without an error, so a hole made with it had no thread (the shower holder's "holes don't have threads")."""

    def test_the_cutter_keeps_the_ridges(self):
        for d, p, L in ((8, 1.25, 10), (12, 1.75, 12), (5, 0.8, 8)):
            c = parts.thread(d, p, L, external=False)
            r = c["modelled_major_d"] / 2
            plain = math.pi * r * r * (L + parts.OVERSHOOT)
            self.assertTrue(c.shape.is_valid)
            self.assertLess(c.shape.volume, plain * 0.97, f"M{d}x{p}: the cutter is a plain bore")

    def test_a_hole_cut_with_it_has_ridges_inside_the_major_diameter(self):
        c = parts.thread(8, 1.25, 10, external=False)
        nut = _nut(c.shape)
        inside = nut & (Pos(0, 0, -10) * Cylinder(c["modelled_major_d"] / 2 - 0.05, 10, align=BOTTOM))
        self.assertGreater(inside.volume, 20.0)


class ThreadEngagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rod = Pos(0, 0, -10) * parts.thread(8, 1.25, 10, external=True).shape
        cls.threaded = _nut(parts.thread(8, 1.25, 10, external=False).shape)
        cls.plain = _nut(Pos(0, 0, -10) * Cylinder(4.15, 10.2, align=BOTTOM))

    def test_engaging_thread_passes(self):
        row = fc.thread_engagement(self.rod, self.threaded, pitch=1.25)
        self.assertEqual(row["status"], "PASS", row)
        self.assertEqual(row["evidence"], "computed")

    def test_plain_hole_fails(self):
        row = fc.thread_engagement(self.rod, self.plain, pitch=1.25)
        self.assertEqual(row["status"], "FAIL", row)
        self.assertIn("plain bore", row["detail"])

    def test_declared_mate_runs_it(self):
        from form import assembly

        class Bud:
            def over(self):
                return False

        a = {"placed": [self.plain, self.rod]}
        m = Mate("nut", "bolt", "thread", axis=(0, 0, 1), origin=(0, 0, 0))
        row = assembly._function_row(m, a, ["nut", "bolt"], {"nut": "Clamp", "bolt": "Bolt"}, Bud())
        self.assertEqual((row["id"], row["status"]), ("fn_thread_nut_bolt", "FAIL"))
        a = {"placed": [self.threaded, self.rod]}
        self.assertEqual(assembly._function_row(m, a, ["nut", "bolt"], {"nut": "Clamp", "bolt": "Bolt"}, Bud())["status"],
                         "PASS")
        self.assertIsNone(assembly._function_row(Mate("nut", "bolt", "pin"), a, ["nut", "bolt"], {}, Bud()))


def _pawl(reach_to_r: float, R: float):
    """A pawl block on the +X side whose tip reaches radius reach_to_r (its root side lies outside the wheel)."""
    return Pos(reach_to_r, 0, 0) * Box(R + 10 - reach_to_r, 3, 6, align=(Align.MIN, Align.CENTER, Align.MIN))


class RatchetLocks(unittest.TestCase):
    def test_deep_teeth_lock(self):
        w = mech.ratchet(teeth=16, od=40, tooth_h=3, thickness=6, bore=8).shapes["wheel"]
        row = fc.ratchet_engagement(w, _pawl(20 - 2.2, 20), clearance=0.3)
        self.assertEqual(row["status"], "PASS", row)

    def test_low_teeth_with_play_do_not_lock(self):
        """The shower holder's ratchet: "teeth too low, doesn't lock, has play"."""
        w = mech.ratchet(teeth=16, od=40, tooth_h=0.8, thickness=6, bore=8).shapes["wheel"]
        row = fc.ratchet_engagement(w, _pawl(20 - 0.5, 20), clearance=0.3)
        self.assertEqual(row["status"], "FAIL", row)
        self.assertEqual(row["evidence"], "heuristic")
        self.assertIn("ride over", row["detail"])


class Snap(unittest.TestCase):
    def test_strain_is_heuristic(self):
        self.assertEqual(fc.snap_strain(1.6, 0.8, 12)["status"], "PASS")
        self.assertEqual(fc.snap_strain(2.5, 1.5, 8)["status"], "FAIL")
        self.assertEqual(fc.snap_strain(1.6, 0.8, 12)["evidence"], "heuristic")


if __name__ == "__main__":
    unittest.main()
