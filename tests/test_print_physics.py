"""Print physics (form/printphys): support volume against shapes worked by hand, the Pareto front on synthetic
objectives, the layered material against closed forms, the warp model against its own equation, and, through the
kernel, the search, the pick and the Bench entries on a real design.

Two classes need more than this Python: a real layered strength study needs the FEA engine (form.fea.python(); the
transversely isotropic beam itself is in the verification suite, tests/test_fea_verification.py), and the slicer
comparison needs a slicer that resolves here. Each is skipped with the reason otherwise.
"""
import copy
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-print-")
os.environ["FORM_DATA"] = TMP                      # never the owner's data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from form import analysis, config, fea, studies  # noqa: E402
from form.fea import material as fmat  # noqa: E402
from form.fea import solve, study  # noqa: E402
from form.printphys import cli as print_cli  # noqa: E402
from form.printphys import geom, orient, sources, timemodel, tools, warp  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

ENGINE = fea.python(config.load())
NEEDS_ENGINE = unittest.skipUnless(ENGINE, "the FEA engine is not installed here (set FORM_FEA_PYTHON to its Python)")


# ---- meshes worked by hand ---------------------------------------------------------------------------------------

def _ears(poly):
    """Triangles of a simple polygon given counter-clockwise (ear clipping)."""
    idx = list(range(len(poly)))
    tris = []

    def area2(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def inside(p, a, b, c):
        return area2(a, b, p) > 1e-12 and area2(b, c, p) > 1e-12 and area2(c, a, p) > 1e-12
    while len(idx) > 3:
        for k in range(len(idx)):
            i, j, m = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i], poly[j], poly[m]
            if area2(a, b, c) <= 1e-12:
                continue
            if any(inside(poly[q], a, b, c) for q in idx if q not in (i, j, m)):
                continue
            tris.append((i, j, m))
            idx.pop(k)
            break
        else:
            raise ValueError("not a simple polygon")
    tris.append(tuple(idx))
    return tris


def prism(poly_xz, depth):
    """A closed mesh: the polygon (x, z), counter-clockwise seen from -y, extruded from y = 0 to y = depth."""
    n = len(poly_xz)
    P = np.array([[x, 0.0, z] for x, z in poly_xz] + [[x, float(depth), z] for x, z in poly_xz])
    T = []
    for a, b, c in _ears(poly_xz):
        T.append((a, b, c))                          # front cap, outward -y
        T.append((n + a, n + c, n + b))              # back cap, outward +y
    for i in range(n):
        j = (i + 1) % n
        T += [(i, n + i, n + j), (i, n + j, j)]
    m = geom.Mesh(P, np.array(T))
    assert m.volume > 0, "the test mesh must face outward"
    return m


TEE = [(10, 0), (20, 0), (20, 20), (30, 20), (30, 25), (0, 25), (0, 20), (10, 20)]
CEE = [(0, 0), (30, 0), (30, 5), (10, 5), (10, 20), (30, 20), (30, 25), (0, 25)]
LEAN = [(0, 0), (10, 0), (30, 20), (20, 20)]
DOWN = [0, 0, -1]


def cylinder(r, length, n=720):
    """A cylinder lying along y, its lowest line at z = 0."""
    ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
    ring = np.column_stack([r * np.cos(ang), np.zeros(n), r + r * np.sin(ang)])
    P = np.concatenate([ring, ring + [0, length, 0], [[0, 0, r]], [[0, length, r]]])
    T = []
    for i in range(n):
        j = (i + 1) % n
        T += [(i, n + i, n + j), (i, n + j, j), (2 * n, i, j), (2 * n + 1, n + j, n + i)]
    m = geom.Mesh(P, np.array(T))
    if m.volume < 0:
        m = geom.Mesh(P, np.array(T)[:, ::-1])
    return m


class SupportVolume(unittest.TestCase):
    """Every number here is worked by hand from the shape."""

    def test_a_tee_is_two_columns_down_to_the_plate(self):
        r = geom.evaluate(prism(TEE, 10), DOWN, three_point=True)
        self.assertAlmostEqual(r["support_mm3"], 2 * 10 * 10 * 20, places=6)       # two 10 x 10 overhangs, 20 mm up
        self.assertAlmostEqual(r["support_mm3_spread"], 0.0, places=6)
        self.assertAlmostEqual(r["support_shadow_mm2"], 200.0, places=6)
        self.assertAlmostEqual(r["support_on_part_mm2"], 0.0, places=6)
        self.assertAlmostEqual(r["support_contact_mm2"], 200.0, places=6)          # only what it holds up
        self.assertAlmostEqual(r["contact_mm2"], 100.0, places=6)                  # the stem's foot
        self.assertFalse(r["rests_on_supports"])

    def test_a_cee_stands_its_support_on_the_part(self):
        r = geom.evaluate(prism(CEE, 10), DOWN, three_point=True)
        self.assertAlmostEqual(r["support_mm3"], 20 * 10 * 15, places=6)           # 20 x 10 overhang, 15 mm to the arm below
        self.assertAlmostEqual(r["support_on_part_mm2"], 200.0, places=6)
        self.assertAlmostEqual(r["support_contact_mm2"], 400.0, places=6)          # held up + stood on
        self.assertAlmostEqual(r["contact_mm2"], 300.0, places=6)

    def test_the_same_cee_measured_to_the_plate_would_be_wrong(self):
        to_plate = 20 * 10 * 20
        self.assertLess(geom.evaluate(prism(CEE, 10), DOWN)["support_mm3"], to_plate - 900)

    def test_a_leaning_wall_counts_only_past_the_critical_angle(self):
        m = prism(LEAN, 10)                          # its underside leans 45 degrees from vertical
        self.assertAlmostEqual(geom.evaluate(m, DOWN, critical_deg=45)["support_mm3"], 0.0, places=6)
        r = geom.evaluate(m, DOWN, critical_deg=30)
        self.assertAlmostEqual(r["support_mm3"], 10 * 20 * 20 / 2, places=6)       # a wedge: depth x base x height / 2
        self.assertAlmostEqual(r["support_shadow_mm2"], 200.0, places=6)
        self.assertAlmostEqual(r["overhang_mm2"], 10 * 20 * math.sqrt(2), places=6)

    def test_a_lying_cylinder_matches_the_integral(self):
        r, L = 10.0, 40.0
        got = geom.evaluate(cylinder(r, L), DOWN, critical_deg=45)["support_mm3"]
        want = L * r * r * (math.sqrt(2) - 0.5 - math.pi / 4)          # integral of r - sqrt(r2 - x2) over |x| < r / sqrt 2
        self.assertAlmostEqual(got / want, 1.0, delta=0.01)

    def test_turned_over_the_tee_needs_none(self):
        r = geom.evaluate(prism(TEE, 10), [0, 0, 1])
        self.assertAlmostEqual(r["support_mm3"], 0.0, places=6)
        self.assertAlmostEqual(r["contact_mm2"], 300.0, places=6)

    def test_a_piece_that_straddles_an_edge_is_bounded_by_the_spread(self):
        # the cee's overhang reaches past the arm below when the arm is shorter: part of its shadow lands on the plate
        short = [(0, 0), (22, 0), (22, 5), (10, 5), (10, 20), (30, 20), (30, 25), (0, 25)]
        want = 12 * 10 * 15 + 8 * 10 * 20
        r = geom.evaluate(prism(short, 10), DOWN, res=0.5, samples_max=400000, three_point=True)
        self.assertAlmostEqual(r["support_mm3"] / want, 1.0, delta=0.01)
        self.assertLess(r["support_mm3_spread"], 0.02 * want)


