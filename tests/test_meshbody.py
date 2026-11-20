"""form.meshbody: sculpted meshes as surface bodies (quad remesh -> cage -> NURBS solid) and as mesh bodies with
exact CAD features (WP-F). The full-size acceptance run (a 200k-triangle helmet) runs with FORM_SLOW=1."""
import os
import time
import unittest

import numpy as np

from form import meshbody as mb

SLOW = os.environ.get("FORM_SLOW") == "1"


class Fixtures(unittest.TestCase):
    def test_helmet_fixture_is_a_closed_thick_shell(self):
        T = mb.fixture_helmet(100)
        V, F = mb.weld(T)
        from form.recon.mesh import topology
        t = topology(V, F)
        self.assertTrue(t["closed"])
        self.assertGreater(t["volume_mm3"], 0)
        parts = mb.split_shell(V, F)
        self.assertGreater(parts["share"], 0.95)
        self.assertEqual(len(mb.boundary_loop(F[parts["outer"]])), len(mb.boundary_loop(F[parts["inner"]])))


class SurfaceBody(unittest.TestCase):
    _cache = {}

    @classmethod
    def shell(cls):
        if "shell" not in cls._cache:
            cls._cache["shell"] = mb.organic_solid(mb.fixture_helmet(140), tol=0.3, kind="shell")
        return cls._cache["shell"]

    def test_shell_mesh_becomes_a_closed_solid_within_tolerance(self):
        solid, rep = self.shell()
        self.assertTrue(rep["valid"] and rep["closed"])
        self.assertEqual(rep["faces"], 3)
        self.assertLessEqual(rep["max_mm"], 0.4, rep)        # a coarser mesh than the acceptance run: its own facets count
        self.assertEqual(rep["tier"], mb.TIER_SURFACE)

    def test_closed_prop_becomes_patches_g1_within_tolerance(self):
        solid, rep = mb.organic_solid(mb.fixture_bust(40), tol=0.5, kind="closed")
        self.assertTrue(rep["valid"] and rep["closed"])
        self.assertLessEqual(rep["faces"], 2000)
        self.assertLessEqual(rep["max_mm"], 0.5, rep)
        self.assertLess(rep["smoothness"]["worst_deg"], 1.0)

    def test_hybrid_magnet_pockets_and_split_rebuild_fast(self):
        from form.craft import organic, subd
        _, rep = self.shell()
        cg = rep["cages"]

        def build(d):
            body = subd.trimmed_shell_solid(cg["outer"], cg["inner"], cg["radius"])
            spots = organic.split_spots(body, -10.0, (60.0, 105.0), d)
            return organic.split_with_magnets(body, -10.0, spots, d, 2.0)
        front, back = build(6.0)
        self.assertTrue(front.is_valid and back.is_valid)
        t = time.perf_counter()
        f2, b2 = build(8.0)
        dt = time.perf_counter() - t
        self.assertLess(dt, 10.0)
        self.assertTrue(f2.is_valid and b2.is_valid)
        self.assertNotAlmostEqual(f2.volume, front.volume, 0)        # bigger pockets, bigger bosses

    @unittest.skipUnless(SLOW, "FORM_SLOW=1: the 200k-triangle acceptance run (about a minute)")
    def test_acceptance_200k_triangles(self):
        T = mb.fixture_helmet(225)
        self.assertGreaterEqual(len(T), 200000)
        t = time.perf_counter()
        solid, rep = mb.organic_solid(T, tol=0.3)
        self.assertLess(time.perf_counter() - t, 180)
        self.assertTrue(rep["valid"] and rep["closed"] and rep["within_tolerance"], rep)
        self.assertLessEqual(rep["faces"], 2000)


@unittest.skipUnless(mb.has_manifold(), "manifold3d is optional (pip install manifold3d)")
class MeshBodies(unittest.TestCase):
    def test_exact_cuts_keep_the_mesh_closed(self):
        from build123d import Box, Cylinder, Pos
        body = mb.MeshBody.from_shape(Box(40, 40, 20))
        v0 = body.volume()
        body.cut(Pos(0, 0, 8) * Cylinder(3.1, 6), "magnet pocket")
        rep = body.report()
        self.assertTrue(rep["closed"])
        self.assertAlmostEqual(v0 - body.volume(), np.pi * 3.1 ** 2 * 5, delta=3.0)      # z 5..10 of the box
        a, b = body.split((0, 0, 0), (1, 0, 0))
        self.assertAlmostEqual(a.volume() + b.volume(), body.volume(), delta=1.0)
        self.assertEqual(rep["tier"], mb.TIER_MESH)


if __name__ == "__main__":
    unittest.main()
