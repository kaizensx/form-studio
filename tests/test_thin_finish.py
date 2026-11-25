"""A decorative finish never thins a wall below the print minimum, and a thin structural wall fails its check.

The case: a sofa-arm holder's hollow corbel had a 1.30 mm wall partway round its curve (an inner ellipse that was
not an offset of the outer one), then 0.5 mm flutes cut it to 0.81 mm; the Thinnest-wall check said WARN and the
design shipped. form/wallguard.py measures the wall a finish leaves, form/featureprog.py leaves such a feature out,
craft.finish_cut clamps each cut instead, and form/checks.py fails a structural wall under three nozzle widths.
Also here: blends as large as an arc edge's radius (they crash OCCT) are refused, a crash names the call it happened
in, and the STL re-mesh ladder keeps to a time budget."""
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-thin-finish-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import checks, featureprog, marks, wallguard  # noqa: E402
from form.recipes.base import Feature, Param  # noqa: E402


def _tube(wall):
    """A 40 x 40 x 30 box with a through hole leaving `wall` on every side, as a FeatureDesign class."""
    from build123d import Align, Box, Cylinder, Pos
    from form import craft
    from form.featureprog import FeatureDesign, feature
    C = (Align.CENTER, Align.CENTER, Align.MIN)

    class Design(FeatureDesign):
        title = "Tube"
        params = [Param("w", "Wall", wall, 0.5, 10, 0.1, "mm", "form", "body")]
        features = [Feature("body", "Box section", "structure")]

        @feature("Box section", role="structure")
        def body(self, v, body):
            return Box(40, 40, 30, align=C) - Box(40 - 2 * v["w"], 40 - 2 * v["w"], 32, align=C)

        @feature("Fluted skin", role="finish")
        def flutes(self, v, body):
            for y in (-10, 0, 10):                       # three 0.5 mm deep flutes in the +x face
                body = body - Pos(20 + 1.4 - 0.5, y, -1) * Cylinder(1.4, 32, align=C)
            return body

        @feature("Clamped flutes", role="finish")
        def clamped(self, v, body):
            cuts = [lambda d, y=y: Pos(-20 - 1.4 + d, y, -1) * Cylinder(1.4, 32, align=C) for y in (-10, 0, 10)]
            return craft.finish_cut(body, cuts, 0.5)
    return Design()


def _build(design, floor=1.2):
    marks.set_context({"wall_floor": floor} if floor is not None else {})
    featureprog.begin()
    try:
        st = design.build(design.validate({}))
    finally:
        marks.set_context({})
    return st, featureprog.report()


class FloorRule(unittest.TestCase):
    def test_print_minimum(self):
        self.assertAlmostEqual(wallguard.floor_for("print", 0.4), 1.2)        # 3 x 0.4 beats 2 x 0.45
        self.assertAlmostEqual(wallguard.floor_for("print", 0.6), 1.8)
        self.assertAlmostEqual(wallguard.floor_for("model", None, "casting"), 2.0)
        self.assertEqual(wallguard.floor_for("model", None, ""), 0.0)          # no process stated: no minimum
        self.assertEqual(wallguard.current_floor(), 0.0)                        # a build outside Studio
        self.assertEqual(wallguard.floor_for("game"), 0.0)
        self.assertEqual(wallguard.DEFAULT_FLOOR, wallguard.floor_for("print", 0.4))

    def test_roles(self):
        self.assertTrue(wallguard.guarded("finish") and wallguard.guarded("refine") and wallguard.guarded("texture"))
        self.assertFalse(wallguard.guarded("structure") or wallguard.guarded("interface"))


