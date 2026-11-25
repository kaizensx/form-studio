"""Mesh to CAD, WP8: editability follows recognition. The mixed result (form/recon/mixed.py: recognised features on the
kept solid, the rest frozen), patterns first (form/recon/patterns.py: one tooth and a polar pattern), and the budget by
predicted gain (the floor, the program route's gate, Layer 1 and the feature search after it).

Each failure class the private parts showed is rebuilt synthetically (tests/recon_fixtures.py): railed_tray (planes
everywhere, no route made a recipe), rounded_tray (walls curving along the direction, under the program route's 40 %),
sector_ratchet (teeth round a hole on a slanted wedge)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = Path(tempfile.mkdtemp(prefix="form-recon-wp8-"))

import recon_fixtures as fx  # noqa: E402

TOL = 0.05
_mixed = {}


def mesh(name):
    from form.recon import pipeline
    stl = TMP / f"{name}.stl"
    if not stl.exists():
        fx.export(name, TMP)
    V, F, _, _ = pipeline.load(stl)
    return stl, V, F


def mixed(name):
    """The mixed result on the fixture's exact solid (Layer 0), computed once."""
    if name not in _mixed:
        from form.recon import mixed as mx
        from form.recon import solid
        stl, V, F = mesh(name)
        sh, info = solid.layer0(V, F)
        assert info["valid"], info
        _mixed[name] = (mx.recipe(V, F, sh, TOL, name=name, out_dir=TMP / f"mixed-{name}"), V, F)
    return _mixed[name]


def rebuild(src, refs, values=None):
    from form.recon import program
    from form.recipes import meshsolid
    stages, rec = program.build_stages(src, refs)
    if values is None:
        return stages[-1].shape
    meshsolid.set_paths(refs)
    try:
        return rec.build(rec.validate({**rec.defaults(), **values}))[-1].shape
    finally:
        meshsolid.set_paths({})