class PlateAndSurface(unittest.TestCase):
    def test_tip_over_is_the_angle_from_the_centre_of_mass_to_the_edge_of_the_contact(self):
        box = prism([(0, 0), (20, 0), (20, 60), (0, 60)], 30)             # 20 x 30 foot, 60 tall
        r = geom.evaluate(box, DOWN)
        self.assertAlmostEqual(r["com_height_mm"], 30.0, places=6)
        self.assertAlmostEqual(r["tip_over_deg"], math.degrees(math.atan2(10, 30)), places=6)
        lying = geom.evaluate(box, [-1, 0, 0])                             # on its 30 x 60 side
        self.assertAlmostEqual(lying["tip_over_deg"], math.degrees(math.atan2(15, 10)), places=6)
        self.assertGreater(lying["tip_over_deg"], r["tip_over_deg"])

    def test_a_centre_of_mass_outside_the_contact_tips(self):
        hook = [(0, 0), (4, 0), (4, 20), (40, 20), (40, 24), (0, 24)]       # a thin post with a long arm
        r = geom.evaluate(prism(hook, 10), DOWN)
        self.assertEqual(r["tip_over_deg"], 0.0)
        self.assertLess(r["com_margin_mm"], 0.0)

    def test_on_an_edge_it_rests_on_supports(self):
        box = prism([(0, 0), (20, 0), (20, 20), (0, 20)], 20)
        r = geom.evaluate(box, geom.unit([1, 0, -1]))
        self.assertTrue(r["rests_on_supports"])
        self.assertEqual(r["tip_over_deg"], 0.0)

    def test_cusp_height_is_the_layer_times_the_cosine(self):
        m = prism(LEAN, 10)
        slope = np.abs(m.n[:, 2]) > 0.5                                      # the two faces leaning 45 degrees
        slope &= np.abs(m.n[:, 1]) < 0.5
        slope &= np.abs(np.abs(m.n[:, 2]) - 1) > 1e-6
        r = geom.evaluate(m, DOWN, layer=0.2, cosmetic=slope)
        self.assertAlmostEqual(r["cosmetic_cusp_um"], 200 * math.cos(math.radians(45)), places=6)
        top = np.abs(m.n[:, 2] - 1) < 1e-9
        self.assertAlmostEqual(geom.evaluate(m, DOWN, layer=0.2, cosmetic=top)["cosmetic_cusp_um"], 0.0, places=9)
        self.assertAlmostEqual(geom.evaluate(prism(TEE, 10), DOWN, cosmetic=np.ones(len(prism(TEE, 10).T), bool))["cosmetic_supported_mm2"], 200.0, places=6)

    def test_stress_across_the_layers_is_the_normal_stress_on_the_layer_plane(self):
        s = np.array([[10.0, 0, 0, 0, 0, 0], [0, 0, -5.0, 0, 0, 0], [0, 0, 0, 4.0, 0, 0]])
        self.assertAlmostEqual(geom.across_layers(s, [0, 0, -1])["tension_MPa"], 0.0)       # 10 MPa in x, layers stacked in z
        self.assertAlmostEqual(geom.across_layers(s, [-1, 0, 0])["tension_MPa"], 10.0)      # stacked along the pull
        d = geom.unit([-1, 0, -1])
        self.assertAlmostEqual(geom.across_layers(s[:1], d)["tension_MPa"], 5.0)            # sigma cos2(45)
        self.assertAlmostEqual(geom.across_layers(s[:1], d)["shear_MPa"], 5.0)              # sigma sin cos
        self.assertAlmostEqual(geom.across_layers(s[2:], [-1, 0, 0])["shear_MPa"], 4.0)
        self.assertAlmostEqual(geom.across_layers(s, [-1, 0, 0], ok=np.array([False, True, True]))["tension_MPa"], 0.0)


class Directions(unittest.TestCase):
    def test_the_geodesic_grid_has_the_stated_directions_evenly(self):
        for level, n in ((0, 12), (1, 42), (2, 162), (3, 642)):
            v = geom.icosphere(level)
            self.assertEqual(len(v), n)
            self.assertTrue(np.allclose(np.linalg.norm(v, axis=1), 1.0))
        v = geom.icosphere(2)
        near = np.degrees(np.arccos(np.clip(np.sort(v @ v.T, axis=1)[:, -2], -1, 1)))       # each one's nearest neighbour
        self.assertLess(near.max(), geom.spacing_deg(2) * 1.2)
        self.assertGreater(near.min(), geom.spacing_deg(2) * 0.6)

    def test_a_ring_is_at_the_step_asked(self):
        d = geom.unit([1, 2, 3])
        for p in geom.ring(d, 7.0):
            self.assertAlmostEqual(math.degrees(math.acos(float(p @ d))), 7.0, places=6)

    def test_the_rotation_puts_down_on_minus_z_as_the_exported_orientation_does(self):
        for d in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [0.3, -0.5, 0.2]):
            u = geom.unit(d)
            self.assertTrue(np.allclose(geom.rotation(u) @ u, [0, 0, -1], atol=1e-12))
            oid, dd = orient.canonical(u)
            self.assertTrue(np.allclose(analysis.orientation_matrix(oid) @ dd, [0, 0, -1], atol=1e-9))
        self.assertEqual(orient.canonical([0, 0, -1])[0], "as_modelled")
        self.assertEqual(orient.canonical([0, 0, 1])[0], "inverted")


