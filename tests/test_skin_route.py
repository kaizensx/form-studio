"""The skin route (subd.skin_from_sections), separate parts, splits with a lip, magnet stock and the hero helmet."""
import json
import os
import time
import unittest

from form import craft, exemplars

try:
    import build123d  # noqa: F401
    HAVE_OCCT = True
except Exception:          # pragma: no cover
    HAVE_OCCT = False

TIMES = os.environ.get("FORM_SKIN_ROUTE_TIMES")      # optional: a JSON file the measured build time is written to


class MagnetTable(unittest.TestCase):
    def test_stock_fits_and_unknown_pull(self):
        self.assertEqual(set(craft.MAGNETS), {"6x2", "6x3", "8x3", "10x3"})
        self.assertEqual(set(craft.MAGNET_FITS), {"press", "glue", "printed"})
        self.assertEqual(craft.MAGNET_FLOOR, 0.6)
        m = craft.magnet("8x3", "glue")
        self.assertAlmostEqual(m["pocket_d"], 8.3)
        self.assertAlmostEqual(m["pocket_depth"], 3.2)
        self.assertIsNone(m["pull"]["value"])
        self.assertEqual(m["pull"]["provenance"], "unknown")
        with self.assertRaises(craft.RecipeError):
            craft.magnet("6x2", "glue", pull_n=9.0)               # a force needs its datasheet
        self.assertEqual(craft.magnet("6x2", pull_n=9.0, source="supplier datasheet")["pull"]["provenance"],
                         "specified")

    def test_room_check(self):
        with self.assertRaises(craft.RecipeError):
            craft.magnet_pair((0, 0, 0), (0, 0, 1), "6x3", "glue", room_b=3.0)    # 3.2 + 0.6 does not fit in 3
        craft.magnet_pair((0, 0, 0), (0, 0, 1), "6x2", "glue", room_b=3.0)

    def test_hero_helmet_found_for_its_query(self):
        hits = [h["name"] for h in exemplars.search("full-face helmet separate parts magnets lens texture", 3)]
        self.assertEqual(hits[0], "hero_helmet")
        self.assertEqual(exemplars.search("motorcycle helmet with texture")[0]["name"], "helmet")


@unittest.skipUnless(HAVE_OCCT, "needs build123d")
class SkinRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from form.craft import subd
        F = craft.helmet_fullface("J")
        cls.F = F
        cls.skin = subd.skin_from_sections(F["sections"], F["tip"], n=22)
        cls.shell = cls.skin.shell(3.5)

    def test_shell_is_few_faces_and_close_to_the_sections(self):
        self.assertLessEqual(len(self.shell.faces()), 6)
        self.assertTrue(self.shell.is_valid)
        dev = self.skin.deviation
        self.assertLess(dev["max_mm"], 2.0, dev)
        self.assertLess(dev["mean_mm"], 0.5, dev)

    def test_ten_analytic_booleans_stay_valid(self):
        from build123d import Box, Cylinder, Pos, Rot, Sphere
        L, W, H = self.F["L"], self.F["W"], self.F["H"]
        tools = [Pos(L / 2, 0, 120) * Rot(0, 90, 0) * Cylinder(20, 80), Pos(0, 0, H) * Box(60, 30, 40),
                 Pos(-L / 2, 8, 150) * Sphere(30), Pos(0, W / 2, 140) * Rot(90, 0, 0) * Cylinder(12, 60),
                 Pos(0, -W / 2, 100) * Box(40, 30, 40), Box(400, 400, 40),
                 Pos(L * 0.3, W * 0.3, 200) * Sphere(25), Pos(-L * 0.3, -W * 0.3, 60) * Rot(0, 0, 30) * Box(30, 60, 30),
                 Pos(L / 2, 0, 40) * Rot(0, 90, 0) * Cylinder(30, 50), Pos(0, 0, H - 5) * Cylinder(40, 30)]
        for i, tl in enumerate(tools):
            for r in (self.shell - tl, self.shell + tl):
                self.assertTrue(r.is_valid, i)
                self.assertEqual(len(r.solids()), 1, i)

    def test_offsets_share_no_faces(self):
        from build123d import Box, Pos
        H = self.F["H"]
        a = self.skin.band(2.0, Pos(0, 0, H) * Box(80, 40, 60), depth=1.5)
        b = self.skin.band(2.0, Pos(30, 0, H) * Box(80, 40, 60), depth=1.5)     # same amount, overlapping regions
        body = craft.fuse(craft.fuse(self.shell, a), b)
        self.assertTrue(body.is_valid)
        self.assertEqual(len(body.solids()), 1)

    def test_parts_measure_clearance(self):
        from build123d import Box, Pos
        a, b = Box(10, 10, 10), Pos(10.3, 0, 0) * Box(10, 10, 10)
        out = craft.parts(a=a, b=b, clearance=0.2)
        self.assertEqual(list(craft.named_parts(out)), ["a", "b"])
        with self.assertRaises(craft.RecipeError):
            craft.parts(a=a, b=b, clearance=0.5)
        with self.assertRaises(craft.RecipeError):
            craft.parts(a=a, b=Pos(5, 0, 0) * Box(10, 10, 10))                  # overlapping parts


