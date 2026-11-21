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


if __name__ == "__main__":
    unittest.main()