class ParetoFront(unittest.TestCase):
    def test_a_small_table_by_hand(self):
        F = [[1, 5], [2, 2], [5, 1], [3, 3], [2, 2], [6, 6], [1, 6]]
        self.assertEqual(geom.pareto(F).tolist(), [True, True, True, False, True, False, False])

    def test_against_the_definition_on_random_objectives(self):
        rng = np.random.default_rng(7)
        for m in (2, 3, 5):
            F = rng.integers(0, 12, size=(160, m)).astype(float)
            keep = geom.pareto(F)
            for i in range(len(F)):
                dominated = any(np.all(F[j] <= F[i]) and np.any(F[j] < F[i]) for j in range(len(F)))
                self.assertEqual(bool(keep[i]), not dominated)
            for i in np.where(~keep)[0]:                                  # every dropped row is beaten by a kept one
                self.assertTrue(any(np.all(F[j] <= F[i]) and np.any(F[j] < F[i]) for j in np.where(keep)[0]))

    def test_one_objective_keeps_the_minimum_and_identical_rows_stay(self):
        self.assertEqual(geom.pareto([[3], [1], [2], [1]]).tolist(), [False, True, False, True])

    def test_the_search_finds_the_arc_between_two_synthetic_optima(self):
        # two objectives: the angle to +z and the angle to +x. No direction beats another exactly on the arc between.
        z, x = np.array([0, 0, 1.0]), np.array([1.0, 0, 0])

        def f(d):
            return {"a": math.degrees(math.acos(np.clip(d @ z, -1, 1))), "b": math.degrees(math.acos(np.clip(d @ x, -1, 1)))}
        s = orient.Search(None, timemodel.settings(), evaluate=f)
        out = s.run(level=2)
        front = [r for r in out["rows"] if r["on_front"]]
        self.assertGreaterEqual(len(front), 5)
        for r in front:                                                   # near the arc, where a + b = 90
            self.assertLess(r["objectives"]["a"] + r["objectives"]["b"], 90.0 + 6.0)
            self.assertLess(abs(r["down"][1]), 0.2)
        self.assertLess(min(r["objectives"]["a"] + r["objectives"]["b"] for r in front if 5 < r["objectives"]["a"] < 85), 90.2)
        self.assertLess(min(r["objectives"]["a"] for r in front), 0.01)   # both ends are found exactly (axis orientations)
        self.assertLess(min(r["objectives"]["b"] for r in front), 0.01)
        self.assertGreater(out["search"]["refinement_moves"], 0)          # the walk left the grid
        grid_only = orient.Search(None, timemodel.settings(), evaluate=f).run(level=2, refine=False)
        worst = max(r["objectives"]["a"] + r["objectives"]["b"] for r in grid_only["rows"] if r["on_front"])
        self.assertGreater(worst, max(r["objectives"]["a"] + r["objectives"]["b"] for r in front))

    def test_the_ranking_is_a_weighted_sum_scaled_over_the_front(self):
        rows = [{"id": "a", "objectives": {"support_mm3": 0.0, "time_s": 100.0}},
                {"id": "b", "objectives": {"support_mm3": 50.0, "time_s": 60.0}},
                {"id": "c", "objectives": {"support_mm3": 100.0, "time_s": 50.0}}]
        self.assertEqual([r["id"] for r in orient.rank(rows, {"support_mm3": 1, "time_s": 0})], ["a", "b", "c"])
        self.assertEqual([r["id"] for r in orient.rank(rows, {"support_mm3": 0, "time_s": 1})], ["c", "b", "a"])
        r = orient.rank(rows, {"support_mm3": 0.5, "time_s": 0.5})
        self.assertAlmostEqual(r[0]["score"], 0.5 * 0.5 + 0.5 * 0.2, places=4)
        self.assertEqual(r[0]["id"], "b")


class Search(unittest.TestCase):
    """The whole search on a mesh, without the kernel."""

    def test_the_tee_is_best_lying_down_or_turned_over_and_never_on_an_edge(self):
        s = orient.Search(prism(TEE, 10), timemodel.settings())
        out = s.run(level=1, rest=analysis.rest_directions(s.m.P, s.m.T))
        front = [r for r in out["rows"] if r["on_front"]]
        self.assertTrue(front)
        self.assertTrue(all(r["tip_over_deg"] > 0 for r in front))
        self.assertTrue(all(r["integrated"] == "fine" for r in front))
        self.assertNotIn("as_modelled", [r["id"] for r in front])         # standing, it needs 4000 mm3 of support
        self.assertAlmostEqual(min(r["support_mm3"] for r in front), 0.0, places=6)
        self.assertAlmostEqual(s.rows["as_modelled"]["support_mm3"], 4000.0, places=4)
        self.assertEqual(out["search"]["grid_directions"], 42)

    def test_free_admits_orientations_on_supports(self):
        m = prism(TEE, 10)
        a = orient.Search(m, timemodel.settings()).run(level=1)
        b = orient.Search(m, timemodel.settings(), free=True).run(level=1)
        self.assertFalse(any(r["rests_on_supports"] for r in a["rows"] if r["on_front"]))
        self.assertGreaterEqual(b["search"]["front"], a["search"]["front"])

    def test_strength_along_the_load_enters_as_an_objective(self):
        m = prism([(0, 0), (10, 0), (10, 60), (0, 60)], 10)               # a bar along z, pulled along z
        stress = {"stress": np.array([[0, 0, 20.0, 0, 0, 0]]), "S_z": 25.0, "S_xy": 40.0, "vm_peak": 20.0}
        s = orient.Search(m, timemodel.settings(), stress=stress)
        standing, lying = s.row([0, 0, -1]), s.row([-1, 0, 0])
        self.assertAlmostEqual(standing["strength"]["sf_across_layers"], 25.0 / 20.0)      # layers pulled apart
        self.assertEqual(standing["strength"]["governing"], "across_layers")
        self.assertAlmostEqual(lying["strength"]["safety_factor"], 40.0 / 20.0)            # the load runs in the layers
        self.assertEqual(lying["strength"]["governing"], "in_plane")
        self.assertLess(lying["objectives"]["strength_use"], standing["objectives"]["strength_use"])
        ld = orient.Search(m, timemodel.settings(), load={"direction": [0, 0, 1], "knockdown": 0.6})
        self.assertAlmostEqual(ld.row([0, 0, -1])["strength"]["strength_along_load"], 0.6)
        self.assertAlmostEqual(ld.row([-1, 0, 0])["strength"]["strength_along_load"], 1.0)


