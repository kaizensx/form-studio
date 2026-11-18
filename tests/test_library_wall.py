"""Wall and desk recipes: SKÅDIS pegboard accessory, cable clip, under-desk hanger.

Each builds at its defaults, at every option and at the ends of its ranges, as the declared number of valid solids
on the plate, with every interface dimension reading back off the solid as intended (tests/recipe_harness.py).
"""
import unittest

from recipe_harness import check, library_contract

from form.recipes import RecipeError, registry


class Pegboard(unittest.TestCase):
    rid = "pegboard"

    def test_contract(self):
        library_contract(self, self.rid)

    def test_every_kind_at_defaults(self):
        for kind in (0, 1, 2, 3):
            m = check(self, self.rid, kind=kind)
            self.assertIn("pegs", m["by_feature"], kind)

    def test_extremes(self):
        check(self, self.rid, kind=0, reach=100, arm_t=20, tip_h=40, board_t=6)
        check(self, self.rid, kind=0, reach=20, arm_t=5, tip_h=5, board_t=3, peg_clear=0.6)
        check(self, self.rid, kind=1, cup_d=80, height=120, wall=4)
        check(self, self.rid, kind=1, cup_d=15, height=30, wall=1.3)
        check(self, self.rid, kind=2, width=160, depth=120, holes=12, hole_d=6)
        check(self, self.rid, kind=2, width=30, depth=15, shelf_t=2.4)
        check(self, self.rid, kind=3, width=160, depth=120, height=120)
        check(self, self.rid, kind=3, width=30, depth=15, height=30, columns=1)

    def test_pegs_fit_skadis(self):
        r = registry()[self.rid]
        d = {x["key"]: x["value"] for x in r.derived(r.validate(r.defaults()))}
        self.assertAlmostEqual(d["peg_w"], 4.4)                   # 5 mm slot, 0.3 mm a side
        self.assertAlmostEqual(d["stub"], 5.4)                    # 5 mm board + 0.4 mm
        m = check(self, self.rid, kind=2, width=120)
        self.assertEqual({x["key"]: x["value"] for x in r.derived(m["values"])}["columns_n"], 3)

    def test_constraints_explain(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "kind": 2, "holes": 12, "hole_d": 20})
        self.assertEqual(cm.exception.feature, "holes")
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "kind": 2, "width": 40, "columns": 3})
        self.assertIn("columns", cm.exception.params)


class CableClip(unittest.TestCase):
    rid = "cable_organizer"

    def test_contract(self):
        library_contract(self, self.rid)

    def test_options(self):
        check(self, self.rid)
        check(self, self.rid, screw=1)
        m = check(self, self.rid, mount=1)
        self.assertIn("clamp", m["by_feature"])

    def test_extremes(self):
        check(self, self.rid, cables=8, cable_d=2, snap=0.85, ring=1.3)
        check(self, self.rid, cables=1, cable_d=16, ring=3, length=40)
        check(self, self.rid, mount=1, cables=8, cable_d=4, desk_t=60, jaw=50)
        check(self, self.rid, mount=1, cables=1, desk_t=10, jaw=12)

    def test_opening_narrower_than_cable_and_roof_prints(self):
        r = registry()[self.rid]
        d = {x["key"]: x["value"] for x in r.derived(r.validate(r.defaults()))}
        self.assertLess(d["opening"], r.defaults()["cable_d"])
        with self.assertRaises(RecipeError) as cm:          # too narrow an opening leaves an overhanging bore roof
            r.validate({**r.defaults(), "snap": 0.6})
        self.assertIn("snap", cm.exception.params)


class DeskHanger(unittest.TestCase):
    rid = "desk_hanger"

    def test_contract(self):
        library_contract(self, self.rid)

    def test_mounts(self):
        m = check(self, self.rid)
        self.assertIn("clamp", m["by_feature"])
        m = check(self, self.rid, mount=1)
        self.assertIn("screws", m["by_feature"])

    def test_extremes(self):
        check(self, self.rid, desk_t=60, jaw=80, drop=80, reach=120, arm_t=20, width=70, lip_h=30)
        check(self, self.rid, desk_t=10, jaw=20, drop=15, reach=30, arm_t=6, width=20, lip_h=4, edge=0.4)
        check(self, self.rid, mount=1, plate_len=30, reach=30, width=20)
        check(self, self.rid, mount=1, plate_len=50, reach=115, width=70, plate_t=12)

    def test_statics_state_their_model(self):
        r = registry()[self.rid]
        v = r.validate(r.defaults())
        s = r.statics(v, 1.0, (0, 0, 0))
        self.assertTrue(all(c["evidence"] == "model" for c in s["checks"]))
        self.assertGreater(s["safety_factor"], 2)


if __name__ == "__main__":
    unittest.main()
