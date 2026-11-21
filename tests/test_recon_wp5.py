"""Mesh to CAD, WP5: turned bodies and polar patterns in the program route, the stepwise loop, the two honesty numbers,
and the optional learned engine (CAD-Recode) as an opt-in that is mocked here: no weights are ever downloaded or
loaded by these tests. Synthetic parts only (tests/recon_fixtures.py)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from functools import partial
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = Path(tempfile.mkdtemp(prefix="form-recon-wp5-"))
os.environ.setdefault("FORM_CADRECODE_DIR", str(TMP / "no-model-here"))

import recon_fixtures as fx  # noqa: E402

# a CadQuery program as CAD-Recode writes it, in its own normalised units, for box_with_holes (60 x 40 x 10, four
# Ø5.5 holes at ±22, ±12 and a Ø8 centre bore); BAD is the same with the wrong height
CODE = """import cadquery as cq
w0=cq.Workplane('XY',origin=(0,0,-17))
r=w0.sketch().push([(0,0)]).rect(200,133).push([(-73,-40),(73,-40),(-73,40),(73,40)]).circle(9,mode='s').push([(0,0)]).circle(13,mode='s').finalize().extrude(33)
"""
BAD = CODE.replace("rect(200,133)", "rect(200,120)")


def mesh(name):
    from form.recon import pipeline
    stl = fx.export(name, TMP)[0]
    V, F, _, _ = pipeline.load(stl)
    return stl, V, F


class CadQuerySubset(unittest.TestCase):
    """The model's code is read, never run."""

    def test_reads_sketch_extrude_programs(self):
        from form.recon.learned import cq
        plan = cq.parse(CODE)
        (e,) = plan.extrusions()
        self.assertEqual((e.d0, e.d1), (0.0, 33.0))
        self.assertEqual([it.kind for it in e.items], ["rect"] + ["circle"] * 5)
        self.assertEqual([it.mode for it in e.items], ["a"] + ["s"] * 5)
        two = cq.parse("import cadquery as cq\nw0=cq.Workplane('ZX',origin=(0,4,0))\n"
                       "r=w0.workplane(offset=2).moveTo(0,0).lineTo(10,0).threePointArc((12,5),(10,10)).lineTo(0,10)"
                       ".close().extrude(-5).union(w0.sketch().circle(3).finalize().extrude(4, both=True))")
        a, b = two.extrusions()
        self.assertEqual(a.items[0].kind, "path")
        self.assertEqual((a.d0, a.d1), (-5.0, 0.0))
        self.assertEqual((b.d0, b.d1), (-4.0, 4.0))
        self.assertTrue(np.allclose(a.plane.origin, (0, 6, 0)))          # ZX's normal is +Y: offset 2 from y=4

    def test_refuses_anything_else(self):
        from form.recon.learned import cq
        for code in ("import os\nos.system('true')", "import cadquery as cq\nr=__import__('os')",
                     "import cadquery as cq\ndef f(): pass", "import cadquery as cq\nr=cq.Workplane('XY').box(1,1,1)",
                     "import cadquery as cq\nr=cq.Workplane('XY').circle(1).revolve()",
                     "import cadquery as cq\nfor i in range(3): pass", "not python ("):
            with self.assertRaises(cq.Unsupported, msg=code):
                cq.parse(code)

    def test_placement_refuses_other_proportions(self):
        from form.recon.learned import cq, translate
        _, V, F = mesh("box_with_holes")
        tall = cq.parse(CODE.replace("extrude(33)", "extrude(150)"))
        with self.assertRaises(cq.Unsupported):
            translate.placement(tall, V)


class LearnedCandidate(unittest.TestCase):
    """The adapter, with the model mocked: placed, snapped, built and verified like every candidate."""

    def test_good_program_verifies_with_dimension_params(self):
        from form.recon import learned, program
        _, V, F = mesh("box_with_holes")
        c = learned.candidate(V, F, 0.02, name="box", generate=lambda V, F: {"code": CODE, "seconds": 0.0})
        self.assertTrue(c["verified"], c["report"])
        self.assertLessEqual(c["report"]["hausdorff_mm"], 0.02)
        vals = sorted(p["value"] for p in c["params"] if p["kind"] in ("d", "L"))
        self.assertEqual(vals, [5.5, 8, 40, 60])                            # snapped onto the mesh, not the model's guess
        md = program.movable_dimensions(c["source"])
        self.assertEqual(md["movable"], md["params"])

    def test_bad_program_is_reported_not_returned(self):
        from form.recon import learned
        _, V, F = mesh("box_with_holes")
        c = learned.candidate(V, F, 0.02, generate=lambda V, F: {"code": BAD})
        self.assertFalse(c["verified"])
        self.assertIn("from the mesh", c["report"]["error"])
        c = learned.candidate(V, F, 0.02, generate=lambda V, F: (_ for _ in ()).throw(RuntimeError("no GPU")))
        self.assertFalse(c["verified"])
        self.assertIn("did not run", c["report"]["error"])


