"""Exact SubD to CAD (WP1): creases, open borders, merged B-spline faces, named regions and the measured report.

Every threshold here is checked against a measurement from form.craft.subd_report (deviation from a level-6
Catmull-Clark limit mesh, seam angles, BRepCheck, STEP round trip); none is assumed."""
import json
import math
import os
import unittest

import numpy as np

from form.craft import subd
from form.craft import subd_report as R


class Rules(unittest.TestCase):
    def test_smooth_step_matches_the_classic_rules(self):
        V, F = subd.quad_sphere(2, 10)
        V1, Q = subd.catmull_clark(V, F)
        # vertex point of a valence-3 corner: (Favg + 2 Ravg + (n - 3) V) / n
        v = 0
        faces = [f for f in F if v in f]
        Fa = np.mean([V[f].mean(0) for f in faces], axis=0)
        nb = {int(x) for f in faces for k, x in enumerate(f) if x != v and (f[(k + 1) % 4] == v or f[k - 1] == v)}
        Ra = np.mean([(V[v] + V[x]) / 2 for x in nb], axis=0)
        n = len(nb)
        self.assertLess(np.abs(V1[v] - (Fa + 2 * Ra + (n - 3) * V[v]) / n).max(), 1e-12)
        self.assertEqual(Q.shape, (4 * len(F), 4))

    def test_crease_and_boundary_rules(self):
        V, F = R.tube_cage(8, 3, 10, 20)
        V1, Q = subd.catmull_clark(V, F)
        n = 8
        # a boundary vertex: (a + 6 v + b) / 8 along the border
        self.assertLess(np.abs(V1[0] - (V[n - 1] + 6 * V[0] + V[1]) / 8).max(), 1e-12)
        # an infinitely sharp edge's point is its midpoint
        V2, F2 = subd.quad_sphere(2, 10)
        eq = R.equator_edges(V2, F2)
        a, b = eq[0]
        Vs, Qs = subd.catmull_clark(V2, F2, creases=eq)
        mid = (V2[a] + V2[b]) / 2
        self.assertLess(np.min(np.linalg.norm(Vs - mid, axis=1)), 1e-12)

    def test_semi_sharp_crease_is_resolved_by_its_levels(self):
        V, F = subd.quad_sphere(2, 50)
        eq = R.equator_edges(V, F)
        self.assertEqual(subd.Cage(V, F, creases={e: 2.0 for e in eq}).levels, 2)
        self.assertEqual(subd.Cage(V, F, creases={e: 1.5 for e in eq}).levels, 2)
        c = subd.Cage(V, F, creases={e: 2.0 for e in eq})
        self.assertEqual(c.creases, {})                    # smooth after ceil(s) levels
        sharp = subd.Cage(V, F, levels=2, creases=eq)
        self.assertEqual(len(sharp.creases), len(eq) * 4)  # an infinite crease survives, split each level
        soft = subd.Cage(V, F, levels=2)
        def radius(c):                                     # the equator: a sharper crease stays wider
            P = subd.limit_points(c.V, c.F, c.creases)
            return float(np.hypot(P[:, 0], P[:, 1]).max())
        self.assertLess(radius(soft), radius(subd.Cage(V, F, levels=2, creases={e: 1.0 for e in eq})))
        self.assertLess(radius(subd.Cage(V, F, levels=2, creases={e: 1.0 for e in eq})), radius(c))
        self.assertLess(radius(c), radius(sharp))


