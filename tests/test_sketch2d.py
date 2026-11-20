"""form.sketch2d: constrained 2D sketches whose dimensions are parameters (WP-F)."""
import random
import time
import unittest

from form.sketch2d import Sketch, SketchError, fixtures


class Fixtures(unittest.TestCase):
    def test_ten_fixtures_solve_and_every_dimension_moves_20_percent(self):
        self.assertEqual(len(fixtures.ALL), 10)
        for name, make in fixtures.ALL.items():
            s = make()
            rep = s.report()
            self.assertLess(rep["residual_mm"], 1e-6, name)
            for d in s.dims():
                for k in (0.8, 1.2):
                    s2 = make()
                    sol = s2.solve({d.name: d.value * k})
                    self.assertAlmostEqual(sol.measure(d.name), d.value * k, 6, f"{name}.{d.name} x{k}")
                    # every other named dimension holds too
                    for o in s2.dims():
                        if o.name != d.name:
                            self.assertAlmostEqual(sol.measure(o.name), o.value, 6, f"{name}: {o.name} kept")
                    self.assertTrue(s2.polygons({d.name: d.value * k}), f"{name}.{d.name} x{k} closes")

    def test_thirty_entities_forty_constraints_under_50_ms(self):
        s = fixtures.gasket()
        rep = s.report()
        self.assertGreaterEqual(rep["entities"], 30)
        self.assertGreaterEqual(rep["constraints"], 40)
        # from a rough drawing: every free point moved up to 2 mm, then solved from scratch
        rnd = random.Random(4)
        for p in s.points:
            if not p.fixed:
                p.x += rnd.uniform(-2, 2)
                p.y += rnd.uniform(-2, 2)
        s._nominal = None
        t = time.perf_counter()
        sol = s.solve()
        ms = (time.perf_counter() - t) * 1000
        self.assertTrue(sol.result.ok)
        self.assertLess(ms, 50, f"{ms:.1f} ms")
        self.assertAlmostEqual(sol.measure("outer_w"), 120, 6)

    def test_intent_is_kept_tangent_and_centred(self):
        s = fixtures.slot_plate()
        sol = s.solve({"slot_len": 52})
        self.assertAlmostEqual(sol.measure("slot_len"), 52, 6)
        polys = s.polygons({"slot_len": 52})
        xs = [p[0] for p in polys[1]]
        self.assertAlmostEqual(min(xs), -max(xs), 4)          # the slot stays centred on the plate

    def test_degrees_of_freedom(self):
        self.assertTrue(fixtures.t_slot().report()["fully_constrained"])
        s = Sketch("free")
        a, b = s.point(0, 0, fix=True), s.point(10, 0)
        s.line(a, b)
        self.assertEqual(s.report()["dof"], 2)


class Errors(unittest.TestCase):
    def test_conflict_names_the_constraints(self):
        s = Sketch("bad")
        a, b = s.point(0, 0, fix=True), s.point(10, 0)
        ln = s.line(a, b)
        s.length(ln, 10, "len")
        s.hdist(a, b, 10)
        s.horizontal(ln)
        with self.assertRaises(SketchError) as e:
            s.solve({"len": 14})
        self.assertIn("len", e.exception.params)

    def test_open_profile_is_refused(self):
        s = Sketch("open")
        s.polyline((0, 0), (10, 0), (10, 10))
        with self.assertRaises(SketchError):
            s.polygons()

    def test_names_are_unique(self):
        s = Sketch("dup")
        ln = s.line((0, 0), (1, 0))
        s.length(ln, 1, "a")
        with self.assertRaises(SketchError):
            s.length(ln, 1, "a")


class Params(unittest.TestCase):
    def test_dimensions_become_params(self):
        s = fixtures.rounded_plate()
        ps = s.params(feature="plate")
        self.assertEqual({p.key for p in ps}, {"plate_w", "plate_h", "corner_r", "hole_d", "bore_d"})
        self.assertTrue(all(p.feature == "plate" and p.min < p.default < p.max for p in ps))

    def test_face_and_a_design(self):
        from build123d import extrude
        from form.recipes.base import Param, Recipe, Stage
        sk = fixtures.l_bracket()

        class D(Recipe):
            id = "t"
            params = sk.params(feature="bracket") + [Param("depth", "Depth", 20, 5, 60)]

            def build(self, v):
                return [Stage("bracket", extrude(sk.face(v), v["depth"]))]
        d = D()
        a = d.build(d.validate(d.defaults()))[-1].shape
        b = d.build(d.validate({**d.defaults(), "leg_b": 60}))[-1].shape
        self.assertTrue(a.is_valid and b.is_valid)
        self.assertAlmostEqual(a.bounding_box().size.Y, 50, 4)
        self.assertAlmostEqual(b.bounding_box().size.Y, 60, 4)
        self.assertIn("<svg", sk.svg())


if __name__ == "__main__":
    unittest.main()