class TimeModel(unittest.TestCase):
    def test_settings_come_from_the_preset_and_say_so(self):
        s = timemodel.settings({"layer_height": "0.16", "wall_loops": "3", "sparse_infill_density": "20%",
                                "inner_wall_speed": ["120"], "support_threshold_angle": "30"}, {"filament_density": ["1.26"]})
        v, how = s["values"], s["how_known"]
        self.assertEqual((v["layer_height"], v["walls"], v["infill"], v["wall_speed"], v["density_g_cm3"]), (0.16, 3.0, 0.2, 120.0, 1.26))
        self.assertEqual(v["critical_deg"], 60.0)                          # the slicer counts from horizontal
        self.assertEqual(how["layer_height"], "slicer preset")
        self.assertEqual(how["skin_speed"], "assumed")
        prusa = timemodel.settings({"perimeters": 4, "fill_density": "15%", "perimeter_speed": 45})
        self.assertEqual((prusa["values"]["walls"], prusa["values"]["infill"], prusa["values"]["wall_speed"]), (4.0, 0.15, 45.0))
        self.assertTrue(all(h == "assumed" for h in timemodel.settings()["how_known"].values()))

    def test_a_solid_block_by_hand(self):
        s = timemodel.settings(given={"walls": 1, "top_layers": 0, "bottom_layers": 0, "infill": 1.0, "layer_overhead_s": 0,
                                      "layer_height": 0.2, "line_width": 0.4, "wall_speed": 100, "infill_speed": 100})
        g = {"height_mm": 10.0, "lateral_mm2": 400.0, "top_mm2": 100.0, "bottom_mm2": 100.0, "support_mm3": 0.0, "support_shadow_mm2": 0.0}
        t = timemodel.estimate(g, 1000.0, s)
        self.assertAlmostEqual(t["time_s"], 1000.0 / (0.4 * 0.2) / 100.0, places=6)         # every mm3 drawn once at 100 mm/s
        self.assertAlmostEqual(t["filament_g"], 1000.0 * 1.24e-3, places=9)
        self.assertEqual(t["layers"], 50)
        with_sup = timemodel.estimate({**g, "support_mm3": 500.0, "support_shadow_mm2": 50.0}, 1000.0, s)
        self.assertGreater(with_sup["time_s"], t["time_s"])
        self.assertGreater(with_sup["support_g"], 0)
        cal = timemodel.estimate(g, 1000.0, s, {"time": 2.0, "mass": 1.1})
        self.assertAlmostEqual(cal["time_s"], 2 * t["time_s"])
        self.assertAlmostEqual(cal["filament_g"], 1.1 * t["filament_g"])
        self.assertAlmostEqual(cal["uncalibrated"]["time_s"], t["time_s"])

    def test_gcode_feature_lengths(self):
        g = Path(TMP) / "f.gcode"
        g.write_text("M83\n; FEATURE: Outer wall\nG1 X1 Y1 E1.5\nG1 X2 E0.5\n; FEATURE: Support\nG1 X3 E2\nG1 E-0.8 F1800\n"
                     "G1 E0.8\n; FEATURE: Support interface\nG2 X1 Y1 I1 J0 E0.25\n", encoding="utf-8")
        f = orient.gcode_features(g)
        self.assertAlmostEqual(f["Outer wall"], 2.0)
        self.assertAlmostEqual(f["Support"], 2.0)                          # the retraction and its prime cancel
        self.assertAlmostEqual(f["Support interface"], 0.25)
        g.write_text("M82\nG92 E0\n;TYPE:Perimeter\nG1 X1 E1.0\nG1 X2 E2.5\n;TYPE:Support material\nG1 X3 E3.0\n", encoding="utf-8")
        f = orient.gcode_features(g)
        self.assertAlmostEqual(f["Perimeter"], 2.5)
        self.assertAlmostEqual(f["Support material"], 0.5)