class Exactness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = R.fixtures()
        cls.rep = {}
        for name, (cage, _) in cls.fx.items():
            cls.rep[name] = R.report(cage)
        out = os.environ.get("FORM_SUBD_REPORT")
        if out:
            with open(out, "w") as f:
                json.dump({k: {"deviation": v["deviation"], "seams": v["seams"], "brep": v["brep"], "step": v["step"]}
                           for k, v in cls.rep.items()}, f, indent=1, default=float)

    def test_regular_torus_is_exact(self):
        d = self.rep["torus_regular"]["deviation"]
        self.assertTrue(d["exact"])
        self.assertLessEqual(d["max_mm"], 1e-6)
        self.assertEqual(d["level"], 6)
        self.assertIn("exact", d["claim"])
        self.assertLess(self.rep["torus_regular"]["seams"]["worst_deg"], 1e-6)

    def test_open_tube_is_exact_with_planar_caps(self):
        d = self.rep["tube_open"]["deviation"]
        self.assertTrue(d["exact"])
        self.assertLessEqual(d["max_mm"], 1e-6)
        cage = self.fx["tube_open"][0]
        self.assertTrue(cage.is_open())
        cage.solid()
        self.assertEqual(cage._caps, ["planar", "planar"])

    def test_extraordinary_cages_are_measured_not_called_exact(self):
        for name in ("cube_sphere", "genus2"):
            d = self.rep[name]["deviation"]
            self.assertFalse(d["exact"], name)
            self.assertNotIn("exact:", d["claim"])
            self.assertGreater(d["irregular_points"], 0)
            self.assertLessEqual(d["max_per_100mm"], 0.05, f"{name}: {d}")

    def test_crease_cages_are_measured(self):
        for name in ("lens_sharp", "lens_semisharp", "rim_sharp"):
            d = self.rep[name]["deviation"]
            self.assertFalse(d["exact"], name)                 # the cube corners are extraordinary
            self.assertLessEqual(d["max_per_100mm"], 0.05, f"{name}: {d}")

    def test_a_regular_crease_is_the_b_spline_of_its_vertices(self):
        V, F = subd.quad_sphere(2, 50)
        eq = R.equator_edges(V, F)
        cage = subd.Cage(V, F, creases=eq)
        # the equator polygon in order
        ring = [eq[0][0]]
        nb = {}
        for a, b in eq:
            nb.setdefault(a, []).append(b)
            nb.setdefault(b, []).append(a)
        prev = None
        while len(ring) < len(eq):
            nxt = [x for x in nb[ring[-1]] if x != prev][0]
            prev = ring[-1]
            ring.append(nxt)
        pos = {v: k for k, v in enumerate(ring)}
        n = len(ring)
        B = cage.patches()
        sides = {0: [(0, 0), (0, 1), (0, 2), (0, 3)], 1: [(0, 3), (1, 3), (2, 3), (3, 3)],
                 2: [(3, 3), (3, 2), (3, 1), (3, 0)], 3: [(3, 0), (2, 0), (1, 0), (0, 0)]}
        checked = 0
        for q, f in enumerate(cage.F):
            for i in range(4):
                v, w = int(f[i]), int(f[(i + 1) % 4])
                if subd._ekey(v, w) not in cage.sharp_edges():
                    continue
                # the uniform cubic B-spline span between crease vertices v and w, as Bezier points
                step = 1 if ring[(pos[v] + 1) % n] == w else -1
                p, nn = V[ring[(pos[v] - step) % n]], V[ring[(pos[w] + step) % n]]
                want = np.array([(p + 4 * V[v] + V[w]) / 6, (2 * V[v] + V[w]) / 3, (V[v] + 2 * V[w]) / 3,
                                 (V[v] + 4 * V[w] + nn) / 6])
                got = np.array([B[q][r, c] for r, c in sides[i]])
                self.assertLess(np.abs(got - want).max(), 1e-9)
                checked += 1
        self.assertEqual(checked, 2 * len(eq))             # both sides of the crease carry the same exact curve

    def test_seams(self):
        self.assertLessEqual(self.rep["cube_sphere"]["seams"]["worst_deg"], 1.0)
        for name, rep in self.rep.items():
            s = rep["seams"]
            self.assertLessEqual(s["worst_deg"], 2.0, name)  # genus2 at 3 levels: measured 1.84 (see the report)
            self.assertGreaterEqual(s["within_1deg"], 0.99, name)

    def test_brep_valid_and_step_round_trip(self):
        for name, rep in self.rep.items():
            self.assertTrue(rep["brep"]["valid"], name)
            self.assertEqual(rep["brep"]["solids"], 1, name)
            self.assertTrue(rep["step"]["valid"], name)
            self.assertLessEqual(rep["step"]["rel_diff"], 1e-3, name)

    def test_regular_blocks_halve_the_face_count(self):
        for name in ("torus_regular", "cube_sphere", "tube_open"):
            b = self.rep[name]["brep"]
            self.assertLessEqual(b["faces"], b["faces_one_per_patch"] // 2, f"{name}: {b}")
            self.assertGreater(b["bspline_faces"], 0)
        self.assertEqual(self.rep["torus_regular"]["brep"]["faces"], 4)

    def test_a_hole_cuts_through_every_fixture(self):
        from build123d import Cylinder, Plane
        from form import craft
        done = []
        for name in ("torus_regular", "cube_sphere", "genus2", "lens_sharp", "tube_open"):
            cage, (c, ax, d) = self.fx[name]
            s = cage.solid()
            tool = Plane(origin=c, z_dir=ax) * Cylinder(d / 2, 400)
            r = craft.cut(s, tool)
            self.assertTrue(r.is_valid, name)
            self.assertEqual(len(r.solids()), 1, name)
            self.assertGreater(s.volume - r.volume, 0.5 * math.pi * (d / 2) ** 2 * 5, name)
            done.append(name)
        self.assertEqual(len(done), 5)


class OpenAndRegions(unittest.TestCase):
    def test_thicken_an_open_skin(self):
        V, F = R.tube_cage(12, 4, 30, 60)
        s = subd.Cage(V, F).solid(close="thicken", thickness=2.0)
        self.assertTrue(s.is_valid)
        self.assertGreater(s.volume, 0.8 * 2 * math.pi * 29 * 50 * 2.0)

    def test_non_planar_border_gets_a_filling_cap(self):
        V, F = subd.quad_sphere(2, 50)
        keep = [f for f in F if not all(V[x][2] > 25 for x in f)]         # the top face removed
        cage = subd.Cage(V, keep, levels=1)
        self.assertTrue(cage.is_open())
        s = cage.solid()
        self.assertTrue(s.is_valid)
        self.assertEqual(cage._caps, ["filling"])

    def test_regions_label_faces_and_give_frames(self):
        from form import craft
        V, F = subd.quad_sphere(2, 50)
        lid = [i for i, f in enumerate(F) if all(V[x][2] > 25 for x in f)]
        cage = subd.Cage(V, F, levels=1, creases=R.region_border(F, lid), regions={"lid": lid})
        s = cage.solid()
        faces = cage.region_faces(s, "lid")
        self.assertGreater(len(faces), 0)
        self.assertTrue(all(f.center().Z > 25 for f in faces))
        self.assertTrue(all(m["region"] in ("lid", None) for m in cage.face_meta()))
        at, axis = cage.region_frame("lid")
        self.assertGreater(axis[2], 0.99)
        self.assertGreater(at[2], 35)
        pair = craft.magnet_pair(at, (-axis[0], -axis[1], -axis[2]))
        self.assertEqual(pair.spec["stock"], "6x2")
        tool = cage.region_tool("lid", out=1.0, depth=4.0)
        self.assertTrue(tool.is_valid)
        piece = s & tool
        self.assertGreater(piece.volume, 0)
        parts = craft.parts(lid=piece, body=craft.cut(s, tool), touching=[("lid", "body")])
        self.assertEqual(len(parts.solids()), 2)
        with self.assertRaises(Exception):
            cage.region_frame("nope")


class Compatibility(unittest.TestCase):
    def test_acc_operator_and_patches_unchanged_for_a_smooth_cage(self):
        V, F = subd.quad_sphere(3, 40)
        c = subd.Cage(V, F, levels=1)
        M, val = subd.acc_operator(len(c.V), c.F)
        self.assertEqual(M.shape, (16 * len(c.F), len(c.V)))
        B = (M @ c.V).reshape(-1, 4, 4, 3)
        self.assertLess(np.abs(subd.tangent_planes(B, c.F, val) - c.patches()).max(), 1e-12)


if __name__ == "__main__":
    unittest.main()