class PipelineWithAndWithoutTheEngine(unittest.TestCase):
    def test_not_installed_changes_nothing(self):
        from form.recon import learned, pipeline
        self.assertFalse(learned.status()["installed"])
        stl, _, _ = mesh("box_with_holes")
        with mock.patch.object(learned, "candidate", side_effect=AssertionError("called without the engine")):
            rep = pipeline.reconstruct(stl, TMP / "plain", "box", 0.02)
        self.assertNotIn("learned", rep)
        self.assertTrue(rep["result"]["within_tolerance"])
        self.assertEqual(rep["result"]["brep_pct"], 100.0)
        self.assertEqual(rep["result"]["editable_pct"], 100.0)

    def test_failing_learned_candidate_is_never_the_result(self):
        from form.recon import learned, pipeline
        stl, _, _ = mesh("box_with_holes")
        fake = partial(learned.candidate, generate=lambda V, F: {"code": BAD})
        with mock.patch.object(learned, "status", return_value={"installed": True}), \
                mock.patch.object(learned, "candidate", fake):
            rep = pipeline.reconstruct(stl, TMP / "bad", "box", 0.02)
        self.assertFalse(rep["learned"]["verified"])
        self.assertNotIn("chosen", rep["learned"])
        self.assertNotIn("learned", rep["result"].get("method") or "")
        self.assertTrue(rep["result"]["within_tolerance"])


class TurnedAndPatterns(unittest.TestCase):
    def test_turned_shaft_is_one_revolved_profile(self):
        from form.recon import program
        _, V, F = mesh("turned_shaft")
        r = program.recipe(V, F, 0.02, name="shaft", out_dir=TMP)
        rp = r["report"]
        self.assertTrue(r["verified"], rp.get("error"))
        self.assertEqual(rp["editable_pct"], 100.0)                       # every face from the revolve, nothing kept
        self.assertEqual([f["kind"] for f in rp["features"]], ["revolve"])
        ds = sorted({round(p["value"], 3) for p in rp["param_table"] if p["kind"] == "d"})
        for d in (16.0, 20.0, 25.0):
            self.assertIn(d, ds)
        md = program.movable_dimensions(r["source"])
        self.assertEqual(md["dimensions"], md["params"])                  # diameters, levels, radii: no positions

    def test_bolt_flange_has_a_polar_pattern(self):
        from form.recon import program
        _, V, F = mesh("bolt_flange")
        r = program.recipe(V, F, 0.02, name="flange", out_dir=TMP)
        rp = r["report"]
        self.assertTrue(r["verified"], rp.get("error"))
        pat = [f for f in rp["features"] if f["kind"] == "polar pattern"]
        self.assertEqual(len(pat), 1)
        self.assertEqual(pat[0]["count"], 6)
        self.assertAlmostEqual(pat[0]["pcd_mm"], 60.0, places=2)
        p1 = next(p for p in rp["param_table"] if p["kind"] == "P")
        self.assertEqual(p1["value"], 60)
        md = program.movable_dimensions(r["source"])
        self.assertIn(p1["key"], md["keys"])                              # the pitch circle moves every hole at once


class Stepwise(unittest.TestCase):
    def test_residual_and_nothing_to_do(self):
        from form.recon import stepwise
        self.assertEqual(stepwise.residual(90.0, {"over_tolerance_area_pct": 1.5}), 11.5)
        best = {"ok": True, "edit": 100.0, "result": None}
        self.assertIs(stepwise.refine(None, None, 0.02, 0.02, "x", TMP, {"runs": []}, best), best)
        best = {"ok": False, "edit": 50.0, "result": None}
        self.assertIs(stepwise.refine(None, None, 0.02, 0.02, "x", TMP, {"runs": []}, best), best)

    def test_ranges_reach_the_nearest_value_on_each_side(self):
        from form.recon.program import Pool
        p = Pool(0.02)
        for z in (0.0, 1.0, 25.0):
            p.add("Z", z, "base")
        p.solve()
        z1 = next(q for q in p.params if q["value"] == 1.0)
        self.assertAlmostEqual(z1["lo"], 0.6)                              # 0.4 of the way down to 0 ...
        self.assertAlmostEqual(z1["hi"], 1.0 + 0.4 * 24)                   # ... and 0.4 of the way up to 25


class Installer(unittest.TestCase):
    def test_size_and_licence_are_shown_before_any_download(self):
        from form import config, installer
        sw = installer.get("recon.learned")
        self.assertEqual(sw.level, "optional")
        self.assertIn("3.09 GB", sw.size)
        self.assertIn("non-commercial", sw.licence)
        cfg = config.load()
        cfg["data"]["dir"] = str(TMP / "data")
        row = installer.survey(cfg, only=["recon.learned"])[0]
        self.assertEqual(row["status"], "missing")
        self.assertFalse(row["default"])                                  # never pre-ticked, never installed by itself
        self.assertIn("3.09 GB", row["size"])
        self.assertIn("non-commercial", row["licence"])
        for m in row["methods"]:
            if m["kind"] == "command":
                self.assertIn("3.09 GB", m["note"])
                self.assertIn("CC BY-NC 4.0", m["note"])
                self.assertIn("--accept-licence cc-by-nc-4.0", m["commands"][-1])
        self.assertNotIn("recon.learned", installer.auto_ids(installer.survey(cfg)))

    def test_download_refuses_without_the_licence(self):
        from form.recon.learned import __main__ as dl
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(dl.main(["download", "--dir", str(TMP / "m")]), 2)
            self.assertEqual(dl.main(["download", "--accept-licence", "mit", "--dir", str(TMP / "m")]), 2)
        self.assertIn("CC BY-NC 4.0", err.getvalue())
        self.assertIn("3.09 GB", err.getvalue())
        self.assertFalse((TMP / "m").exists())

    def test_status_never_imports_torch(self):
        from form.recon import learned
        st = learned.status(TMP / "nowhere")
        self.assertFalse(st["installed"])
        self.assertNotIn("torch", sys.modules)
        self.assertEqual(json.loads(json.dumps(st))["licence"], learned.LICENCE)


if __name__ == "__main__":
    t = time.perf_counter()
    unittest.main()