class LayeredMaterial(unittest.TestCase):
    def test_equal_constants_give_the_isotropic_tensor(self):
        E, nu = 2600.0, 0.33
        C, S = solve.transverse_isotropic(E, E, nu, nu, E / (2 * (1 + nu)), [0.3, -0.5, 0.8])
        lam, mu = solve.lame(E, nu)
        self.assertTrue(np.allclose(C, solve.isotropic_tensor(float(lam), float(mu)), rtol=1e-10, atol=1e-8))
        self.assertTrue(np.allclose(np.einsum("ijkl,klmn->ijmn", C, S), np.einsum("ijkl,klmn->ijmn", C, S).transpose(2, 3, 0, 1)))

    def test_the_modulus_along_a_direction_matches_lekhnitskii(self):
        Ep, Ez, nup, nuzp, G = 2600.0, 2000.0, 0.33, 0.25, 900.0
        for ang in (0, 15, 30, 45, 60, 90):
            ax = [math.sin(math.radians(ang)), 0, math.cos(math.radians(ang))]      # the axis at `ang` from x... see below
            C, S = solve.transverse_isotropic(Ep, Ez, nup, nuzp, G, ax)
            # pull along z: the strain along z per unit stress is S_zzzz; the axis is `ang` away from z
            self.assertAlmostEqual(1.0 / S[2, 2, 2, 2], solve.young_along(Ep, Ez, nuzp, G, ang), places=6)
        self.assertAlmostEqual(solve.young_along(Ep, Ez, nuzp, G, 0), Ez)
        self.assertAlmostEqual(solve.young_along(Ep, Ez, nuzp, G, 90), Ep)

    def test_stress_and_strain_invert(self):
        C, S = solve.transverse_isotropic(2600.0, 2000.0, 0.33, 0.25, 900.0, [1, 1, 0])
        e = np.array([[1e-3, 2e-4, 0], [2e-4, -3e-4, 1e-4], [0, 1e-4, 5e-4]])
        self.assertTrue(np.allclose(np.einsum("ijkl,kl->ij", S, np.einsum("ijkl,kl->ij", C, e)), e))

    def test_an_unstable_material_is_refused(self):
        with self.assertRaises(solve.SolveError):
            solve.transverse_isotropic(2600.0, 200.0, 0.33, 0.9, 900.0, [0, 0, 1])

    def test_a_filament_takes_its_z_values_from_the_datasheet_and_says_what_is_assumed(self):
        m = fmat.resolve({"key": "PLA", "poisson": 0.33, "source": "test"})
        ly = fmat.layered(m, [0, 0, 1])
        self.assertEqual((ly["E_p"], ly["E_z"], ly["S_xy"], ly["S_z"]), (2580.0, 2060.0, 35.0, 31.0))
        self.assertEqual(ly["how_known"]["E_z"]["evidence"], "specified (datasheet)")
        self.assertIn("Bambu Lab", ly["how_known"]["S_z"]["source"])
        self.assertEqual(sorted(ly["assumed"]), ["G_zp", "nu_zp"])
        self.assertIn("Huber", ly["how_known"]["G_zp"]["rule"])
        self.assertAlmostEqual(ly["G_zp"], math.sqrt(2580 * 2060) / (2 * (1 + math.sqrt(0.33 * 2580 / 2060 * 0.33))), places=6)
        self.assertEqual(ly["knockdown"], {"strength": round(31 / 35, 3), "stiffness": round(2060 / 2580, 3), "what": "Z over in-plane, of the values above"})
        self.assertIsNone(ly["S_shear"])
        self.assertEqual(ly["how_known"]["S_shear"]["status"], "unsourced")

    def test_given_values_replace_the_assumptions(self):
        m = fmat.resolve({"key": "PLA", "poisson": 0.33, "source": "a tensile test"})
        ly = fmat.layered(m, [0, 0, 1], {"G_z_MPa": 950, "poisson_z": 0.3, "shear_strength_MPa": 18, "source": "a shear test"})
        self.assertEqual((ly["G_zp"], ly["nu_zp"], ly["S_shear"]), (950.0, 0.3, 18.0))
        self.assertEqual(ly["assumed"], [])
        self.assertEqual(ly["how_known"]["G_zp"]["evidence"], fmat.SPECIFIED)
        self.assertEqual(fmat.layered(m, [0, 0, 1], {"G_z_MPa": 950})["how_known"]["G_zp"]["evidence"], fmat.ASSUMED)

    def test_without_any_z_value_the_modulus_is_assumed_and_the_weak_factor_withheld(self):
        m = fmat.resolve({"name": "my resin", "E_GPa": 3.0, "poisson": 0.35, "yield_MPa": 50})
        ly = fmat.layered(m, [1, 0, 0])
        self.assertEqual(ly["E_z"], ly["E_p"])
        self.assertIn("E_z", ly["assumed"])
        self.assertIsNone(ly["S_z"])
        self.assertEqual(ly["S_xy"], 50.0)
        self.assertEqual(fmat.engine_material({**m, "layers": ly})["layers"]["axis"], [1.0, 0.0, 0.0])

    def test_a_definition_takes_a_layers_block(self):
        base = {"fixtures": [{"faces": [[0, 0, 0]]}], "loads": [{"type": "force", "faces": [[1, 1, 1]], "vector": [0, 0, -1]}]}
        d = study.clean({**base, "layers": {"orientation": "on_back", "sweep": ["as_modelled", "down:1,0,0"], "assume": {"G_z_MPa": "900"}}})
        self.assertEqual(d["layers"], {"orientation": "on_back", "sweep": ["as_modelled", "down:1,0,0"], "assume": {"G_z_MPa": 900.0}})
        self.assertEqual(study.clean({**base, "layers": {}}).get("layers"), None)
        self.assertEqual(study.clean({**base, "layers": {"sweep": []}})["layers"], {"orientation": "setup", "sweep": [], "assume": {}})
        for bad, word in (({"orientation": "sideways"}, "Unknown print orientation"), ({"assume": {"colour": 1}}, "Unknown value"),
                          ({"sweep": ["as_modelled"] * 9}, "up to eight")):
            with self.assertRaises(StudioError) as cm:
                study.clean({**base, "layers": bad})
            self.assertIn(word, str(cm.exception))
        with self.assertRaises(StudioError) as cm:
            study.clean({"kind": "modal", "layers": {"orientation": "setup"}})
        self.assertIn("static", str(cm.exception))

    def test_the_build_direction_is_opposite_to_what_faces_the_plate(self):
        self.assertTrue(np.allclose(study.layer_axis("as_modelled"), [0, 0, 1]))
        self.assertTrue(np.allclose(study.layer_axis("inverted"), [0, 0, -1], atol=1e-12))
        self.assertTrue(np.allclose(study.layer_axis("down:1,0,0"), [-1, 0, 0]))
        p = {"orientation": "on_left"}
        d = {"layers": {"orientation": "setup", "sweep": "auto"}}
        self.assertEqual(study.layer_orientation(p, d), "on_left")
        ids = [s["id"] for s in study.layer_sweep(p, d)]
        self.assertEqual(len(ids), 5)
        self.assertNotIn("on_left", ids)


class Warp(unittest.TestCase):
    def test_the_model_is_the_published_equation(self):
        a, dT, L, n, dh = 9e-5, 40.0, 100.0, 20.0, 0.2
        w = warp.wang_delta(a, dT, L, n, dh)
        k = 6 * a * dT * (n - 1) / (n ** 3 * dh)
        self.assertAlmostEqual(w["curvature_per_mm"], k, places=12)
        self.assertAlmostEqual(w["delta_mm"], (1 - math.cos(L * k / 2)) / k, places=10)
        h = n * dh                                                        # Armillotta's form for a small angle
        self.assertAlmostEqual(w["delta_mm"] / (0.75 * a * dT * L ** 2 * dh / h ** 2 * (1 - dh / h)), 1.0, delta=0.01)
        self.assertGreater(warp.wang_delta(a, dT, 200.0, n, dh)["delta_mm"], 3.9 * w["delta_mm"])      # grows with the square of the span
        self.assertLess(warp.wang_delta(a, dT, L, 2 * n, dh)["delta_mm"], w["delta_mm"])              # a taller stack is stiffer
        self.assertEqual(warp.wang_delta(a, 0.0, L, n, dh)["delta_mm"], 0.0)

    def test_the_footprint_of_a_block(self):
        fp = warp.footprint(prism([(0, 0), (80, 0), (80, 6), (0, 6)], 40), DOWN)
        self.assertAlmostEqual(fp["contact_mm2"], 3200.0, places=6)
        self.assertAlmostEqual(fp["span_mm"], math.hypot(80, 40), places=6)
        self.assertEqual(fp["rect_mm"], [80.0, 40.0])
        self.assertEqual((fp["sharp_corners"], fp["sharpest_deg"]), (4, 90.0))
        self.assertAlmostEqual(fp["mean_height_mm"], 6.0, places=6)
        round_ = warp.footprint(cylinder(10, 40, 180), [0, -1, 0])       # standing on its round end
        self.assertEqual(round_["sharp_corners"], 0)
        self.assertAlmostEqual(round_["span_mm"], 20.0, delta=0.01)
        self.assertEqual(warp.footprint(prism(TEE, 10), geom.unit([1, 0, -1]))["contact_mm2"], 0.0)

    def test_the_indicator_states_every_input_and_ranks_plates_above_blocks(self):
        alpha = {"value": 96e-6, "how_known": "specified"}
        tg, ch, ly = {"value": 62.0, "how_known": "specified"}, {"value": 25.0, "how_known": "assumed"}, {"value": 0.2, "how_known": "assumed"}
        plate = warp.indicator(warp.footprint(prism([(0, 0), (120, 0), (120, 2), (0, 2)], 20), DOWN), alpha, tg, ch, ly)
        block = warp.indicator(warp.footprint(prism([(0, 0), (20, 0), (20, 20), (0, 20)], 20), DOWN), alpha, tg, ch, ly)
        self.assertGreater(plate["index"], 20 * block["index"])
        self.assertEqual(plate["band"], "high")
        self.assertEqual(block["band"], "low")
        self.assertAlmostEqual(plate["shrinkage_strain"]["value"], 96e-6 * 37, places=12)
        self.assertEqual(plate["raised_by"][0]["by"], "sharp corners at the ends of the footprint")
        self.assertIn("not a predicted lift", plate["not"].lower())
        self.assertIn("Wang", plate["model"]["source"])
        self.assertIn("end_lift_mm", plate["model_terms"])
        self.assertIn("Not a prediction", plate["model_terms"]["note"])
        for k in ("alpha_per_K", "glass_transition_C", "chamber_C", "layer_height_mm", "span_mm", "layers", "first_layer_mm2"):
            self.assertIn("how_known", plate["inputs"][k])
        hot = warp.indicator(warp.footprint(prism([(0, 0), (120, 0), (120, 2), (0, 2)], 20), DOWN), alpha, tg, {"value": 70.0, "how_known": "given"}, ly)
        self.assertEqual((hot["index"], hot["band"]), (0.0, "low"))
        edge = warp.indicator(warp.footprint(prism(TEE, 10), geom.unit([1, 0, -1])), alpha, tg, ch, ly)
        self.assertIsNone(edge["index"])

    def test_material_values_are_sourced_or_asked_for(self):
        a, tg, key = warp.material_inputs("PLA")
        self.assertEqual((a["value"], tg["value"], key), (96e-6, 62.0, "PLA"))
        self.assertIn("ma17184668", a["url"])
        self.assertIn("not this filament's own datasheet", a["how_known"])
        a, tg, _ = warp.material_inputs("ASA")                            # no Tg in any source read: Vicat stands in, said so
        self.assertIn("assumed", tg["how_known"])
        self.assertIn("Vicat", tg["how_known"])
        with self.assertRaises(StudioError) as cm:
            warp.material_inputs("TPU")
        self.assertIn("Nothing is assumed", str(cm.exception))
        a, tg, _ = warp.material_inputs("TPU", alpha_per_K=1e-4, tg_C=-24, source="a datasheet")
        self.assertIn("specified", a["how_known"])
        self.assertIn("assumed", warp.material_inputs("TPU", alpha_per_K=1e-4, tg_C=-24)[0]["how_known"])

    def test_every_sourced_value_names_its_document_and_the_line_it_was_read_from(self):
        rows = sources.table()
        self.assertGreaterEqual(len(rows), 14)
        for r in rows:
            for k in ("value", "source", "url", "quote", "condition", "basis", "retrieved"):
                self.assertTrue(r.get(k) not in (None, ""), f"{r['material']} {r['name']} lacks {k}")
            self.assertIn("unit", r)
            self.assertTrue(r["url"].startswith("https://"))
            self.assertIn(r["basis"], ("printed specimen", "resin datasheet"))
        self.assertIsNone(sources.get("PLA", "viscosity"))
        self.assertIsNone(sources.get("TPU", "cte"))
        self.assertEqual(sources.get("nylon", "tg")["value"], 52.0)


