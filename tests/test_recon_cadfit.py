"""CADFit as a mesh-to-CAD candidate (form/recon/cadfit): its scripts are read, never run; its candidate is built and
verified like every other; it respects its deadline; and the pipeline is unchanged when it is off.

Synthetic parts only (tests/recon_fixtures.py). Nothing is downloaded.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("FORM_SKIP_UI", "1")


def _box_script(height=1 / 3, export=None, bore=True):
    """A CADFit-style program for recon_fixtures.box_with_holes, in CADFit's normalised frame (centre (0, 0, 5) mm,
    60 mm -> 2): the outline and its five holes on one sketch, extruded."""
    s = 1 / 30
    L = ["import cadquery as cq", "import math", "",
         "plane_1 = cq.Plane(origin=(0.0, 0.0, -0.166667), normal=(0.0, 0.0, 1.0), xDir=(1.0, 0.0, 0.0))",
         "sketch_1 = cq.Workplane(plane_1)",
         "loop_1 = sketch_1.moveTo(-1.0, -0.666667)", "loop_1 = loop_1.lineTo(1.0, -0.666667)",
         "loop_1 = loop_1.lineTo(1.0, 0.666667)", "loop_1 = loop_1.lineTo(-1.0, 0.666667)", "loop_1 = loop_1.close()"]
    names = ["loop_1"]
    holes = [(-22, -12, 2.75), (22, -12, 2.75), (-22, 12, 2.75), (22, 12, 2.75)] + ([(0, 0, 4.0)] if bore else [])
    for k, (x, y, r) in enumerate(holes):
        n = f"loop_{k + 2}"
        names.append(n)
        L += [f"{n} = sketch_1.moveTo({x * s:.6f}, {y * s:.6f})", f"{n} = {n}.circle({r * s:.6f})"]
    L.append("sketch_1=sketch_1" + "".join(f".add({n})" for n in names))
    L.append(f"solid_1 = sketch_1.extrude({height:.6f})")
    L.append("result = solid_1")
    if export:
        L.append(f"cq.exporters.export(result, {export!r})")
    return "\n".join(L) + "\n"


def _mesh(name="box_with_holes"):
    import recon_fixtures as fx
    from form.recon import pipeline
    d = Path(tempfile.mkdtemp(prefix="cadfit-test-"))
    stl = fx.export(name, d)[0]
    V, F, _, _ = pipeline.load(stl)
    return V, F


# children for the deadline tests (top level: the child process is started with spawn)
def _runner_sends_then_hangs(conn, stl, work, seconds):        # pragma: no cover - runs in the child process
    conn.send({"script": "result = 1", "iou": 0.5, "steps": {}})
    time.sleep(120)


def _runner_hangs(conn, stl, work, seconds):                   # pragma: no cover - runs in the child process
    time.sleep(120)


def _in_daemon(conn, left_s):                                  # pragma: no cover - runs in a daemon child
    """What the kernel worker does: a daemon process that runs the real CADFit candidate (its own child included)."""
    from form.recon import cadfit
    V, F = _mesh("filleted_block")
    t = time.perf_counter()
    c = cadfit.candidate((V, F), 240, tol=0.02, name="part", left_s=left_s)
    conn.send({**c["report"], "_took": round(time.perf_counter() - t, 2)})


def np_zeros():
    import numpy as np
    return np.zeros((3, 3))


def np_tri():
    import numpy as np
    return np.array([[0, 1, 2]])


class ScriptReader(unittest.TestCase):
    def test_reads_and_builds_the_subset(self):
        from form.recon.cadfit import cqrun
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "a.stl"
            cqrun.allow(d)
            try:
                cqrun.run_script(_box_script(export=str(out)))
            finally:
                cqrun.allow(None)
            self.assertGreater(out.stat().st_size, 1000)
        op = cqrun.program(_box_script())
        self.assertEqual(op.node[0], "extrude")
        self.assertEqual(len(op.node[2]), 6)
        solids = cqrun.build(op)
        self.assertEqual(len(solids), 1)
        v = 2 * (4 / 3) * (1 / 3) - (4 * (2.75 / 30) ** 2 + (4 / 30) ** 2) * 3.141592653589793 / 3
        self.assertAlmostEqual(solids[0].volume, v, places=3)    # the circles are holes, not material

    def test_refuses_anything_else(self):
        from form.recon.cadfit import cqrun
        bad = ["import os", "__import__('os').system('true')", "open('x', 'r')", "x = [1, 2]",
               "plane = cq.Plane(origin=(0, 0, 0), normal=(0, 0, 1))\nw = cq.Workplane(plane)\nw.shell(1)",
               "for i in range(3):\n    pass", "exec('1')"]
        for src in bad:
            with self.assertRaises(cqrun.Unsupported, msg=src):
                cqrun.program("import cadquery as cq\n" + src)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            cqrun.allow(d)
            try:
                with self.assertRaises(cqrun.Unsupported):          # an export outside the work folder
                    cqrun.run_script(_box_script(export=str(Path(other) / "x.stl")))
                self.assertFalse((Path(other) / "x.stl").exists())
            finally:
                cqrun.allow(None)

    def test_scratch_files_stay_in_the_work_folder(self):
        """CADFit's volume of a candidate writes a scratch script and STL with tempfile: the driver points tempfile at
        the work folder, so the export is allowed there and the volume is real."""
        from form.recon.cadfit import cqrun
        from form.recon.cadfit.vendor import cadquery_ops
        acts = ["plane = cq.Plane(origin=(0, 0, 0), normal=(0, 0, 1), xDir=(1, 0, 0))", "sketch = cq.Workplane(plane)",
                "sketch.moveTo(0, 0)", "sketch.circle(0.5)"]
        keep = tempfile.tempdir
        with tempfile.TemporaryDirectory() as d:
            cqrun.allow(d)
            tempfile.tempdir = d
            try:
                v = cadquery_ops.calculate_extrusion_volume({"insts": acts, "height": 1.0})
            finally:
                tempfile.tempdir = keep
                cqrun.allow(None)
            self.assertAlmostEqual(v, 3.14159 * 0.25, places=2)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_vendored_code_runs_no_subprocess(self):
        root = Path(__file__).resolve().parents[1] / "form" / "recon" / "cadfit"
        for p in root.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("subprocess.run", text, p.name)
            self.assertNotIn("os.system(", text, p.name)
            self.assertNotIn("hf_hub_download", text, p.name)
        self.assertEqual([x for x in root.rglob("*.pyc") if "__pycache__" not in x.parts], [])
        self.assertTrue((root / "LICENSE").read_text().startswith("Attribution-NonCommercial 4.0 International"))
        self.assertIn("MIT licence does not cover this folder", (root / "PERMISSION.md").read_text())
        for p in (root / "vendor").glob("*.py"):
            head = p.read_text(encoding="utf-8").split("\n", 4)
            self.assertTrue(any("Ghadi Nehme" in h for h in head[:3]), p.name)


class Candidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.V, cls.F = _mesh()

    def test_candidate_builds_and_verifies(self):
        from form.recon import cadfit
        c = cadfit.candidate((self.V, self.F), 240, tol=0.02, name="box",
                             search=lambda V, F, s: {"script": _box_script(), "iou": 1.0, "seconds": 0.1})
        self.assertTrue(c["verified"], c["report"].get("error"))
        self.assertLessEqual(c["report"]["hausdorff_mm"], 0.02)
        self.assertEqual(c["report"]["editable_pct"], 100.0)
        self.assertIn("Param(", c["source"])
        self.assertIn("CADFit", c["source"])
        self.assertEqual(c["report"]["solids"], 1)

    def test_never_returned_when_it_fails_verify(self):
        from form.recon import cadfit
        wrong = lambda V, F, s: {"script": _box_script(bore=False), "iou": 0.98, "seconds": 0.1}   # no centre bore
        c = cadfit.candidate((self.V, self.F), 240, tol=0.02, name="box", search=wrong)
        self.assertFalse(c["verified"])
        self.assertIn("from the mesh", c["report"]["error"])
        prog = {"report": {"method": "sketches and extrusions", "verified": True, "editable_pct": 10.0,
                           "hausdorff_mm": 0.01}, "verified": True}
        rep = {}
        from form.recon import pipeline
        with mock.patch.dict(os.environ, {"FORM_RECON_CADFIT": "1"}), \
                mock.patch.object(cadfit, "_search", wrong), mock.patch.object(cadfit, "status",
                                                                               return_value={"installed": True}):
            got = cadfit.offer(prog, self.V, self.F, 0.02, "box", lambda d: None, 240, rep, pipeline._better)
        self.assertIs(got, prog)
        self.assertFalse(rep["cadfit"]["verified"])
        self.assertNotIn("chosen", rep["cadfit"])
        # a low IoU is not translated or built at all
        c = cadfit.candidate((self.V, self.F), 240, search=lambda V, F, s: {"script": _box_script(), "iou": 0.4})
        self.assertFalse(c["verified"])
        self.assertIn("IoU 0.400", c["report"]["error"])

    def test_verified_candidate_replaces_a_worse_one(self):
        from form.recon import cadfit, pipeline
        prog = {"report": {"method": "sketches and extrusions", "verified": False, "error": "no"}, "verified": False}
        rep = {}
        good = lambda V, F, s: {"script": _box_script(), "iou": 1.0, "seconds": 0.1}
        with mock.patch.dict(os.environ, {"FORM_RECON_CADFIT": "1"}), mock.patch.object(cadfit, "_search", good), \
                mock.patch.object(cadfit, "status", return_value={"installed": True}):
            got = cadfit.offer(prog, self.V, self.F, 0.02, "box", lambda d: None, 240, rep, pipeline._better)
        self.assertTrue(got["verified"])
        self.assertTrue(rep["cadfit"]["chosen"])
        self.assertEqual(got["report"]["also_tried"][0]["method"], "sketches and extrusions")


class Deadline(unittest.TestCase):
    def test_child_is_killed_at_its_deadline_and_keeps_what_it_sent(self):
        from form.recon import cadfit
        V, F = _mesh()
        t = time.perf_counter()
        r = cadfit._search(V, F, 4.0, runner=_runner_sends_then_hangs)
        took = time.perf_counter() - t
        self.assertLess(took, 12.0)
        self.assertGreaterEqual(took, 3.9)
        self.assertTrue(r["timed_out"])
        self.assertEqual(r["iou"], 0.5)
        r = cadfit._search(V, F, 3.0, runner=_runner_hangs)
        self.assertTrue(r["timed_out"])
        self.assertIn("found nothing", r["error"])

    def test_real_search_respects_a_short_deadline(self):
        from form.recon import cadfit
        if not cadfit.status()["installed"]:
            self.skipTest("CADFit's libraries are not installed")
        V, F = _mesh("filleted_block")
        t = time.perf_counter()
        r = cadfit._search(V, F, 6.0)
        self.assertLess(time.perf_counter() - t, 15.0)
        self.assertIn("seconds", r)

    def test_runs_from_a_daemon_worker_within_the_hard_deadline(self):
        """The real child path, started from a daemon process as the kernel worker is (no mock of the start): it
        runs instead of failing with multiprocessing's "daemonic processes are not allowed to have children", and
        its slice never exceeds the time left before the reconstruction's hard deadline."""
        import multiprocessing as mp
        from form.recon import cadfit
        if not cadfit.status()["installed"]:
            self.skipTest("CADFit's libraries are not installed")
        ctx = mp.get_context("spawn")
        for left in (4.0, 1.0):
            a, b = ctx.Pipe(duplex=False)
            p = ctx.Process(target=_in_daemon, args=(b, left), daemon=True)
            p.start()
            b.close()
            self.assertTrue(a.poll(120), "the daemon worker did not answer")
            rep = a.recv()
            p.join(10)
            self.assertNotIn("AssertionError", str(rep.get("error")), rep)
            self.assertNotIn("did not run", str(rep.get("error")), rep)
            self.assertLessEqual(rep["seconds_allowed"], left)
            if left >= cadfit.MIN_RUN_S:
                self.assertIsNotNone(rep.get("search_seconds"), rep)        # the child ran
                self.assertLess(rep["search_seconds"], left + 3.0)
            else:
                self.assertIn("was not started", rep["error"])
                self.assertIsNone(rep.get("search_seconds"))
            print(f"\nCADFit from a daemon worker, {left:g} s left: {rep.get('search_seconds')} s searching, "
                  f"{rep['_took']} s in all; {str(rep.get('error'))[:120]}")

    def test_without_its_code_it_says_what_it_needs(self):
        from form.recon import cadfit
        with mock.patch.object(cadfit, "_bundled", return_value=False):
            st = cadfit.status()
            self.assertFalse(st["installed"])
            self.assertEqual(st["needs"], "form-studio[cadfit]")
            c = cadfit.candidate((np_zeros(), np_tri()), 240)
        self.assertFalse(c["verified"])
        self.assertIn("form-studio[cadfit]", c["report"]["error"])

    def test_slice_of_the_budget(self):
        from form.recon import cadfit
        self.assertEqual(cadfit.seconds_for(240), 60.0)
        self.assertEqual(cadfit.seconds_for(10), cadfit.SECONDS[0])
        self.assertEqual(cadfit.seconds_for(10_000), cadfit.SECONDS[1])


