"""The reconstruction critics (form/recon/gates.py) and the GMS-compatible score (form/recon/gms.py).

    .venv/bin/python -m unittest tests.test_recon_gates
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recon_fixtures as fx  # noqa: E402
from form.recon import distance, gates, gms, mesh  # noqa: E402


def _stl(name, folder):
    T, _ = mesh.read_triangles(fx.export(name, folder)[0])
    V, F, _ = mesh.weld(T)
    return V, F


def _tess(name, tol=0.005):
    from form.kernel import _tessellate
    return _tessellate(fx.FIXTURES[name]()[0], tol)


def _rot_x(V, deg):
    a = np.radians(deg)
    R = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    c = V.mean(axis=0)
    return (V - c) @ R.T + c


class Gates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="gates-"))

    def test_size_tolerance_scales_with_the_part(self):
        small = np.array([[0, 0, 0], [5, 5, 5.0]])
        big = np.array([[0, 0, 0], [400, 300, 100.0]])
        self.assertEqual(gates.size_tolerance(small), gates.SIZE_FLOOR)
        self.assertAlmostEqual(gates.size_tolerance(big), 0.0015 * np.linalg.norm([400, 300, 100]), places=9)

    def test_a_faithful_candidate_passes_every_gate(self):
        for name in ("bolt_flange", "box_with_holes"):
            V, F = _stl(name, self.tmp)
            r = gates.check(V, F, *_tess(name), tol=0.02)
            self.assertTrue(r["passed"], (name, r["verdict"], r["openings"]["mismatches"]))
            self.assertGreater(r["openings"]["openings_checked"], 0)
            self.assertGreater(r["occupancy"]["iou"], 0.99)

    def test_a_filled_cavity_passes_hausdorff_and_fails_occupancy(self):
        V, F = _stl("hollow_block", self.tmp)
        P2, T2 = _stl("cavity_filler", self.tmp)
        # the candidate: the hollow block and a loose block filling its cavity. Every face of it lies on a face of the
        # part, so the two-sided surface distance is zero, but it is solid where the part is hollow.
        P, T = np.vstack([V, P2]), np.vstack([F, T2 + len(V)])
        self.assertLess(distance.hausdorff(V, F, P, T)["hausdorff_mm"], 0.02)
        r = gates.check(V, F, P, T, tol=0.02)
        self.assertFalse(r["passed"])
        self.assertIn("occupancy", r["failed"])
        self.assertIn("voids", r["failed"])
        cavity = fx.FIXTURES["hollow_block"]()[1]["cavity_mm3"]
        self.assertAlmostEqual(r["occupancy"]["missing_void_mm3"], cavity, delta=0.05 * cavity)
        self.assertTrue(gates.check(V, F, *_tess("hollow_block"), tol=0.02)["passed"])   # the real part passes

    def test_a_round_hole_modelled_square_fails_the_opening_gate(self):
        V, F = _stl("box_with_holes", self.tmp)
        P, T = _stl("box_with_square_hole", self.tmp)
        r = gates.check(V, F, P, T, tol=0.02)
        self.assertTrue(r["occupancy"]["occupancy_ok"])       # the volume barely moves: the per-opening check sees it
        self.assertEqual(r["failed"], ["openings"])
        m = r["openings"]["mismatches"][0]
        self.assertEqual(m["kind"], "wrong shape")
        self.assertTrue(m["part"].startswith("circle"))
        self.assertTrue(m["candidate"].startswith("rectangle"))
        self.assertLess(m["iou"], gates.OPENING_IOU)
        self.assertLess(abs(m["center"][0]) + abs(m["center"][1]), 0.1)

    def test_a_missing_hole_is_reported_as_missing(self):
        V, F = _stl("box_with_holes", self.tmp)
        P, T = mesh.weld(np.asarray(_box_triangles()))[:2]          # the same box with no holes at all
        r = gates.opening_gate(V, F, P, T, tol=0.02)
        self.assertFalse(r["openings_ok"])
        self.assertTrue(all(m["kind"] == "missing opening" for m in r["mismatches"]))
        self.assertEqual(r["mismatch_count"], 5)


def _box_triangles(sx=60.0, sy=40.0, sz=10.0):
    """A plain 60 x 40 x 10 box (centred in X and Y, from Z 0) as outward triangles."""
    x, y = sx / 2, sy / 2
    c = np.array([[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0], [-x, -y, sz], [x, -y, sz], [x, y, sz], [-x, y, sz]])
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6),
         (3, 0, 4), (3, 4, 7)]
    return c[np.array(f)]


class GMS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.V, cls.F = _stl("bolt_flange", Path(tempfile.mkdtemp(prefix="gms-")))

    def test_identical_meshes_score_one(self):
        self.assertEqual(gms.gms(self.V, self.F, self.V, self.F)["gms"], 1.0)

    def test_it_falls_monotonically_with_rotation(self):
        scores = [gms.gms(self.V, self.F, _rot_x(self.V, d), self.F)["gms"] for d in (0, 1, 2, 5, 10, 20, 40)]
        self.assertEqual(scores[0], 1.0)
        self.assertTrue(all(b < a for a, b in zip(scores, scores[1:])), scores)
        self.assertLess(scores[-1], 0.2)

    def test_a_faithful_tessellation_scores_high(self):
        self.assertGreater(gms.gms(self.V, self.F, *_tess("bolt_flange"))["gms"], 0.9)

    @unittest.skipUnless(importlib.util.find_spec("pykdtree") and importlib.util.find_spec("trimesh")
                         and os.environ.get("FORM_GMS_UPSTREAM"),
                         "cross-check needs pykdtree, trimesh and FORM_GMS_UPSTREAM=<your copy of cadena utils/gms.py>")
    def test_matches_upstream_gms(self):
        import trimesh
        spec = importlib.util.spec_from_file_location("cadena_gms", os.environ["FORM_GMS_UPSTREAM"])
        up = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(up)
        for d in (0, 3, 10):
            W = _rot_x(self.V, d)
            theirs = float(up.aoc_gms(trimesh.Trimesh(self.V, self.F), trimesh.Trimesh(W, self.F))[1])
            ours = gms.gms(self.V, self.F, W, self.F)["gms"]
            self.assertAlmostEqual(ours, theirs, delta=0.03, msg=f"rotation {d} deg")


class ScanArtifacts(unittest.TestCase):
    def test_each_artifact_is_seeded_and_does_what_it_says(self):
        T = np.asarray(_box_triangles())
        V, F, _ = mesh.weld(T)
        Vn, _ = fx.scan_artifact(V, F, "noise", 0.01, seed=3)
        self.assertTrue(np.array_equal(Vn, fx.scan_artifact(V, F, "noise", 0.01, seed=3)[0]))
        self.assertGreater(np.abs(Vn - V).max(), 0)
        Vq, _ = fx.scan_artifact(V + 0.013, F, "quantised", 0.02)
        self.assertTrue(np.allclose(Vq / 0.02, np.round(Vq / 0.02)))
        _, Fd = fx.scan_artifact(V, F, "dropout", 0.1)
        self.assertEqual(len(Fd), len(F) - 1)


class CadenaBench(unittest.TestCase):
    """scripts/cadena_bench.py never downloads unless asked and never writes into the repository."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import cadena_bench
        cls.cb = cadena_bench

    def test_it_refuses_paths_inside_the_repository(self):
        root = self.cb.ROOT
        for p in (root / "docs" / "CADENA.md", root / "x.md", root):
            with self.assertRaises(SystemExit):
                self.cb.outside_repo(p, "the report")
        self.assertEqual(self.cb.outside_repo(Path(tempfile.gettempdir()) / "c.md", "the report").name, "c.md")
        with self.assertRaises(SystemExit):
            self.cb.main(["--data", tempfile.gettempdir(), "--out", str(root / "docs" / "CADENA.md")])

    def test_it_needs_a_source_and_does_not_download_by_default(self):
        with self.assertRaises(SystemExit):
            self.cb.main(["--out", str(Path(tempfile.gettempdir()) / "c.md")])
        called = []
        keep = self.cb.download
        self.cb.download = lambda *a: called.append(a)
        try:
            with self.assertRaises(SystemExit):              # an empty folder: nothing found, nothing fetched
                self.cb.main(["--data", tempfile.mkdtemp(), "--out", str(Path(tempfile.gettempdir()) / "c.md")])
        finally:
            self.cb.download = keep
        self.assertEqual(called, [])

    def test_aggregates_leave_invalid_parts_out_of_the_means(self):
        rows = [{"gates": "pass", "gms": 0.9, "occupancy_iou": 0.99, "within": True, "brep_pct": 100.0,
                 "editable_pct": 80.0, "seconds": 10.0, "gate_seconds": 0.5},
                {"gates": "no STEP", "gms": None, "occupancy_iou": None, "within": False, "brep_pct": 0.0,
                 "editable_pct": None, "seconds": 2.0, "gate_seconds": None}]
        g = self.cb.aggregate(rows)
        self.assertEqual((g["parts"], g["valid"], g["invalid_rate"], g["gms_mean"], g["gates_pass_rate"]),
                         (2, 1, 0.5, 0.9, 1.0))