# ---- through the kernel ------------------------------------------------------------------------------------------

TEE_DESIGN = '''
from build123d import Align, Box, Pos
from form.recipes.base import Feature, Param, Recipe, Stage

M = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Tee"
    summary = "A stem with a cap that overhangs on two sides, and a shelf under one of them."
    params = [Param("h", "Stem height", 30, 10, 60, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        s = Pos(20, 0, 0) * Box(20, 20, v["h"], align=M) + Pos(0, 0, v["h"]) * Box(60, 20, 8, align=M)
        s += Pos(40, 0, 10) * Box(12, 20, 4, align=M)
        return [Stage("body", s)]
'''
TEE_SUPPORT = 2 * 20 * 20 * 30 - 12 * 20 * 14 + 12 * 20 * 10          # two overhangs, less what the shelf catches, plus the shelf's own


def printing(cfg):
    cfg = copy.deepcopy(cfg)
    cfg.setdefault("general", {})["capabilities"] = ["core", "parts", "mesh", "print"]
    cfg["general"]["new_designs"] = "print"
    return cfg


class WithStudio(unittest.TestCase):
    slicer = False

    @classmethod
    def config(cls):
        cfg = printing(config.load())
        if not cls.slicer:
            cfg["slicer"]["enabled"] = False
            cfg["slicer"]["app"] = str(Path(TMP) / "no-slicer")
            cfg["slicer"]["kind"] = "bambu"
        return cfg

    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(cls.config())
        cls.p = cls.st.create_design(f"Tee {cls.__name__}", TEE_DESIGN, purpose="print")
        cls.st.settings(cls.p, {"material": "PLA"})

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def load(self):
        return self.st.load(self.p["id"])