class Disabled(unittest.TestCase):
    def test_off_by_default_and_by_config(self):
        from form.recon import cadfit
        with tempfile.TemporaryDirectory() as d:
            toml = Path(d) / "studio.toml"
            toml.write_text("[recon]\ncadfit = false\n")
            env = {k: v for k, v in os.environ.items() if k != "FORM_RECON_CADFIT"}
            env["FORM_CONFIG"] = str(toml)
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertFalse(cadfit.enabled())
                toml.write_text("[recon]\ncadfit = true\n")
                self.assertTrue(cadfit.enabled())
                (Path(d) / "studio.toml").write_text("")
                self.assertFalse(cadfit.enabled())             # the default
            with mock.patch.dict(os.environ, {"FORM_RECON_CADFIT": "0"}):
                self.assertFalse(cadfit.enabled())

    def test_pipeline_unchanged_when_disabled(self):
        from form.recon import cadfit
        prog = {"report": {"method": "sketches and extrusions"}, "verified": False}
        rep = {"layers": {}}
        boom = mock.Mock(side_effect=AssertionError("CADFit ran while disabled"))
        with mock.patch.dict(os.environ, {"FORM_RECON_CADFIT": "0"}), mock.patch.object(cadfit, "candidate", boom):
            got = cadfit.offer(prog, None, None, 0.02, "x", lambda d: None, 240, rep, lambda a, b: True)
        self.assertIs(got, prog)
        self.assertEqual(rep, {"layers": {}})
        boom.assert_not_called()

    def test_hook_is_small_and_imports_nothing_heavy(self):
        import subprocess
        src = (Path(__file__).resolve().parents[1] / "form" / "recon" / "pipeline.py").read_text()
        self.assertEqual(src.count("cadfit."), 1)
        code = ("import sys, form.recon.cadfit as c; c.status(); "
                "print([m for m in ('trimesh', 'manifold3d', 'sklearn', 'build123d') if m in sys.modules])")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=str(Path(__file__).resolve().parents[1]), timeout=120)
        self.assertEqual(out.stdout.strip(), "[]", out.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
