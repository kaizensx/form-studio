"""The export ladder's mesh steps (form/meshclose.py) on small meshes with the defects seen in real exports: a crack
between faces (T-junction), a face with no triangles, two walls touching along an edge, near-coincident vertices.
numpy only; the OCCT rungs are covered by tests/test_chat_failures.py and scripts/export_corpus.py."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from form import mesh_audit, meshclose as mc  # noqa: E402

CUBE_P = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float) * 10
CUBE_F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                   [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])


class Topology(unittest.TestCase):
    def test_closed_cube(self):
        self.assertTrue(mc.closed(mc.topology(CUBE_P, CUBE_F)))

    def test_missing_face_is_filled_flat(self):
        P, F, info = mc.repair(CUBE_P, CUBE_F[2:], time.time() + 10)          # the bottom face got no triangles
        self.assertTrue(mc.closed(mc.topology(P, F)), mc.topology(P, F))
        self.assertEqual(info["holes_filled"], 1)
        self.assertAlmostEqual(info["fill_deviation_mm"], 0.0, places=9)     # the hole is flat: so is the fill
        self.assertGreater(mc._volume(P, F), 999.0)

    def test_t_junction_is_stitched(self):
        """The bottom face's edge 0-1 gets a midpoint the side face does not have: a crack, closed by splitting."""
        P = np.vstack([CUBE_P, [[5, 0, 0]]])
        F = CUBE_F.copy().tolist()
        F[0] = [0, 2, 8]
        F.append([8, 2, 1])
        F = np.array(F)
        self.assertFalse(mc.closed(mc.topology(P, F)))
        F2, n = mc.stitch(P, F, 1e-3)
        self.assertEqual(n, 1)
        self.assertTrue(mc.closed(mc.topology(P, F2)), mc.topology(P, F2))

    def test_walls_touching_along_an_edge_are_split_apart(self):
        P = np.vstack([CUBE_P, CUBE_P + [10, 10, 0]])                       # two cubes sharing the edge x=y=10
        F = np.vstack([CUBE_F, CUBE_F + 8])
        P, F = mc.weld(P[F])
        self.assertGreater(mc.topology(P, F)["nonmanifold"], 0)
        P2, F2, n = mc.split_touching(P, F)
        self.assertEqual(n, 2)
        self.assertTrue(mc.closed(mc.topology(*mc.weld(P2[F2]))))
        self.assertLessEqual(np.linalg.norm(P2[len(P):][:, None] - P[None], axis=2).min(axis=1).max(), mc.SPLIT_MM * 1.01)

    def test_cluster_merges_vertices_across_grid_cells(self):
        V = np.array([[[0.0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0.00049, 0, 0], [0, 1, 0], [0, 0, 1]]])
        _, F = mc.cluster(V, 1e-3)
        self.assertEqual(F[0][0], F[1][0])


class Sidecar(unittest.TestCase):
    def test_parts_are_audited_one_by_one(self):
        d = Path(tempfile.mkdtemp())
        a, b = CUBE_P[CUBE_F], (CUBE_P + [10, 0, 0])[CUBE_F]                # two cubes sharing a face
        mc.write(d / "two.stl", [a, b])
        tris, _fmt, _sha = mesh_audit.read_stl(d / "two.stl")
        self.assertEqual(tris.parts, [12, 12])
        self.assertEqual(mesh_audit.audit(tris, expected_components=2)["status"], "PASS_LIMITED_SCREEN")
        self.assertIn("nonmanifold_edges", mesh_audit.audit(list(tris), expected_components=2)["failures"])
        mc.write(d / "two.stl", [np.concatenate([a, b])])                  # one piece: the sidecar goes
        self.assertFalse((d / "two.stl.parts.json").exists())


class GuardedMesher(unittest.TestCase):
    """The mesher in a child process (form/meshguard.py), as a shape with many faces is meshed."""

    def test_starting_the_child_is_not_the_meshers_time(self):
        """The time limit is for the mesher. Loading the kernel in the child took longer than a rung's limit on a
        Windows runner, so every rung "did not finish" and no STL was made: here the limit (1 s) is shorter than any
        start, and the box is meshed all the same."""
        try:
            from build123d import Box
        except Exception:                                   # pragma: no cover
            self.skipTest("needs build123d")
        from form import meshguard
        d = Path(tempfile.mkdtemp())
        meshguard.write_brep(Box(10, 20, 30), d / "box.brep")
        stats: dict = {}
        t = time.monotonic()
        res = meshguard.run(d / "box.brep", -1, 0.01, 0.1, False, 1.0, stats)
        took = time.monotonic() - t
        self.assertIsNotNone(res)
        V, missing = res[0]
        self.assertEqual((len(V), missing), (12, 0))
        self.assertGreater(stats["start_s"], 0.0)
        self.assertLessEqual(stats["start_s"], took)

    def test_the_budget_does_not_pay_for_the_start(self):
        try:
            from build123d import Box, Cylinder, Pos
        except Exception:                                   # pragma: no cover
            self.skipTest("needs build123d")
        from form import meshguard
        shape = Box(40, 40, 6)
        for i in range(4):
            for j in range(4):
                shape = shape - Pos(-15 + 10 * i, -15 + 10 * j, 0) * Cylinder(2, 6)
        self.assertGreater(len(shape.faces()), mc.GUARD_FACES // 4)
        real = meshguard.run

        def slow(*a, **k):                                  # a machine where the child takes 3 s longer to start
            time.sleep(3.0)
            r = real(*a, **k)
            if len(a) > 6 and isinstance(a[6], dict):
                a[6]["start_s"] = a[6].get("start_s", 0.0) + 3.0
            return r
        M = mc._Mesher(shape, guard=True)
        meshguard.run = slow
        try:
            t0 = time.time()
            out, rep = mc._close(M, shape, 0.01, 0.1, 4.0, t0, t0 + 4.0)     # a 4 s budget, less than one such start
        finally:
            meshguard.run = real
            M.close()
        self.assertTrue(rep["per_solid"][0]["closed"], rep)
        self.assertGreaterEqual(M.start_s, 3.0)


if __name__ == "__main__":
    unittest.main()
