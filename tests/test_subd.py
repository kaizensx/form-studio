"""form.craft.subd: subdivision cages to exact NURBS solids (WP-F)."""
import math
import unittest

import numpy as np

from form.craft import subd


def torus_cage(n=12, m=8, R=40.0, r=12.0):
    """A closed quad cage in which every vertex has four quads round it (no extraordinary vertex)."""
    V = []
    for i in range(n):
        for j in range(m):
            a, b = 2 * math.pi * i / n, 2 * math.pi * j / m
            V.append(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
    F = [[i * m + j, ((i + 1) % n) * m + j, ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m]
         for i in range(n) for j in range(m)]
    return np.array(V), F


class Grids(unittest.TestCase):
    def test_fit_reproduces_a_smooth_surface(self):
        g = np.linspace(0, 1, 60)
        U, W = np.meshgrid(g, g, indexing="ij")
        P = np.stack([U * 100, W * 80, 10 * np.sin(U * 3) * np.cos(W * 2)], -1).reshape(-1, 3)
        C, u, v, d = subd.fit_grid_refined(P, U.ravel(), W.ravel(), 14, 14)
        self.assertLess(d.max(), 0.02)

    def test_occt_surface_matches_numpy(self):
        C = subd.dome_cage(200, 160, 120, n=10)
        s = subd.grid_surface(C)
        for u, v in ((0.5, 0.5), (0.2, 0.7), (0.91, 0.33)):
            p = s.Value(u, v)
            q = subd.grid_eval(C, [u], [v])[0]
            self.assertLess(math.dist((p.X(), p.Y(), p.Z()), q), 1e-9)

    def test_handles_move_the_surface_locally(self):
        C = subd.dome_cage(200, 160, 120, n=12)
        h = [subd.Handle("bump", "Bump", (100, 0, 60), 40, (1, 0, 0), 0, -10, 10)]
        D = subd.apply_handles(C, h, {"bump": 6})
        moved = np.linalg.norm(D - C, axis=2)
        self.assertGreater(moved.max(), 1.5)                  # cage points near the centre move most
        far = np.linalg.norm(C - np.array([100, 0, 60]), axis=2) > 40
        self.assertEqual(moved[far].max(), 0.0)
        self.assertEqual(h[0].param("shell").key, "bump")


class Solids(unittest.TestCase):
    def test_sculpted_shell_is_three_exact_faces(self):
        C = subd.dome_cage(220, 180, 160, n=12, rim=lambda t: 10 * (1 - math.cos(t)), tuck=0.2)
        s = subd.sculpted_shell(C, 2.5)
        self.assertTrue(s.is_valid)
        self.assertEqual(len(s.solids()), 1)
        self.assertEqual(len(s.faces()), 3)
        self.assertGreater(s.volume, 0)

    def test_regular_cage_is_exactly_smooth(self):
        V, F = torus_cage()
        c = subd.Cage(V, F)
        self.assertEqual(c.extraordinary(), 0)
        self.assertLess(subd.seam_angles(c.patches(), c.F)["worst_deg"], 1e-6)

    def test_closed_cage_solid_and_g1_at_extraordinary_points(self):
        V, F = subd.quad_sphere(3, 40)
        c = subd.Cage(V, F, levels=1)
        self.assertEqual(c.extraordinary(), 8)
        rep = subd.seam_angles(c.patches(), c.F)
        self.assertLess(rep["worst_deg"], 1.0)
        s = c.solid()
        self.assertTrue(s.is_valid)
        self.assertEqual(len(s.faces()), len(c.F))
        self.assertAlmostEqual(s.volume, 4 / 3 * math.pi * 40 ** 3, delta=0.25 * 4 / 3 * math.pi * 40 ** 3)

    def test_catmull_clark_makes_quads_of_any_polygons(self):
        V = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], float)
        F = [[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]]
        V2, Q = subd.catmull_clark(V, F)
        self.assertEqual(Q.shape, (12, 4))
        self.assertEqual(len(V2), 4 + 4 + 6)


if __name__ == "__main__":
    unittest.main()