class OnADesign(WithStudio):
    def test_1_the_front_of_the_tee(self):
        r = tools.orient_call(self.st, self.p["id"], cosmetic=[[30, 10, 38]])
        self.assertFalse(r["calibration"]["factors"])
        self.assertEqual(r["calibration"]["how_known"], "uncalibrated")
        self.assertEqual(r["search"]["grid_directions"], 162)
        self.assertGreaterEqual(r["candidates_evaluated"], 162)
        ids = [f["id"] for f in r["front"]]
        self.assertNotIn("as_modelled", ids)
        self.assertFalse(r["current_on_front"])
        # worked by hand above; the cap's facets straddle the shelf's edge, so the integral is within its stated spread
        self.assertAlmostEqual(r["current"]["support_mm3"], TEE_SUPPORT, delta=0.002 * TEE_SUPPORT)
        self.assertEqual(r["current"]["integrated"], "fine")
        self.assertLess(r["current"]["support_mm3_spread"], 0.005 * TEE_SUPPORT)
        best = r["front"][0]
        self.assertEqual(best["rank"], 1)
        self.assertGreater(best["tip_over_deg"], 0)
        self.assertEqual(r["recommended"], best["id"])
        self.assertEqual(set(r["objectives"]), {"support_mm3", "support_contact_mm2", "time_s", "tip_over_deg", "cosmetic_cusp_um",
                                                "cosmetic_supported_mm2"})
        self.assertIn("modelled", r["objectives"]["time_s"]["how_known"])
        self.assertIn("computed", r["objectives"]["support_mm3"]["how_known"])
        self.assertEqual(r["cosmetic"][0]["feature"], "body")
        self.assertAlmostEqual(r["cosmetic"][0]["area_mm2"], 60 * 20, places=3)             # the top of the cap
        self.assertIsNone(r["strength_input"]["from"])
        self.assertIn("not among the objectives", r["strength_input"]["note"])
        self.assertFalse(r["verification"]["ran"])
        self.assertEqual(self.load()["orientation"], "as_modelled")                         # a search sets nothing

    def test_2_the_pick_is_written_to_the_print_setup(self):
        r = tools.orient_call(self.st, self.p["id"])                                        # repeats the last search
        self.assertEqual(r["cosmetic"][0]["at"], [30.0, 10.0, 38.0])
        pick = r["front"][0]["id"]
        out = tools.orient_call(self.st, self.p["id"], pick=pick)["picked"]
        self.assertEqual((out["orientation"], out["was"], out["changed"]), (pick, "as_modelled", True))
        p = self.load()
        self.assertEqual(p["orientation"], pick)
        self.assertEqual(p["print"]["orient"]["picked"]["orientation"], pick)
        again = tools.orient_call(self.st, self.p["id"])
        self.assertTrue(again["current_on_front"])
        with self.assertRaises(StudioError):
            tools.orient_call(self.st, self.p["id"], pick="sideways")

    def test_3_a_load_direction_makes_strength_an_objective(self):
        r = tools.orient_call(self.st, self.p["id"], load_direction=[0, 0, 1])
        self.assertIn("strength_use", r["objectives"])
        self.assertEqual(r["strength_input"]["from"], "load direction")
        self.assertEqual(r["strength_input"]["knockdown"]["ratio"], round(31 / 35, 3))
        standing = next(f for f in [r["current"]] + r["front"] if f and abs(abs(f["down"][2]) - 1) < 1e-6) if abs(r["current"]["down"][2]) == 1 else None
        lying = next(f for f in r["front"] if abs(f["down"][2]) < 1e-6)
        self.assertAlmostEqual(lying["strength"]["strength_along_load"], 1.0)
        if standing:
            self.assertAlmostEqual(standing["strength"]["strength_along_load"], round(31 / 35, 3), places=3)

    def test_4_warp_risk_names_its_inputs_and_compares_orientations(self):
        r = tools.warp_call(self.st, self.p["id"], orientation="as_modelled")
        self.assertEqual(r["material"], "PLA")
        self.assertIn(r["band"], ("low", "moderate", "high"))
        self.assertEqual(r["inputs"]["chamber_C"]["value"], 25.0)
        self.assertIn("assumed", r["inputs"]["chamber_C"]["how_known"])
        self.assertAlmostEqual(r["inputs"]["span_mm"]["value"], math.hypot(20, 20), places=2)
        self.assertEqual(len(r["by_orientation"]), 6)
        idx = [x["index"] for x in r["by_orientation"] if x["index"] is not None]
        self.assertEqual(idx, sorted(idx))
        flat = tools.warp_call(self.st, self.p["id"], orientation="inverted")              # the 60 x 20 cap on the plate
        self.assertGreater(flat["index"], r["index"])
        warm = tools.warp_call(self.st, self.p["id"], orientation="inverted", chamber_C=45)
        self.assertLess(warm["index"], flat["index"])
        self.assertEqual(warm["inputs"]["chamber_C"]["how_known"], "given")
        with self.assertRaises(StudioError) as cm:
            tools.warp_call(self.st, self.p["id"], material="TPU")
        self.assertIn("Nothing is assumed", str(cm.exception))

    def test_5_the_bench_lists_check_and_make_entries(self):
        rows = {e["id"]: e for e in studies.listing(self.st, self.load())["entries"]}
        for sid, group in (("print.orient", "study"), ("print.strength", "study"), ("print.warp", "study"), ("print.orientation", "route")):
            self.assertIn(sid, rows)
            self.assertEqual(rows[sid]["group"], group)
        self.assertEqual(rows["print.orient"]["state"], "current")                           # found in the cache, not recomputed
        self.assertIn("on the front", rows["print.orient"]["headline"])
        self.assertIn(rows["print.strength"]["state"], ("never", "unavailable"))
        self.assertIn("picked", rows["print.orientation"]["headline"])
        self.assertEqual(rows["print.orientation"]["state"], "current")                       # read when listed
        self.assertEqual(rows["print.orientation"]["evidence"], "a person's pick")
        done = studies.start(self.st, self.p["id"], "print.warp", wait=True)["entry"]
        self.assertEqual(done["state"], "current")
        self.assertIn("indicator", done["headline"])
        self.st.commit(self.load(), {"h": 34}, note="taller")
        after = {e["id"]: e for e in studies.listing(self.st, self.load())["entries"]}
        self.assertIn(after["print.warp"]["state"], ("stale", "never"))                      # a new revision: stale by construction
        self.assertNotEqual(after["print.orient"]["state"], "current")

    def test_6_the_command_line_prints_json(self):
        self.assertEqual(print_cli.main([]), 2)
        self.assertEqual(print_cli.main(["--help"]), 0)

    def test_7_a_model_or_printing_off_is_refused(self):
        off = Studio({**self.st.cfg, "general": {**self.st.cfg["general"], "capabilities": ["core"]}})
        try:
            with self.assertRaises(StudioError) as cm:
                tools.orient_call(off, self.p["id"])
            self.assertIn("printing is off", str(cm.exception))
        finally:
            off.kernel.shutdown()


