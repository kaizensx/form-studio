"""Storage recipes of the built-in library: Gridfinity bin and baseplate, battery and card holder.

Each builds at its defaults and at the ends of its main ranges with the real kernel, and its interface dimensions
(magnet pockets, sockets, battery pockets) read back off the solid as intended. See tests/recipe_harness.py.
"""
import unittest

from recipe_harness import build, check, library_contract

from form.recipes import RecipeError, registry


class GridfinityBin(unittest.TestCase):
    rid = "gridfinity_bin"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        lo, hi = m["bbox"]
        self.assertAlmostEqual(hi[0] - lo[0], 2 * 42 - 0.5, 3)          # 42 n − 0.5 (spec)
        self.assertAlmostEqual(hi[2] - lo[2], 6 * 7 + 4.0, 3)           # 7 mm units + the truncated lip
        keys = {r["key"] for r in registry()[self.rid].measure(m["values"], m["by_feature"])}
        self.assertEqual(keys, {"magnet_hole"})

    def test_short_bins_keep_a_smaller_tab_and_scoop(self):
        r = registry()[self.rid]
        v = r.validate({**r.defaults(), "height_u": 3})
        d = {x["key"]: x["value"] for x in r.derived(v)}
        self.assertTrue(0 < d["label_built"] < 12 and 0 < d["scoop_built"] < 12, d)
        check(self, self.rid, height_u=3)

    def test_extremes(self):
        check(self, self.rid, grid_x=1, grid_y=1, height_u=3, label=0, scoop_r=6, compart_x=1)
        m = check(self, self.rid, grid_x=4, grid_y=4, height_u=20, compart_x=8, compart_y=6, screws=1, floor=2.5,
                  scoop_r=4, label_w=6)
        self.assertEqual({r["key"] for r in registry()[self.rid].measure(m["values"], m["by_feature"])}, {"magnet_hole", "screw_hole"})
        check(self, self.rid, lip=0, magnets=0, scoop=0, label=0, wall=2.4, divider_t=2.4)

    def test_magnet_pocket_follows_the_magnet(self):
        m = check(self, self.rid, magnet_d=8, magnet_clearance=0.05)
        row = registry()[self.rid].measure(m["values"], m["by_feature"])[0]
        self.assertAlmostEqual(row["modelled"], 8.1, 3)

    def test_constraints_explain_themselves(self):
        r = registry()[self.rid]
        for over, params in (({"screws": 1, "floor": 1.2}, "floor"), ({"compart_x": 8, "grid_x": 1}, "compart_x"),
                             ({"magnet_d": 10}, "magnet_d")):
            with self.assertRaises(RecipeError) as cm:
                r.validate({**r.defaults(), **over})
            self.assertIn(params, cm.exception.params)
            self.assertTrue(cm.exception.hint)


class GridfinityBaseplate(unittest.TestCase):
    rid = "gridfinity_baseplate"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        lo, hi = m["bbox"]
        self.assertAlmostEqual(hi[0] - lo[0], 4 * 42, 3)
        self.assertAlmostEqual(hi[2] - lo[2], 4.65, 3)                  # the socket height (spec), open frame

    def test_extremes(self):
        check(self, self.rid, grid_x=1, grid_y=1, corner_r=0.5)
        m = check(self, self.rid, grid_x=3, grid_y=2, floor=1, magnets=1, pad_x=6, pad_y=3)
        self.assertEqual({r["key"] for r in registry()[self.rid].measure(m["values"], m["by_feature"])}, {"socket_waist", "magnet_hole"})
        check(self, self.rid, grid_x=2, grid_y=3, floor=1, screws=1, pad_x=20, pad_y=20, corner_r=8)

    def test_bed_and_floor_constraints(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "pad_x": 10})
        self.assertIn("pad_x", cm.exception.params)
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "magnets": 1})
        self.assertIn("floor", cm.exception.params)


class BatteryHolder(unittest.TestCase):
    rid = "battery_holder"

    def test_contract_and_defaults(self):
        library_contract(self, self.rid)
        m = check(self, self.rid)
        row = registry()[self.rid].measure(m["values"], m["by_feature"])[0]
        self.assertAlmostEqual(row["modelled"], 14.5 + 2 * 0.35, 3)    # AA, IEC LR6 maximum + clearance

    def test_every_kind_builds_with_its_pocket(self):
        r = registry()[self.rid]
        for kind in range(8):
            over = {"kind": kind}
            if kind in (3, 5, 6):
                over.update(cols=3, rows=8)
            m = check(self, self.rid, **over)
            rows = r.measure(m["values"], m["by_feature"])
            self.assertEqual(len(rows), 1, kind)

    def test_extremes(self):
        check(self, self.rid, kind=6, cols=10, rows=6)
        check(self, self.rid, kind=2, cols=3, rows=3, depth_pct=80, grooves=0, web=1.2, border=2.5, corner_r=3)
        check(self, self.rid, kind=1, cols=1, rows=1, depth_pct=25, border=15, corner_r=15)

    def test_limits(self):
        r = registry()[self.rid]
        with self.assertRaises(RecipeError):
            r.validate({**r.defaults(), "cols": 10, "rows": 12})
        with self.assertRaises(RecipeError) as cm:
            r.validate({**r.defaults(), "kind": 2, "cols": 10})
        self.assertIn("cols", cm.exception.params)

    def test_build_is_quick_enough_for_the_worker(self):
        self.assertLess(build(self.rid, kind=6, cols=10, rows=6)["t_total"], 45)


if __name__ == "__main__":
    unittest.main()
