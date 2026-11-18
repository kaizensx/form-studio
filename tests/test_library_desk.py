"""Library recipes: phone and tablet stand, box with lid, shelf bracket. Real kernel, built in this process."""
import unittest

from recipe_harness import check, library_contract

from form.recipes import RecipeError, registry


class DeviceStand(unittest.TestCase):
    rid = "device_stand"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        r = registry()[self.rid]
        rows = {x["key"]: x for x in r.measure(m["values"], m["by_feature"])}
        self.assertAlmostEqual(rows["slot_width"]["modelled"], 9.5 + 2 * 0.75, 3)   # device + 2 × clearance, square to it
        self.assertAlmostEqual(rows["plug_slot"]["modelled"], 13.0, 3)
        st = r.statics(m["values"], m["volume"], m["com"])
        self.assertGreater(st["tip_force_n"], 1.0)                                  # a firm tap does not tip it at defaults

    def test_options_and_extremes(self):
        check(self, self.rid, charge=0, seat_h=8)
        check(self, self.rid, lean=8)
        check(self, self.rid, lean=35, depth=150)
        check(self, self.rid, width=150, device_width=250, device_height=180, device_thickness=12, device_mass=500,
              depth=160, back_h=100)
        check(self, self.rid, device_thickness=5, width=40, plug_w=12, lip_t=3, back_t=4, base_t=3, strut_t=3, edge_r=0.6)

    def test_plug_needs_seat_height(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "seat_h": 10})
        self.assertEqual(cm.exception.feature, "cable")
        self.assertIn("seat_h", cm.exception.params)


class StorageBox(unittest.TestCase):
    rid = "storage_box"

    def test_contract(self):
        library_contract(self, self.rid)

    def test_every_lid_at_defaults(self):
        r = registry()[self.rid]
        want = {0: {"groove_w", "lid_w"}, 1: {"skirt_w"}, 2: {"skirt_w", "hole_d"}}
        for lid in (0, 1, 2):
            m = check(self, self.rid, lid=lid)
            rows = {x["key"] for x in r.measure(m["values"], m["by_feature"])}
            self.assertEqual(rows, want[lid], f"lid {lid}")
            a = r.assembly(m["values"])
            self.assertEqual(len(a.parts), 2)
            self.assertEqual(len(a.joints), 1)

    def test_extremes(self):
        for lid in (0, 1):
            check(self, self.rid, bed=False, lid=lid, inner_w=160, inner_d=150, inner_h=120, dividers=5, wall=4, corner_r=15,
                  scoop_r=10, lid_t=4, groove=2)
            check(self, self.rid, lid=lid, inner_w=24, inner_d=24, inner_h=12, label=0, corner_r=3, scoop_r=1)
        check(self, self.rid, lid=2, inner_w=24, inner_d=24, inner_h=14, label=0, corner_r=3, scoop_r=1)
        check(self, self.rid, bed=False, lid=2, inner_w=160, inner_d=150, inner_h=120, dividers=5, wall=4, corner_r=15,
              scoop_r=10, lid_t=4, knuckle_r=4.5, open_deg=170)
        check(self, self.rid, lid=1, dividers=3, label=0)

    def test_sliding_groove_leaves_a_wall(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "wall": 1.8, "groove": 1.0})
        self.assertEqual(cm.exception.feature, "groove")


class ShelfBracket(unittest.TestCase):
    rid = "shelf_bracket"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        r = registry()[self.rid]
        rows = {x["key"]: x for x in r.measure(m["values"], m["by_feature"])}
        self.assertAlmostEqual(rows["screw_hole"]["modelled"], 4.0 + 2 * 0.5, 3)
        st = r.statics(m["values"], m["volume"], m["com"])
        self.assertGreaterEqual(st["safety_factor"], 2.0)
        self.assertTrue(all(c["evidence"] == "model" for c in st["checks"]))

    def test_extremes(self):
        check(self, self.rid, arm=60, height=60, web_r=15, width=12, screw_d=3, screw_head_d=5.5, shelf_depth=80, arm_t=6,
              leg_t=6, edge_r=0.6, load_kg=1)
        check(self, self.rid, arm=170, height=170, web_r=120, width=50, arm_t=25, leg_t=25, screw_d=6, screw_head_d=12,
              shelf_depth=400, load_kg=40, edge_r=4)

    def test_overload_is_flagged(self):
        r = registry()[self.rid]
        m = check(self, self.rid)
        st = r.statics({**m["values"], "load_kg": 40}, m["volume"], m["com"])
        self.assertEqual(st["checks"][0]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