@NEEDS_ENGINE
class LayeredStudy(WithStudio):
    """Needs the engine: the tee held at its foot and loaded on the cap, as printed."""
    BODY = {"fixtures": [{"type": "fixed", "faces": [[30, 10, 0]]}],
            "loads": [{"type": "force", "faces": [[5, 10, 38]], "vector": [0, 0, -20]}],
            "material": "PLA", "mesh": {"budget_s": 60}}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        r = tools.strength_call(cls.st, cls.p["id"], "", cls.BODY, "setup", ["on_back", "on_left"], None, "", False, False, "test")
        cls.note = r.get("material_note")
        cls.sid = r["study"]["id"]
        cls.res = study.run(cls.st, cls.p["id"], cls.sid)["result"]

    def test_1_the_weak_direction_has_its_own_factor_and_error(self):
        res = self.res
        self.assertTrue(res["converged"], res.get("not_converged_because"))
        lay = res["layers"]
        self.assertEqual(lay["orientation"], "as_modelled")
        self.assertTrue(lay["follows_print_setup"])
        self.assertTrue(np.allclose(lay["axis"], [0, 0, 1]))
        a = lay["across_layers"]
        self.assertEqual(a["strength_MPa"], 31.0)
        self.assertAlmostEqual(a["safety_factor"]["value"], 31.0 / a["peak_tension_MPa"], places=6)
        self.assertLessEqual(a["safety_factor"]["low"], a["safety_factor"]["value"])
        self.assertIsNotNone(a["error"])
        self.assertAlmostEqual(lay["in_plane"]["safety_factor"]["value"], 35.0 / res["peak_von_mises_MPa"], places=6)
        self.assertEqual(res["safety_factor"]["value"], min(a["safety_factor"]["value"], lay["in_plane"]["safety_factor"]["value"]))
        self.assertIn(lay["governing"], ("across_layers", "in_plane"))
        self.assertIn("transversely isotropic", res["model"])
        self.assertIn("printed Base down", res["headline"])

    def test_2_every_material_value_says_how_it_is_known(self):
        m = self.res["layers"]["material"]
        self.assertEqual(sorted(m["assumed"]), ["G_zp", "nu_zp"])
        self.assertIn("assumed: nu_zp, G_zp", self.res["layers"]["evidence"])
        self.assertEqual(m["how_known"]["E_z"]["evidence"], "specified (datasheet)")
        self.assertIn("Ferreira", m["how_known"]["nu_p"]["source"])               # Poisson's ratio: printed specimens, named
        self.assertIn("another document", self.note)
        self.assertEqual(m["knockdown"]["strength"], round(31 / 35, 3))

    def test_3_it_changes_with_the_orientation(self):
        rows = {r["id"]: r for r in self.res["layers"]["by_orientation"]}
        self.assertEqual(set(rows), {"as_modelled", "on_back", "on_left"})
        self.assertTrue(rows["as_modelled"]["chosen"])
        # the cap bends about y: its bending stress runs along x. Stacked along x (on its left side) the layers are
        # pulled apart by it; stacked along y (on its back) they are not.
        self.assertGreater(rows["on_left"]["peak_tension_across_MPa"], 3 * rows["on_back"]["peak_tension_across_MPa"])
        self.assertLess(rows["on_left"]["sf_across_layers"], rows["on_back"]["sf_across_layers"])
        self.assertNotAlmostEqual(rows["on_left"]["max_displacement_mm"], rows["on_back"]["max_displacement_mm"], places=4)

    def test_4_the_setup_makes_it_stale_and_the_field_feeds_the_orientation_search(self):
        p = self.load()
        self.assertEqual(study.state(self.st, p, self.sid)["state"], "current")
        r = tools.orient_call(self.st, self.p["id"], study=self.sid)
        self.assertEqual(r["strength_input"]["from"], "strength study")
        self.assertEqual((r["strength_input"]["S_z_MPa"], r["strength_input"]["S_xy_MPa"]), (31.0, 35.0))
        self.assertIn("strength_use", r["objectives"])
        self.assertTrue(all(f["strength"]["safety_factor"] > 0 for f in r["front"]))
        self.st.settings(p, {"orientation": "on_left"})
        self.assertEqual(study.state(self.st, self.load(), self.sid)["state"], "stale")
        self.st.settings(self.load(), {"orientation": "as_modelled"})
        self.assertEqual(study.state(self.st, self.load(), self.sid)["state"], "current")
        rows = {e["id"]: e for e in studies.listing(self.st, self.load())["entries"]}
        self.assertEqual(rows["print.strength"]["state"], "current")
        self.assertIn("safety factor", rows["print.strength"]["headline"])

    def test_5_the_field_carries_the_stress_and_the_tension_across_the_layers(self):
        f = study.field(self.st, self.load(), self.sid)["fields"]
        self.assertEqual(f["stress"]["components"], 6)
        self.assertIn("across_layers", f)
        self.assertIn("interlayer_shear", f)


def _slicer_cfg():
    """A configuration whose slicer resolves here, or None."""
    from form import slicer as slicer_mod
    cfg = printing(config.load())
    try:
        s = Studio(cfg).slicer_info()
    except Exception:                                    # noqa: BLE001
        return None
    if s.get("available"):
        return cfg
    machine = ((s.get("presets") or {}).get("machine") or {}).get("name") or ""
    tail = {"Bambu Lab A1 mini": "@BBL A1M", "Bambu Lab A1": "@BBL A1", "Bambu Lab P1S": "@BBL X1C", "Bambu Lab X1 Carbon": "@BBL X1C"}
    for name, suffix in tail.items():
        if machine.startswith(name) and slicer_mod.label(s.get("kind", "")):
            trial = copy.deepcopy(cfg)
            trial["slicer"]["filament"] = f"Bambu PLA Basic {suffix}"
            try:
                if Studio(trial).slicer_info().get("available"):
                    return trial
            except Exception:                            # noqa: BLE001
                pass
    return None


SLICER_CFG = _slicer_cfg() if os.environ.get("FORM_TEST_SLICER", "1") != "0" else None


@unittest.skipUnless(SLICER_CFG, "no slicer resolves here (none installed, or its selected presets are not found)")
class AgainstTheSlicer(WithStudio):
    """The model against the real slicer's own slices of the same orientations."""
    slicer = True

    @classmethod
    def config(cls):
        return SLICER_CFG

    def test_time_and_support_filament_are_compared_and_the_error_is_reported(self):
        r = tools.orient_call(self.st, self.p["id"], calibrate=True, verify=2)
        cal = r["calibration"]
        self.assertEqual(cal["how_known"], "calibrated on one real slice")
        self.assertEqual(cal["on"], "as_modelled")
        self.assertGreater(cal["factors"]["time"], 0.2)
        self.assertLess(cal["factors"]["time"], 5.0)
        self.assertIn("x", cal["note"])
        v = r["verification"]
        self.assertTrue(v["ran"])
        self.assertEqual(v["set_for_these_slices"].get("enable_support") or v["set_for_these_slices"].get("support_material"), "1")
        rows = {c["id"]: c for c in v["candidates"]}
        self.assertIn("as_modelled", rows)                                 # the setup's orientation is always compared
        self.assertTrue(rows["as_modelled"]["calibration_slice"])
        self.assertGreaterEqual(len(rows), 3)
        std = rows["as_modelled"]["support_g"]
        self.assertGreater(std["slicer"], 1.0)                             # the standing tee really is supported
        self.assertLess(abs(std["error"]), 0.5)                            # the model's support grams within 50 % of the slicer's
        for c in v["candidates"]:
            if c["calibration_slice"]:
                continue
            self.assertLess(c["support_g"]["slicer"], 0.2 * std["slicer"])  # the front's orientations need far less
            self.assertLess(abs(c["time_s"]["error"]), 0.5)
            self.assertLess(c["time_s"]["slicer"], rows["as_modelled"]["time_s"]["slicer"])
        self.assertEqual(v["time_error"]["over"], len(rows) - 1)
        self.assertLess(v["time_error"]["max_abs"], 0.5)
        self.assertIsNotNone(v["support_error"]["mean_abs_g"])
        self.assertIn("simulation, not a print", v["note"])
        print(f"\n  slicer comparison ({v['slicer']} {v['slicer_version']}): time error mean {100 * v['time_error']['mean_abs']:.1f} % "
              f"max {100 * v['time_error']['max_abs']:.1f} % over {v['time_error']['over']}; support {std['predicted']:.2f} g "
              f"predicted vs {std['slicer']:.2f} g sliced ({100 * std['error']:+.1f} %)", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