class FinishGuard(unittest.TestCase):
    def test_a_finish_on_a_thin_wall_is_left_out_with_the_wall_and_where(self):
        st, rep = _build(_tube(1.5))                      # 1.5 - 0.5 = 1.0 mm left: under 1.2
        log = {e["feature"]: e["status"] for e in rep["log"]}
        self.assertEqual(log["flutes"], "skipped")
        msg = rep["skipped"][0]["message"]
        self.assertIn("1.2 mm minimum wall", msg)
        self.assertRegex(msg, r"leave a (0\.9\d|1\.0\d) mm wall at \(")

    def test_the_same_finish_on_a_wall_with_margin_builds(self):
        st, rep = _build(_tube(2.5))
        log = {e["feature"]: e["status"] for e in rep["log"]}
        self.assertEqual(log["flutes"], "built")
        self.assertEqual(log["clamped"], "built")
        self.assertFalse(rep["skipped"])

    def test_the_floor_follows_the_build_context(self):
        st, rep = _build(_tube(1.5), floor=0.8)             # a looser floor (a model's process) lets it through
        self.assertEqual({e["feature"]: e["status"] for e in rep["log"]}["flutes"], "built")

    def test_finish_cut_clamps_each_cut_to_the_wall_behind_it(self):
        from form import craft
        craft.notes()
        st, rep = _build(_tube(1.45))                     # its own values: no checkpoint from the tests above
        log = {e["feature"]: e["status"] for e in rep["log"]}
        self.assertEqual(log["clamped"], "built")            # never trips the guard: it made the cuts shallower
        body = st[-1].shape
        from build123d import Align, Box, Pos
        w = wallguard.cut_walls(Pos(0, 0, 0) * (Box(40, 40, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
                                                - Box(37.1, 37.1, 32, align=(Align.CENTER, Align.CENTER, Align.MIN))), body)
        self.assertIsNotNone(w)
        self.assertGreaterEqual(w["t"], 1.2 - 1e-3)
        self.assertTrue(any("made shallower" in n for n in craft.notes()))

    def test_added_material_is_not_a_thinned_wall(self):
        from build123d import Align, Box, Pos
        C = (Align.CENTER, Align.CENTER, Align.MIN)
        base = Box(40, 40, 10, align=C)
        ribbed = base + Pos(0, 0, 10) * Box(0.9, 30, 2, align=C)     # a 0.9 mm fin on top: new material
        self.assertIsNone(wallguard.cut_walls(base, ribbed))


class StructuralWallCheck(unittest.TestCase):
    def _wall(self, thin, structural):
        rec = type("R", (), {"fit": None, "features": [], "mesh": False})()
        analysis = {"brep": {"valid": True, "solids": 1, "volume_mm3": 1000.0}, "interface_audit": [],
                    "orientation_table": [{"id": "as_modelled", "label": "Base down", "footprint_mm": [50, 50],
                                           "height_mm": 20, "steep_mm2": 0, "ceiling_mm2": 0, "contact_mm2": 900}],
                    "thin": thin, "thin_structural": structural, "thickness_samples": 1000}
        ctx = {"orientation": "as_modelled", "envelope": (180, 180, 180), "margin": 2, "printer": "A1 mini", "nozzle": 0.4}
        return next(c for c in checks.build(rec, {"derived": [], "statics": None}, analysis, ctx, None) if c["id"] == "wall")

    def test_a_structural_wall_under_three_lines_fails_with_where(self):
        spot = {"t": 0.98, "at": [67.9, -59.1, 30.0], "to": [67.0, -58.7, 30.0], "feature": "corbel"}
        c = self._wall(spot, {**spot, "label": "Hollow corbel", "cut_by": ["Fluted skin"], "features": ["flutes", "corbel"]})
        self.assertEqual(c["status"], "FAIL")
        self.assertEqual(c["value"], "0.98 mm")
        self.assertIn("Hollow corbel (thinned by Fluted skin)", c["detail"])
        self.assertIn("(67.9, -59.1, 30.0)", c["detail"])
        self.assertEqual(c["feature"], "corbel")

    def test_a_decorative_ridge_in_the_soft_band_stays_a_warning(self):
        ridge = {"t": 0.98, "at": [1, 2, 3], "to": [1, 3, 3], "feature": "flutes"}
        c = self._wall(ridge, {"t": 3.6, "at": [0, 0, 0], "to": [0, 0, 3.6], "feature": "body"})
        self.assertEqual(c["status"], "WARN")
        self.assertEqual(self._wall({**ridge, "t": 0.6}, None)["status"], "FAIL")       # under two lines: any wall
        self.assertEqual(self._wall({**ridge, "t": 1.3}, {**ridge, "t": 1.3})["status"], "PASS")


class KernelSafety(unittest.TestCase):
    def test_a_fillet_as_large_as_an_arc_edge_is_not_handed_to_occt(self):
        # r05 of the sofa-arm holder: a 1.2 mm fillet on the top edge of a 1.2 mm radius bead ended the kernel
        from build123d import Align, Axis, Box, Cylinder, Pos
        from form import craft
        from form.craft.surfaces import singular_edges
        C = (Align.CENTER, Align.CENTER, Align.MIN)
        body = Box(20, 20, 10, align=C) + Pos(10, 0, 0) * Cylinder(1.2, 10, align=C)
        top = body.edges().group_by(Axis.Z)[-1]
        self.assertTrue(singular_edges(top, 1.2))
        craft.notes()
        out = craft.safe_fillet(body, top, 1.2)          # would crash the process without the guard
        self.assertTrue(out.is_valid)
        self.assertTrue(any("crashes the kernel" in n for n in craft.notes()))

    def test_a_crash_names_the_call_and_the_source_line(self):
        from form.worker import crash_site, crash_text
        src = os.path.join(TMP, ".sources", "abc.py")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w") as f:
            f.write("x = 1\nbody = craft.safe_fillet(body, zs[-1], 1.2)\n")
        dump = ("Fatal Python error: Segmentation fault\n\nCurrent thread 0x1 (most recent call first):\n"
                '  File "/x/build123d/topology/three_d.py", line 367 in fillet\n'
                '  File "/x/form/craft/surfaces.py", line 296 in safe_fillet\n'
                f'  File "{src}", line 2 in build\n')
        site = crash_site(dump)
        self.assertEqual(site["op"], "fillet (three_d.py:367)")
        self.assertEqual(site["via"], "craft.safe_fillet")
        self.assertEqual(site["line"], 2)
        self.assertIn("line 2 of the design source: `body = craft.safe_fillet(body, zs[-1], 1.2)`", crash_text(site))
        self.assertIsNone(crash_site("no stack here"))

    def test_the_stl_export_ladder_keeps_to_its_budget(self):
        """The export that hung 60 s (a chamfer over flute edges): the ladder (form/meshclose.py) stops at its
        budget and answers, closed or with the cause."""
        import time
        from build123d import Box
        from form import kernel
        out = os.path.join(TMP, "box.stl")
        t0 = time.perf_counter()
        info = kernel.write_stl(Box(10, 10, 10), out, budget_s=0.0)
        self.assertLess(time.perf_counter() - t0, 5.0)
        self.assertIn("closure", info)
        self.assertTrue(info["closure"]["closed"])


if __name__ == "__main__":
    unittest.main()