class Push(unittest.TestCase):
    def test_a_face_moves_along_its_normal_and_nothing_else_does(self):
        from build123d import Align, Box
        from form.recon.ops import plane_faces, push
        box = Box(10, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
        self.assertEqual(len(plane_faces(box, (0, 0, 1), 5.0)), 1)
        self.assertEqual(len(plane_faces(box, (0, 0, -1), 0.0)), 1)
        self.assertEqual(len(plane_faces(box, (0, 0, -1), 5.0)), 0)                # the top faces up, not down
        self.assertAlmostEqual(push(box, (0, 0, 1), 5.0, 0.5).volume, 550.0, places=6)
        self.assertAlmostEqual(push(box, (0, 0, 1), 5.0, -0.5).volume, 450.0, places=6)
        self.assertIs(push(box, (0, 0, 1), 5.0, 0.0), box)                         # at its value nothing is rebuilt
        with self.assertRaises(ValueError):
            push(box, (0, 0, 1), 7.0, 0.5)


class Patterns(unittest.TestCase):
    def test_teeth_round_a_hole_are_one_tooth_and_a_pattern(self):
        from form.recon import patterns
        _, V, F = mesh("sector_ratchet")
        f = fx.sector_ratchet()[1]
        g = patterns.find(V, F, TOL)
        self.assertIsNotNone(g)
        self.assertEqual(g["axis"], 2)
        self.assertEqual(g["count"], f["teeth"])
        self.assertAlmostEqual(g["pitch_deg"], f["pitch_deg"], delta=0.05)
        self.assertAlmostEqual(g["centre"][0], 0.0, delta=TOL)
        self.assertAlmostEqual(g["centre"][1], 0.0, delta=TOL)
        za, zb = patterns.levels(V, F, g, TOL)
        self.assertAlmostEqual(za, 0.0, delta=1e-3)
        self.assertAlmostEqual(zb, 6.0, delta=1e-3)

    def test_a_plate_has_no_pattern(self):
        from form.recon import patterns
        _, V, F = mesh("railed_tray")
        self.assertIsNone(patterns.find(V, F, TOL))


class Mixed(unittest.TestCase):
    def check(self, name, at_least):
        r, V, F = mixed(name)
        rp = r["report"]
        self.assertTrue(r["verified"], rp.get("error"))
        self.assertLessEqual(rp["hausdorff_mm"], TOL)
        self.assertGreaterEqual(rp["editable_pct"], at_least)
        d = r["dimensions"]
        self.assertGreater(d["params"], 0)
        self.assertEqual(d["movable"], d["dimensions"])                             # every dimension kept moves
        # the recipe is a real design: rebuilt here it is the same part, and within the tolerance of the mesh
        from form.recon import solid, verify
        shape = rebuild(r["source"], r["refs"])
        P, T = solid.tessellate(shape, TOL / 10)
        self.assertLessEqual(verify.compare(V, F, P, T, shape=shape.wrapped, check_above=TOL)["hausdorff_mm"], TOL)
        return r

    def test_planes_everywhere_become_dimensions(self):
        r = self.check("railed_tray", 50.0)
        src = r["source"]
        self.assertIn("push(body", src)
        self.assertIn("'Thickness 2.5 along Z", src)                               # the plate's own thickness
        # moving a thickness moves the part
        key = next(p["key"] for p in r["params"] if p["label"].startswith("Thickness 2.5 along Z"))
        v0 = rebuild(src, r["refs"]).volume
        v1 = rebuild(src, r["refs"], {key: 3.0}).volume
        self.assertGreater(v1 - v0, 1000.0)

    def test_walls_curving_along_the_direction_still_give_dimensions(self):
        from form.recon import program
        _, V, F = mesh("rounded_tray")
        r = program.recipe(V, F, TOL, name="rounded", out_dir=TMP / "rounded")       # the failure class: gives up
        self.assertIn("read as sketches", r["report"].get("error", ""))
        self.assertLess(r["report"]["walls_read_as_sketches_pct"], 100 * program.MIN_EXPLAINED)
        self.check("rounded_tray", 50.0)                                            # ... the floor does not

    def test_teeth_are_one_patterned_feature(self):
        r = self.check("sector_ratchet", 50.0)
        rp = r["report"]
        self.assertTrue(rp["pattern"]["kept"], rp["pattern"])
        self.assertEqual(rp["pattern"]["count"], fx.sector_ratchet()[1]["teeth"])
        src = r["source"]
        self.assertEqual(src.count("tooth = slab(profile("), 1)                    # one tooth sketch
        self.assertIn("for _i in range(int(round(v['teeth']))):", src)             # ... and a pattern of it
        v0 = rebuild(src, r["refs"]).volume
        n = fx.sector_ratchet()[1]["teeth"]
        v1 = rebuild(src, r["refs"], {"teeth": n + 1}).volume                      # one more tooth: more material
        self.assertGreater(v1 - v0, 5.0)

    def test_no_time_means_no_recipe_and_says_why(self):
        from form.recon import mixed as mx
        from form.recon import solid
        _, V, F = mesh("railed_tray")
        sh, _ = solid.layer0(V, F)
        r = mx.recipe(V, F, sh, TOL, name="late", out_dir=TMP / "late", deadline=time.perf_counter())
        self.assertFalse(r["verified"])                                            # no Param: no recipe to offer
        self.assertEqual(r["report"]["face_params"], 0)
        self.assertIn("time budget", r["report"]["stopped"])
        self.assertIn("time budget", r["report"]["error"])


class BudgetByGain(unittest.TestCase):
    def test_a_program_that_cannot_beat_the_floor_is_not_built(self):
        from form.recon import program
        _, V, F = mesh("railed_tray")
        t = time.perf_counter()
        r = program.recipe(V, F, TOL, name="gate", out_dir=TMP / "gate", floor_pct=100.0)
        self.assertIn("not built (budget by predicted gain)", r["report"].get("error", ""))
        self.assertIn("predicted_pct", r["report"])
        self.assertIsNone(r.get("source"))
        self.assertLess(time.perf_counter() - t, 120)

    def test_the_pipeline_never_offers_zero_when_planes_were_recognised(self):
        """The plate class: Layer 1 recognises the planes, but the routes that make recipes fail (the program route is
        off here, the feature search fails the way a chamfer that will not rebuild made it fail). Without the floor
        the result is Layer 1, 0 % editable; with it, at least half of the surface is."""
        from unittest import mock
        from form.recon import pipeline
        stl, _, _ = mesh("railed_tray")
        off = {"report": {"method": "sketches and extrusions", "error": "off here"}}
        failed = {"report": {"method": "feature tree", "error": "ValueError: Failed creating a chamfer (injected)"}}
        reps = {}
        with mock.patch.dict(os.environ, {"FORM_RECON_BOUNDED": "0"}), \
                mock.patch.object(pipeline, "_program", lambda *a, **k: off), \
                mock.patch.object(pipeline, "layer2", lambda *a, **k: failed):
            for floor in (False, True):
                with mock.patch.object(pipeline, "MIXED", floor):
                    reps[floor] = pipeline.reconstruct(stl, TMP / f"pipe-railed-{floor}", "railed", TOL, budget_s=240.0)
        before, after = reps[False]["result"], reps[True]["result"]
        self.assertEqual(before["layer"], 1)                                       # the failure, reproduced
        self.assertEqual(before["editable_pct"], 0.0)
        self.assertGreater(reps[False]["layers"]["1"]["parametric_area_pct"], 80.0)
        self.assertTrue(after["within_tolerance"])
        self.assertTrue(reps[True]["mixed"]["verified"], reps[True]["mixed"])
        self.assertEqual(after["layer"], 2)
        self.assertGreaterEqual(after["feature_area_pct"], 50.0)
        self.assertGreater(after["editable_pct"], 0.0)
        self.assertTrue((TMP / "pipe-railed-True" / "railed_recipe.py").exists())


if __name__ == "__main__":
    unittest.main()
