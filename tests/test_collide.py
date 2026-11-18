"""Mesh proximity and joint sweeps (form/collide.py) on geometry whose answers are known.

Two boxes overlapping, a pin in a hole with 0.2 mm clearance, a hinged lid that hits a wall at 95° (the angle checked
against the B-rep by bisection), and sweeps stopped by their time budget.
"""
import math
import time
import unittest

import numpy as np

from form import collide
from form.collide import Body, query, surface_distance, sweep, travel
from form.recipes.assembly import hinge, joint_matrix

I = np.eye(4)


def box(lo, hi):
    lo, hi = np.array(lo, float), np.array(hi, float)
    V = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    T = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4],
         [1, 5, 7], [1, 7, 3]]
    return V, np.array(T)


def cylinder(r, h, n=48, z0=0.0):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.c_[r * np.cos(a), r * np.sin(a)]
    V = np.r_[np.c_[ring, np.full(n, z0)], np.c_[ring, np.full(n, z0 + h)], [[0, 0, z0], [0, 0, z0 + h]]]
    T = []
    for i in range(n):
        j = (i + 1) % n
        T += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return V, np.array(T)


def tube(ri, ro, h, n=48):
    """A ring with a bore: an outer wall facing out, a bore facing in (closed and consistently oriented)."""
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    V = np.array([[r * math.cos(t), r * math.sin(t), z] for r in (ri, ro) for z in (0, h) for t in a])
    T = []
    for i in range(n):
        j = (i + 1) % n
        ib0, ib1, ob0, ob1, jb0, jb1, jo0, jo1 = i, n + i, 2 * n + i, 3 * n + i, j, n + j, 2 * n + j, 3 * n + j
        T += [[ob0, jo0, jo1], [ob0, jo1, ob1], [ib0, ib1, jb1], [ib0, jb1, jb0],
              [ob1, jo1, jb1], [ob1, jb1, ib1], [ob0, ib0, jb0], [ob0, jb0, jo0]]
    return V, np.array(T)


def at(x, y, z):
    M = np.eye(4)
    M[:3, 3] = (x, y, z)
    return M


class Pairs(unittest.TestCase):
    def test_two_boxes(self):
        big, small = Body(*box([0, 0, 0], [20, 20, 20])), Body(*box([0, 0, 0], [10, 10, 10]))
        r = query(small, big, at(5, 5, 17), 1.0)                     # sunk 3 mm into the top
        self.assertEqual(r.state(0.0), "overlap")
        self.assertTrue(r.cross)
        self.assertGreater(r.depth, 0.0)
        self.assertLessEqual(r.depth, 3.0 + 1e-9)                    # a lower bound on the true 3 mm
        self.assertLessEqual(r.box[0][2], 20)                        # the marker spans where the surfaces cross (z = 20)
        self.assertGreaterEqual(r.box[1][2], 20)
        self.assertEqual(query(small, big, at(5, 5, 20), 1.0).state(0.0), "contact")      # resting on it
        g = query(small, big, at(5, 5, 20.05), 1.0)
        self.assertEqual(g.state(0.0), "gap")
        self.assertAlmostEqual(g.d, 0.05, places=9)
        far = query(small, big, at(5, 5, 25), 1.0)
        self.assertEqual(far.state(0.0), "far")
        self.assertGreaterEqual(far.d, 1.0)                          # a lower bound beyond the cutoff
        nested = query(small, big, at(5, 5, 5), 1.0)                 # wholly inside: surfaces never meet
        self.assertTrue(nested.nested)
        self.assertEqual(nested.state(0.0), "overlap")

    def test_pin_in_hole_with_clearance(self):
        hole, pin = Body(*tube(2.6, 6, 10)), Body(*cylinder(2.4, 14, z0=-2))
        t = time.perf_counter()
        r = query(pin, hole, I, 1.0)
        self.assertLess(time.perf_counter() - t, 10)
        self.assertEqual(r.state(0.0), "gap")
        self.assertTrue(r.exact)
        # the polygons are inscribed: the gap is 0.2 mm at the vertices, a little less at mid-edges of the pin (none here
        # since the pin's vertices touch its circle), so the mesh gap lies between 0.2 * cos(pi/48)-ish and 0.2
        self.assertAlmostEqual(r.d, 0.2, delta=0.01)
        bad = query(Body(*cylinder(2.7, 14, z0=-2)), hole, I, 1.0)   # 0.1 mm too fat
        self.assertEqual(bad.state(0.0), "overlap")
        self.assertAlmostEqual(bad.depth, 0.1, delta=0.03)

    def test_surface_distance_and_inside(self):
        b = Body(*box([0, 0, 0], [10, 10, 10]))
        np.testing.assert_allclose(surface_distance(b, [[5, 5, 5], [5, 5, 13], [1, 5, 5]]), [5, 3, 1], atol=1e-9)
        self.assertEqual(collide.inside(b, [[5, 5, 5], [5, 5, 13]]).tolist(), [True, False])