class GatesRankCandidates(unittest.TestCase):
    """The pipeline ranks candidates by verified, then the critics' verdict, then editable share (pipeline._better)."""

    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp(prefix="rank-"))
        cls.V, cls.F = _stl("hollow_block", tmp)
        P2, T2 = _stl("cavity_filler", tmp)
        cls.filled = (np.vstack([cls.V, P2]), np.vstack([cls.F, T2 + len(cls.V)]))
        cls.faithful = _tess("hollow_block")

    def _cands(self):
        # the filled one drives more of its surface and is as close to the mesh: without the critics it would win
        filled = {"verified": True, "P": self.filled[0], "T": self.filled[1],
                  "report": {"method": "filled", "editable_pct": 100.0, "hausdorff_mm": 0.0}}
        faithful = {"verified": True, "P": self.faithful[0], "T": self.faithful[1],
                    "report": {"method": "faithful", "editable_pct": 60.0, "hausdorff_mm": 0.001}}
        return filled, faithful

    def test_a_filled_cavity_candidate_loses_to_the_faithful_one(self):
        from form.recon import pipeline
        filled, faithful = self._cands()
        self.assertTrue(pipeline._better(filled, faithful))              # no verdicts yet: editable share decides
        gx = pipeline._Gates(self.V, self.F, 0.02, 240.0)
        self.assertTrue(gx.better(faithful, filled))
        self.assertFalse(gx.better(filled, faithful))
        self.assertIn("voids", filled["report"]["gates"]["failed"])
        self.assertTrue(faithful["report"]["gates"]["passed"])
        self.assertEqual(gx.runs, 2)                                       # each verdict once, kept in the report
        self.assertLess(gx.summary()["spent_s"], gx.share)

    def test_an_unverified_candidate_never_wins_on_gates(self):
        from form.recon import pipeline
        filled, faithful = self._cands()
        faithful["verified"] = False
        gx = pipeline._Gates(self.V, self.F, 0.02, 240.0)
        self.assertTrue(gx.better(filled, faithful))
        self.assertEqual(gx.runs, 0)                                       # verified decides: no gate time spent

    def test_the_gates_keep_to_their_slice_of_the_budget(self):
        from form.recon import pipeline
        filled, faithful = self._cands()
        gx = pipeline._Gates(self.V, self.F, 0.02, 1.0)                    # 0.04 s: too little for one check
        self.assertIsNone(gx.verdict(filled))
        self.assertIn("not run", filled["report"]["gates"]["verdict"])
        self.assertTrue(gx.better(filled, faithful))                       # "not run" is no objection

    def test_candidates_are_a_list_through_the_same_gates(self):
        from form.recon import pipeline
        self.assertEqual([k for k, _ in pipeline.CANDIDATES], ["learned", "cadfit"])
        filled, faithful = self._cands()
        gx = pipeline._Gates(self.V, self.F, 0.02, 240.0)
        ctx = {"better": gx.better}

        def offer(prog, ctx):                                            # a new generator: one entry in the list
            return filled if ctx["better"](filled, prog) else prog
        keep = pipeline.CANDIDATES
        try:
            pipeline.CANDIDATES = keep + [("filler", offer)]
            prog = faithful
            for _, o in pipeline.CANDIDATES[2:]:
                prog = o(prog, ctx)
        finally:
            pipeline.CANDIDATES = keep
        self.assertIs(prog, faithful)