@unittest.skipUnless(HAVE_OCCT, "needs build123d")
class HeroHelmet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        craft.notes()
        from form import featureprog
        cls.design = exemplars.load("hero_helmet")
        cls.v = cls.design.defaults()
        featureprog.begin()
        t0 = time.perf_counter()
        cls.stages = cls.design.build(cls.v)
        cls.seconds = time.perf_counter() - t0
        cls.report = featureprog.report()
        if TIMES:
            with open(TIMES, "w", encoding="utf-8") as f:
                json.dump({"hero_helmet_build_s": round(cls.seconds, 2)}, f)
        print(f"\nhero_helmet build: {cls.seconds:.2f} s")

    def test_builds_four_valid_parts_in_time(self):
        out = self.stages[-1].shape
        self.assertTrue(out.is_valid)
        self.assertEqual(len(out.solids()), self.design.solids)
        self.assertEqual(sorted(craft.named_parts(out)), ["faceplate", "lens_l", "lens_r", "shell"])
        self.assertLess(self.seconds, 45.0)

    def test_is_a_feature_design_built_skeleton_first(self):
        from form.featureprog import FeatureDesign
        self.assertIsInstance(self.design, FeatureDesign)
        ids = [f.id for f in self.design.features]
        self.assertEqual(ids[0], "shell")                         # the skeleton: one solid, built first
        self.assertEqual(len(self.stages[0].shape.solids()), 1)
        self.assertEqual([s.feature for s in self.stages], ids)  # one stage per @feature, none skipped
        self.assertEqual(self.report["skipped"], [], self.report)

    def test_lens_magnets_stay_under_the_plate(self):
        """Measured with rays from outside along each lens pocket's axis: the faceplate keeps well over the 0.6 mm
        floor in front of every lens magnet (the seat inside it adds 1 mm), so no pocket shows on the outside."""
        out = craft.named_parts(self.stages[-1].shape)
        for pr in self.design.magnet_pairs(self.v)[4:]:
            self.assertGreater(pr.floor(out["faceplate"], "a"), 2.5)

    def test_magnet_pairs_are_coaxial(self):
        out = craft.named_parts(self.stages[-1].shape)
        pairs = self.design.magnet_pairs(self.v)
        self.assertEqual(len(pairs), 8)
        for k, pr in enumerate(pairs):
            a, b = ("shell", "faceplate") if k < 4 else ("faceplate", "lens_l" if k < 6 else "lens_r")
            err = craft.coaxial_error(pr, out[a], out[b])
            self.assertLess(err["offset_mm"], 0.05, (k, err))
            self.assertLess(err["angle_deg"], 0.5, (k, err))

    def test_assembly_finds_every_part(self):
        from form.recipes.assembly import Part  # noqa: F401
        spec = self.design.assembly(self.v)
        out = craft.named_parts(self.stages[-1].shape)
        from build123d import Vector
        for p in spec.parts:
            holder = [n for n, s in out.items() if s.is_inside(Vector(*p.solid))]
            self.assertEqual(holder, [p.id], p)
        self.assertIn("unknown", spec.hardware[0].note)


if __name__ == "__main__":
    unittest.main()