def exact_lid_contact(y0):
    """First contact angle of the lid with the wall, from the B-rep (bisection on the solids' distance)."""
    from build123d import Box, Location, Pos
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
    lid, stop = Pos(20, 10, 11) * Box(40, 20, 2), Pos(20, y0 + 2, 15) * Box(40, 4, 30)
    lo, hi = 90.0, 120.0
    for _ in range(30):
        m = (lo + hi) / 2
        t = gp_Trsf()
        t.SetRotation(gp_Ax1(gp_Pnt(0, 20, 12), gp_Dir(-1, 0, 0)), math.radians(m))
        lo, hi = (m, hi) if (Location(t) * lid).distance_to(stop) > 1e-7 else (lo, m)
    return lo


class Sweeps(unittest.TestCase):
    """A 40 x 20 x 10 box, its 2 mm lid hinged along the back top edge, and a wall behind the hinge."""
    Y0 = 21.575                                    # wall face: the lid first touches it at 95° (checked below)

    def setUp(self):
        self.bodies = {"box": Body(*box([0, 0, 0], [40, 20, 10])), "lid": Body(*box([0, 0, 10], [40, 20, 12])),
                       "wall": Body(*box([0, self.Y0, 0], [40, self.Y0 + 4, 30]))}
        self.j = hinge("lid", (-1, 0, 0), (0, 20, 12), (0, 120), samples=13)
        self.tr = travel(self.bodies["lid"], I, "hinge", self.j.axis, self.j.origin)

    def run_sweep(self, seconds=60.0, refine=True):
        frames = lambda v: {"lid": joint_matrix(self.j, v), "box": I, "wall": I}
        return sweep(self.bodies, frames, [("lid", "box"), ("lid", "wall")], [float(x) for x in np.linspace(0, 120, 13)],
                     lambda b, a, c: self.tr(a, c), tol=0.0, warn=0.1, cutoff=2.0,
                     deadline=time.perf_counter() + seconds, refine=refine, min_step=0.25)

    def test_hinged_lid_hits_the_wall_at_95_degrees(self):
        exact = exact_lid_contact(self.Y0)
        self.assertAlmostEqual(exact, 95.0, delta=0.1)
        r = self.run_sweep()
        self.assertFalse(r.partial)
        self.assertIsNotNone(r.contact_from)
        self.assertAlmostEqual(r.contact_from, exact, delta=0.5)     # located by bisection
        hit = [s for s in r.samples if s.state == "overlap"]
        self.assertTrue(hit and min(s.value for s in hit) >= exact - 1e-6)    # never reports a hit before the real one
        self.assertTrue(all(s.pair == ("lid", "wall") for s in hit))
        # the bound proves most of the way up to the contact free between samples
        proven = sum(b - a for a, b in r.proven)
        self.assertGreater(proven, 70)
        self.assertTrue(all(b <= exact + 1e-6 for a, b in r.proven))

    def test_sampled_only_without_refinement(self):
        r = self.run_sweep(refine=False)
        self.assertEqual(len(r.samples), 13)
        self.assertEqual(r.proven, [])
        self.assertTrue(r.unproven)

    def test_budget_stops_with_the_range_covered(self):
        r = self.run_sweep(seconds=0.0)
        self.assertTrue(r.partial)
        self.assertIsNone(r.covered)
        frames = lambda v: {"lid": joint_matrix(self.j, v), "box": I, "wall": I}
        calls = []

        def slow(s):                                   # every sample takes 0.2 s: the budget allows a few
            calls.append(s.value)
            time.sleep(0.2)
        r = sweep(self.bodies, frames, [("lid", "box"), ("lid", "wall")], [float(x) for x in np.linspace(0, 120, 13)],
                  lambda b, a, c: self.tr(a, c), tol=0.0, warn=0.1, cutoff=2.0, deadline=time.perf_counter() + 0.7,
                  on_sample=slow)
        self.assertTrue(r.partial)
        self.assertEqual(r.covered[0], 0.0)
        self.assertLess(r.covered[1], 120.0)
        self.assertEqual(sorted(s.value for s in r.samples if not s.refined), [v for v in calls if v in
                                                                                 np.linspace(0, 120, 13)])


if __name__ == "__main__":
    unittest.main()