class HoleFilling(unittest.TestCase):
    def test_two_holes_touching_at_a_vertex_are_two_loops(self):
        V, F, _ = mesh.weld(np.asarray(_box_triangles()))
        v = 0                                           # remove two triangles that share only the vertex 0
        ts = [i for i, f in enumerate(F.tolist()) if v in f]
        a = ts[0]
        b = next(t for t in ts[1:] if len(set(F[a].tolist()) & set(F[t].tolist())) == 1)
        G = np.delete(F, [a, b], axis=0)
        top = mesh.topology(V, G)
        self.assertEqual(top["boundary_edges"], 6)
        self.assertEqual(sorted(len(L) for L in top["_loops"]), [3, 3])
        V2, F2, rec = mesh.fill_holes(V, G, top["_loops"])
        self.assertTrue(mesh.topology(V2, F2)["closed"])
        self.assertEqual([r["method"] for r in rec], ["the one missing triangle"] * 2)

    def test_dropout_is_filled_back_exactly(self):
        V, F = _stl("bolt_flange", Path(tempfile.mkdtemp(prefix="drop-")))
        Vd, Fd = fx.scan_artifact(V, F, "dropout")
        top = mesh.topology(Vd, Fd)
        self.assertGreater(top["boundary_loops"], 10)
        V2, F2, rec = mesh.fill_holes(Vd, Fd, top["_loops"])
        self.assertTrue(mesh.topology(V2, F2)["closed"])
        self.assertTrue(all(r["filled"] for r in rec))
        self.assertLess(distance.hausdorff(V, F, V2, F2)["hausdorff_mm"], 1e-6)

    def test_a_crease_is_kept_and_a_large_hole_is_refused(self):
        V, F, _ = mesh.weld(np.asarray(_box_triangles()))
        # the two triangles of one side: a planar 4-edge hole; one more on the next side: a hole across the edge
        side = [i for i, f in enumerate(F.tolist()) if np.allclose(V[f][:, 1], -20)]
        top = mesh.topology(V, np.delete(F, side, axis=0))
        V2, F2, rec = mesh.fill_holes(V, np.delete(F, side, axis=0), top["_loops"])
        self.assertEqual(rec[0]["edges"], 4)
        self.assertTrue(rec[0]["planar"])
        self.assertLess(distance.hausdorff(V, F, V2, F2)["hausdorff_mm"], 1e-9)
        V3, F3, rec = mesh.fill_holes(V, np.delete(F, side, axis=0), top["_loops"], max_area=1.0)
        self.assertFalse(rec[0]["filled"])
        self.assertEqual(rec[0]["repair"], "hole left open (large)")
        self.assertEqual(len(F3), len(F) - 2)

    def test_pipeline_refuses_only_large_holes(self):
        from form.recon import pipeline
        tmp = Path(tempfile.mkdtemp(prefix="holes-"))
        V, F, _ = mesh.weld(np.asarray(_box_triangles()))
        top = [i for i, f in enumerate(F.tolist()) if np.allclose(V[f][:, 2], 10)]
        p = tmp / "lidless.stl"
        mesh.write_stl(p, V, np.delete(F, top, axis=0))                  # the whole top missing: 2400 mm2
        rep = pipeline.reconstruct(p, tmp / "out", "lidless", 0.02, 0)
        self.assertIn("too large to fill", rep["error"])
        self.assertNotIn("result", rep)


