"""The build-up draws each feature's own edges before its solid (form/app/geometry.py mesh_edges): the edges of the
faces the kernel made, read from the feature's triangles."""
import importlib.util
import unittest

import numpy as np

SKIP = "PySide6 is not installed" if importlib.util.find_spec("PySide6") is None else ""


def _quad(a, b, c, d, off):
    return [a, b, c, d], [[off, off + 1, off + 2], [off, off + 2, off + 3]]


@unittest.skipIf(SKIP, SKIP)
class MeshEdges(unittest.TestCase):
    def _cube(self, shared: bool):
        c = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        if shared:
            return np.array(c, dtype=np.float32), np.array([t for f in faces for t in ((f[0], f[1], f[2]), (f[0], f[2], f[3]))], dtype=np.uint32)
        P, T = [], []
        for f in faces:
            p, t = _quad(*(c[i] for i in f), off=len(P))
            P += p
            T += t
        return np.array(P, dtype=np.float32), np.array(T, dtype=np.uint32)

    def test_faces_the_kernel_meshed_apart_give_their_outlines(self):
        from form.app.geometry import mesh_edges
        E = mesh_edges(*self._cube(shared=False))
        self.assertEqual(E.shape, (24, 6))                       # four edges per face, no diagonals
        self.assertTrue(np.allclose(np.abs(E[:, :3] - E[:, 3:]).sum(axis=1), 1.0))

    def test_a_welded_mesh_gives_its_creases(self):
        from form.app.geometry import mesh_edges
        E = mesh_edges(*self._cube(shared=True))
        self.assertEqual(E.shape, (12, 6))
        self.assertTrue(np.allclose(np.abs(E[:, :3] - E[:, 3:]).sum(axis=1), 1.0))

    def test_nothing_and_nonsense_draw_nothing(self):
        from form.app.geometry import mesh_edges
        self.assertEqual(len(mesh_edges(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32))), 0)
        self.assertEqual(len(mesh_edges(np.zeros((2, 3), np.float32), np.array([[0, 1, 5]], np.uint32))), 0)


if __name__ == "__main__":
    unittest.main()
