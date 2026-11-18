"""Library recipes for the home and workshop: hose adapter, self-watering planter, faceted vase.

Real kernel, built in this process (tests/recipe_harness.py): defaults, every option and the extremes build valid
solids, interfaces read back off the solid as intended, and the constraints refuse what would not print.
"""
import math
import unittest

from recipe_harness import BED, build, check, library_contract

from form.recipes import RecipeError, registry


class HoseAdapter(unittest.TestCase):
    rid = "hose_adapter"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        r = registry()[self.rid]
        d = {x["key"]: x["value"] for x in r.derived(m["values"])}
        self.assertAlmostEqual(d["a_size"], 35 + 2 * 0.2)        # a socket over a 35 mm wand
        self.assertAlmostEqual(d["b_size"], 32 - 2 * 0.15)       # a spigot into a 32 mm socket
        self.assertEqual({row["key"] for row in r.measure(m["values"], m["by_feature"])}, {"a_size", "b_size"})

    def test_garden_hose_barbs_both_ends(self):
        check(self, self.rid, fits_a=0, d_a=13, clear_a=-0.2, barbs_a=3, fits_b=0, d_b=19, clear_b=-0.2, barbs_b=3)

    def test_sockets_both_ends_and_plain(self):
        check(self, self.rid, fits_a=1, d_a=50, fits_b=1, d_b=40, collar=0, flutes=0)

    def test_extremes(self):
        check(self, self.rid, d_a=6, fits_a=0, clear_a=0, wall=1.6, len_a=8, collar=0, d_b=60, fits_b=1, len_b=20)
        check(self, self.rid, d_a=120, fits_a=1, d_b=100, fits_b=1, cone=35, flutes=40, taper=2)

    def test_constraints_explain_themselves(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "barbs_a": 2})             # end A is a socket
        self.assertEqual(cm.exception.feature, "barbs")
        self.assertIn("fits_a", cm.exception.params)
        with self.assertRaises(RecipeError):
            r.validate({**r.defaults(), "fits_b": 0, "barbs_b": 6, "len_b": 10})


class PlantPot(unittest.TestCase):
    rid = "plant_pot"

    def parts_fit_the_bed(self, m):
        for s in m["shape"].solids():
            bb = s.bounding_box()
            self.assertLessEqual(max(bb.size.X, bb.size.Y, bb.size.Z), BED)

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid, bed=False)                      # two parts: one plate each on a 180 mm bed
        self.parts_fit_the_bed(m)
        r = registry()[self.rid]
        rows = {x["key"]: x for x in r.measure(m["values"], m["by_feature"])}
        self.assertAlmostEqual(rows["pot_bore"]["modelled"], 90 + 2 * 2.0, 3)
        self.assertIn("seat_d", rows)
        self.assertGreater(r.reservoir_ml(m["values"]), 150)
        a = r.assembly(m["values"])
        self.assertEqual([p.id for p in a.parts], ["reservoir", "pot"])

    def test_smooth_and_small(self):
        check(self, self.rid, flutes=0, bed=False)
        check(self, self.rid, pot_d=40, pot_h=30, res_h=10, drains=0, fill_w=10)

    def test_constraints(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "rim_wall": 2.4, "seat": 1.2, "seat_clear": 0.3})
        self.assertEqual(cm.exception.feature, "seat")
        with self.assertRaises(RecipeError):
            r.validate({**r.defaults(), "pot_d": 40, "pot_h": 140, "taper": 12})


class Vase(unittest.TestCase):
    rid = "vase"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        r = registry()[self.rid]
        do, di = r.steepest(m["values"])
        self.assertLess(max(do, di), math.cos(math.radians(42)))   # no facet steeper than 42° from vertical
        self.assertGreater(r.volume_ml(m["values"]), 300)

    def test_lamp_shade(self):
        m = check(self, self.rid, lamp=1, d_bottom=72, d_belly=150, belly_at=0.8, d_top=160, height=130, twist=0, sides=18, bands=8)
        rows = registry()[self.rid].measure(m["values"], m["by_feature"])
        self.assertEqual(rows[0]["key"], "holder_hole")
        self.assertAlmostEqual(rows[0]["modelled"], 40 + 2 * 0.4, 3)

    def test_styles_and_extremes(self):
        check(self, self.rid, diamond=0, twist=-60, sides=8, bands=6)
        check(self, self.rid, height=40, d_bottom=30, d_belly=30, d_top=30, sides=6, bands=2, twist=0)
        check(self, self.rid, height=175, d_bottom=100, d_belly=170, d_top=150, sides=40, bands=30, twist=90)

    def test_steep_belly_is_refused_with_its_parameters(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "d_bottom": 30, "d_belly": 170, "belly_at": 0.15})
        self.assertEqual(cm.exception.feature, "body")
        self.assertIn("d_belly", cm.exception.params)


if __name__ == "__main__":
    unittest.main()