class ScanNoise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.V, cls.F = _stl("bolt_flange", Path(tempfile.mkdtemp(prefix="noise-")))

    def test_an_exact_mesh_is_left_alone(self):
        from form.recon import denoise
        Vs, rep = denoise.measure_and_snap(self.V, self.F, 0.02)
        self.assertFalse(rep["noisy"])
        self.assertTrue(np.array_equal(Vs, self.V))
        Vq, _ = fx.scan_artifact(self.V, self.F, "quantised")
        self.assertFalse(denoise.measure_and_snap(Vq, self.F, 0.05)[1]["noisy"])   # its planes are still exact

    def test_noise_is_measured_and_the_vertices_go_back_on_their_surfaces(self):
        from form.recon import denoise
        Vn, F = fx.scan_artifact(self.V, self.F, "noise")
        Vs, rep = denoise.measure_and_snap(Vn, F, 0.05)
        self.assertTrue(rep["noisy"])
        self.assertAlmostEqual(rep["noise_mm"], 0.01, delta=0.002)
        self.assertGreater(rep["surface_share_pct"], 95)
        self.assertLessEqual(rep["max_move_mm"], 0.05)
        z = np.round(Vs[:, 2], 6)
        self.assertLessEqual(len(np.unique(z)), 8)           # the caps share their heights again (noisy: thousands)

    def test_the_program_route_reads_the_noisy_flange(self):
        from form.recon import denoise, program, verify
        Vn, F = fx.scan_artifact(self.V, self.F, "noise")
        Vs, _ = denoise.measure_and_snap(Vn, F, 0.05)
        r = program.recipe(Vs, F, 0.05, name="flange", limit=0.05, out_dir=Path(tempfile.mkdtemp(prefix="nprog-")))
        self.assertTrue(r["verified"], r["report"].get("error"))
        self.assertEqual(r["report"]["editable_pct"], 100.0)
        self.assertLessEqual(verify.compare(Vn, F, r["P"], r["T"])["hausdorff_mm"], 0.05)   # against the noisy mesh


if __name__ == "__main__":
    unittest.main()
