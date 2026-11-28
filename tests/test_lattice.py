"""Lattices and TPMS (wave AE) against analytic and published values.

Cells (numpy only): a network TPMS at level 0 fills exactly half of space (each function changes sign under a rigid
motion); the area of the level-0 surface against the published area of the minimal surface (Schwarz P 2.3451, gyroid
3.0915, Schwarz D 3.8378 per unit cell: Schoen 1970, as tabulated by Jung and Torquato 2005) within 1 %; a thin
sheet's density against area x wall; strut length per cell against the closed forms (4 sqrt 3, 6 sqrt 2, 12 sqrt 2,
6 sqrt 2); the first-order strut density against pi r² L / a³ and the octet truss against 6 sqrt 2 pi (r / l)²
(Deshpande, Fleck and Ashby 2001); the marching-tetrahedra mesh of a sphere against 4/3 pi r³.

Properties: Gibson-Ashby's E* / Es = C rho^n against the formula for each class; the class of each strut cell against
the exponent of the periodic frame model; the octet truss's E = rho Es / 9 by that model within 1 %.

Geometry (the kernel): struts as an exact B-rep, valid, one solid, its density against the cell's; a TPMS as a faceted
solid whose density is the cell's within 1 %; the skin's closed voids counted; a graded lattice denser where asked.
Through the Studio: lattice_fill writes a revision, the Bench entry is current, remove gives the body back.
Tests use their own FORM_DATA, never the owner's data."""
import importlib.util
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="form-lattice-")
os.environ["FORM_DATA"] = TMP

from form import lattice as LT  # noqa: E402
from form.lattice import cells as C, homog as H  # noqa: E402

HAS_SCIPY = importlib.util.find_spec("scipy") is not None
HAS_M3 = importlib.util.find_spec("manifold3d") is not None


class Cells(unittest.TestCase):
    def test_network_tpms_at_level_zero_is_half(self):
        for k in C.TPMS:
            self.assertAlmostEqual(C.tpms_density(k, "network", 0.0), 0.5, places=6, msg=k)

    def test_surface_area_against_published(self):
        for k, pub in C.PUBLISHED_AREA.items():
            got = C.tpms_area(k, 64)
            self.assertLess(abs(got / pub - 1.0), 0.01, f"{k}: {got:.4f} against {pub}")

    def test_thin_sheet_density_is_area_times_wall(self):
        for k, pub in C.PUBLISHED_AREA.items():
            level = C.tpms_level_for_wall(k, 0.03, 1.0)
            wall = C.tpms_wall(k, level, 1.0)["mean_mm"]
            self.assertAlmostEqual(wall, 0.03, places=6)
            rho = C.tpms_density(k, "sheet", level, 96)
            self.assertLess(abs(rho / (pub * wall) - 1.0), 0.04, f"{k}: {rho:.5f} against {pub * wall:.5f}")

    def test_level_is_the_inverse_of_density(self):
        for k in C.TPMS:
            for form, rho in (("sheet", 0.2), ("sheet", 0.45), ("network", 0.3)):
                c = C.tpms_level(k, form, rho)
                self.assertAlmostEqual(C.tpms_density(k, form, c), rho, delta=0.001, msg=f"{k} {form} {rho}")

    def test_strut_length_per_cell(self):
        want = {"bcc": 4 * math.sqrt(3), "fcc": 6 * math.sqrt(2), "octet": 12 * math.sqrt(2), "kelvin": 6 * math.sqrt(2)}
        for k, L in want.items():
            self.assertAlmostEqual(C.strut_length_per_cell(k), L, places=9, msg=k)
            self.assertAlmostEqual(C.STRUT_LENGTH[k], L, places=12)
        self.assertEqual({k: len(C.struts(k)) for k in C.STRUT}, {"bcc": 8, "fcc": 24, "octet": 36, "kelvin": 36})

    def test_strut_density_first_order_and_measured(self):
        r, a = 0.25, 10.0
        for k in C.STRUT:
            first = C.strut_density_first_order(k, r, a)
            self.assertAlmostEqual(first, math.pi * (r / a) ** 2 * C.STRUT_LENGTH[k], places=12)
            got = C.strut_density(k, r, a, 64)                     # capsules: struts with spheres of their own radius
            self.assertLess(got, first * 1.02, k)                  # the overlap at the nodes only takes material away
            self.assertGreater(got, first * 0.90, k)               # and for slender struts it is a few percent
        # the octet truss in its usual form: 6 sqrt 2 pi (r / l)², l the strut length a / sqrt 2
        l = a / math.sqrt(2)                                       # noqa: E741
        self.assertAlmostEqual(C.strut_density_first_order("octet", r, a), 6 * math.sqrt(2) * math.pi * (r / l) ** 2, places=12)
        # Kelvin: 3 pi / (8 sqrt 2) (d / L)², L the edge a / (2 sqrt 2)
        Lk = a / (2 * math.sqrt(2))
        self.assertAlmostEqual(C.strut_density_first_order("kelvin", r, a), 3 * math.pi / (8 * math.sqrt(2)) * (2 * r / Lk) ** 2, places=12)

    def test_marching_tetrahedra_on_a_sphere(self):
        n, R = 48, 0.8
        t = np.linspace(-1, 1, n + 1)
        X, Y, Z = np.meshgrid(t, t, t, indexing="ij")
        V, F = C.iso_mesh(np.sqrt(X * X + Y * Y + Z * Z) - R, (-1, -1, -1), 2.0 / n)
        self.assertAlmostEqual(C.mesh_volume(V, F), 4 / 3 * math.pi * R ** 3, delta=0.01 * 4 / 3 * math.pi * R ** 3)
        self.assertAlmostEqual(C.mesh_area(V, F), 4 * math.pi * R ** 2, delta=0.01 * 4 * math.pi * R ** 2)
        from form.recon import mesh as meshmod
        top = meshmod.topology(V, F)
        self.assertTrue(top["closed"])
        self.assertEqual(top["flipped_edges"], 0)

    def test_names(self):
        self.assertEqual(C.kind_of("Diamond"), "schwarz_d")
        self.assertEqual(C.kind_of("schwarz-p"), "schwarz_p")
        with self.assertRaises(ValueError):
            C.kind_of("honeycomb")


class Properties(unittest.TestCase):
    def test_gibson_ashby_against_the_formula(self):
        for rho in (0.05, 0.2, 0.5):
            b = LT.gibson_ashby(rho, "bending")
            self.assertAlmostEqual(b["E_rel"], rho ** 2, places=12)
            self.assertAlmostEqual(b["strength_rel"], 0.3 * rho ** 1.5, places=12)
            s = LT.gibson_ashby(rho, "stretch")
            self.assertAlmostEqual(s["E_rel"], rho / 3, places=12)
            self.assertAlmostEqual(s["strength_rel"], rho / 3, places=12)
            self.assertAlmostEqual(LT.gibson_ashby(rho, "octet")["E_rel"], rho / 9, places=12)

    def test_properties_use_the_law_and_say_so(self):
        spec = LT.normalise("gyroid", 8.0, density=0.2)
        r = LT.properties(spec, material="AL-6061", process="lpbf")
        rho = r["relative_density"]["value"]
        self.assertAlmostEqual(rho, 0.2, delta=0.004)
        self.assertEqual(r["stiffness"]["evidence"], "computed (scaling law)")
        self.assertEqual(r["stiffness"]["class"], "stretch")
        self.assertAlmostEqual(r["stiffness"]["E_rel"], rho / 3, places=9)
        self.assertAlmostEqual(r["stiffness"]["E_MPa"], rho / 3 * 68900.0, delta=1.0)        # the library's E, 68.9 GPa
        self.assertIn("MatWeb", r["stiffness"]["Es_source"])
        self.assertEqual(r["relative_density"]["evidence"], "computed (unit cell)")
        thin = r["relative_density"]["thin_wall_estimate"]["value"]
        self.assertLess(abs(thin / rho - 1), 0.05)
        bcc = LT.properties(LT.normalise("bcc", 8.0, strut_d=0.8))
        self.assertEqual(bcc["stiffness"]["class"], "bending")
        self.assertAlmostEqual(bcc["stiffness"]["E_rel"], bcc["relative_density"]["value"] ** 2, places=12)
        self.assertLess(bcc["relative_density"]["value"], bcc["relative_density"]["first_order"]["value"] * 1.05)

    def test_strut_classes_are_what_the_frame_model_gives(self):
        for k in C.STRUT:
            n = H.frame_exponent(k)
            law = LT.LAWS[LT.CLASS[k]]
            self.assertAlmostEqual(n, law["n"], delta=0.05, msg=f"{k}: exponent {n:.3f}")

    def test_octet_truss_is_rho_over_nine(self):
        r = 0.01
        rho = C.strut_density_first_order("octet", r, 1.0)
        self.assertLess(abs(H.frame("octet", r)["E_rel"] / (rho / 9) - 1.0), 0.01)
        v = LT.properties(LT.normalise("octet", 10.0, strut_d=0.2, node=1.05), verify=True)["verification"]
        self.assertTrue(v["available"])
        self.assertLess(abs(v["difference"]), 0.06, "slender octet, small nodes: the law and the frame model agree")

    def test_verification_reports_the_law_s_error(self):
        v = LT.properties(LT.normalise("bcc", 8.0, strut_d=1.0), verify=True)["verification"]
        self.assertTrue(v["available"])
        self.assertAlmostEqual(v["exponent"], 2.0, delta=0.05)
        # along a cell axis a BCC lattice is far more compliant than the generic C = 1: the difference is reported
        self.assertGreater(v["estimate_over_fe"], 3.0)
        self.assertAlmostEqual(v["difference"], v["estimate_over_fe"] - 1.0, places=9)

    @unittest.skipUnless(HAS_SCIPY, "the voxel model needs SciPy")
    def test_voxel_model_bounds_and_tpms_classes(self):
        solid = H.voxel({"kind": "gyroid", "form": "network", "level": C.F_MAX["gyroid"] + 1.0, "cell": 1.0}, 0.3, 8)
        self.assertAlmostEqual(solid["E_rel"], 1.0, delta=1e-4)                       # a full cell is the solid
        for form, rho in (("sheet", 0.25), ("network", 0.3)):
            spec = {"kind": "gyroid", "form": form, "level": C.tpms_level("gyroid", form, rho), "cell": 1.0}
            e = H.voxel(spec, 0.3, 20)["E_rel"]
            self.assertLess(e, rho)                                                   # under the rule of mixtures
            law = LT.gibson_ashby(rho, LT.CLASS[(form,)])["E_rel"]
            self.assertLess(abs(math.log(law / e)), math.log(1.6), f"{form}: law {law:.4f}, voxel FE {e:.4f}")

    def test_printability_reads_the_sourced_tables(self):
        from form.dfm import rules
        thin = LT.properties(LT.normalise("octet", 8.0, strut_d=0.4, skin=1.0), process="sls")["printability"]
        limit = next(r for r in rules.table("sls")["rules"] if r["measure"] == "wall_min_mm")["fail"]
        row = {r["id"]: r for r in thin["rows"]}
        self.assertEqual(row["lattice.thin"]["limit_mm"], limit)
        self.assertEqual(row["lattice.thin"]["status"], "PASS" if 0.4 >= limit else "FAIL")
        self.assertEqual(row["lattice.trapped"]["status"], "WARN")                    # a skin, nothing built yet
        built = LT.printability(LT.normalise("octet", 8.0, strut_d=1.0, skin=1.0), {"what": "strut", "min_mm": 1.0, "pore_mm": 5.0, "channels": 1},
                                "sls", built={"trapped_voids": 1})
        self.assertEqual({r["id"]: r["status"] for r in built["rows"]}["lattice.trapped"], "FAIL")
        self.assertEqual(built["verdict"], "FAIL")
        fdm = LT.properties(LT.normalise("gyroid", 8.0, wall=0.3), process="fdm", nozzle=0.4)["printability"]
        rows = {r["id"]: r for r in fdm["rows"]}
        self.assertEqual(rows["lattice.nozzle"]["status"], "FAIL")
        sheet = LT.properties(LT.normalise("gyroid", 8.0, density=0.2, skin=1.0), process="sla")["printability"]
        self.assertIn("lattice.channels", [r["id"] for r in sheet["rows"]])

    def test_specification_is_checked(self):
        for bad in (dict(kind="gyroid", cell=8), dict(kind="gyroid", cell=8, density=0.2, wall=0.5),
                    dict(kind="bcc", cell=8, wall=0.5), dict(kind="gyroid", cell=8, strut_d=1.0),
                    dict(kind="kelvin", cell=8, strut_d=2.6), dict(kind="octet", cell=8, density=0.2, output="nurbs"),
                    dict(kind="gyroid", cell=8, grading={"mode": "stress", "density": [0.1, 0.4]})):
            with self.assertRaises(LT.LatticeError, msg=str(bad)):
                LT.normalise(**bad)

    def test_stress_field_as_a_grid(self):
        rng = np.random.default_rng(2)
        P = rng.uniform([0, 0, 0], [40, 20, 10], (4000, 3))
        vm = 5.0 + 90.0 * P[:, 0] / 40.0                                  # stress rising along x
        g = LT.grid_from_points(P, vm, 8, study="s1")
        self.assertAlmostEqual(g["peak_MPa"], float(vm.max()))
        spec = LT.normalise("gyroid", 8.0, skin=1.0, grading={"mode": "stress", "density": [0.1, 0.4], **g})
        from form.lattice import geom
        lo, hi = np.zeros(3), np.array([40.0, 20.0, 10.0])
        d = geom.density_at(spec, np.array([[2.0, 10, 5], [20.0, 10, 5], [38.0, 10, 5]]), lo, hi)
        self.assertTrue(d[0] < d[1] < d[2])
        self.assertAlmostEqual(d[1], 0.1 + 0.3 * (5 + 45) / 95, delta=0.03)
        self.assertEqual(spec["grading"]["study"], "s1")

    def test_source_block_round_trip(self):
        src = "from form.recipes.base import Recipe\n\n\nclass Design(Recipe):\n    pass\n"
        spec = LT.normalise("octet", 8.0, strut_d=1.0, skin=1.2)
        joined = LT.join(src, spec)
        self.assertIn(LT.START, joined)
        base, got = LT.split(joined)
        self.assertEqual(got, spec)
        self.assertEqual(base, src)
        self.assertEqual(LT.join(joined, None), src)
        compile(joined, "design", "exec")


class Geometry(unittest.TestCase):
    """In this process, on build123d shapes (what the worker runs)."""

    def fill(self, shape, **kw):
        """As lattice_fill does it: the output planned on the body, and a B-rep that OCCT makes invalid taken as a
        mesh when the choice was Form Studio's."""
        from form.lattice import geom
        spec = LT.normalise(**kw)
        asked = spec["output"]
        spec["output"] = geom.plan(shape, spec)["output"]
        try:
            out = geom._fill(shape, spec)
        except LT.LatticeError as e:
            if not (asked == "auto" and spec["output"] == "brep" and "invalid solid" in str(e)):
                raise
            spec["output"] = "mesh"
            out = geom._fill(shape, spec)
        return out, geom.REPORTS[geom.spec_key(spec)], spec

    def test_the_view_is_the_built_lattice_inside_the_skin(self):
        """What the stage draws (geom.view): the same struts kept where the inner region is, as dense as the build."""
        from build123d import Box
        from form.lattice import geom
        if not geom._has_manifold():
            self.skipTest("manifold3d is not installed")
        _out, rep, spec = self.fill(Box(18, 18, 18), kind="bcc", cell=8, strut_d=1.2, skin=1.0)
        v = geom.view(Box(18, 18, 18), spec)
        lo, hi = v["region"]["lo"], v["region"]["hi"]
        self.assertTrue(all(abs(a + 8.0) < 1e-6 for a in lo) and all(abs(b - 8.0) < 1e-6 for b in hi), "the box less the 1 mm skin")
        P = v["positions"]
        self.assertTrue((P.min(axis=0) >= -8.0 - 1e-4).all() and (P.max(axis=0) <= 8.0 + 1e-4).all(), "nothing outside the region")
        drawn = v["volume_mm3"] / v["inner_volume_mm3"]
        self.assertAlmostEqual(drawn, rep["relative_density_measured"], delta=0.02)
        self.assertFalse(v["graded"])
        self.assertTrue(abs(float(v["density"][0]) - drawn) < 1e-6, "a uniform lattice carries the drawn density")

    def test_struts_as_exact_brep(self):
        from build123d import Box, GeomType
        out, rep, spec = self.fill(Box(18, 18, 18), kind="octet", cell=8, strut_d=1.0, skin=1.0)
        self.assertEqual(rep["output"], "brep")
        self.assertTrue(out.is_valid)
        self.assertEqual(len(out.solids()), 1)
        kinds = {f.geom_type for f in out.faces()}
        self.assertEqual(kinds, {GeomType.CYLINDER, GeomType.PLANE}, "real cylinders; the octet's twelve struts cover "
                         "each node's sphere, and the skin is the box's own planes")
        bcc, _r, _s = self.fill(Box(18, 18, 18), kind="bcc", cell=8, strut_d=1.0, skin=1.0)
        self.assertIn(GeomType.SPHERE, {f.geom_type for f in bcc.faces()}, "a BCC node's sphere shows between its struts")
        cell = LT.properties(spec)["relative_density"]["value"]
        self.assertAlmostEqual(rep["relative_density_measured"], cell, delta=0.03 * cell)
        self.assertEqual(rep["trapped_voids"], 1)                         # the skin seals the lattice's open space
        self.assertEqual(rep["deviation"]["max_mm"], 0.0)
        self.assertAlmostEqual(rep["volume_mm3"], out.volume, places=6)
        self.assertAlmostEqual(out.volume, 18 ** 3 - 16 ** 3 * (1 - rep["relative_density_measured"]), delta=1e-3)

    def test_struts_without_a_skin_are_open(self):
        from build123d import Box
        out, rep, _ = self.fill(Box(16, 16, 16), kind="bcc", cell=8, strut_d=1.2, skin=0)
        self.assertTrue(out.is_valid)
        self.assertEqual(rep["trapped_voids"], 0)
        self.assertAlmostEqual(rep["relative_density_measured"], out.volume / 16 ** 3, places=9)

    @unittest.skipUnless(HAS_M3, "manifold3d is not installed")
    def test_strut_mesh_route_agrees_with_the_brep(self):
        from build123d import Box
        b, rb, _ = self.fill(Box(18, 18, 18), kind="bcc", cell=8, strut_d=1.2, skin=1.0, output="brep")
        m, rm, _ = self.fill(Box(18, 18, 18), kind="bcc", cell=8, strut_d=1.2, skin=1.0, output="mesh")
        self.assertEqual(rm["output"], "mesh")
        self.assertIn("mesh body", rm["representation"])
        self.assertAlmostEqual(m.volume, b.volume, delta=0.01 * b.volume)      # facets of a 16-sided strut read low
        self.assertLess(m.volume, b.volume)
        self.assertEqual(rm["trapped_voids"], 1)
        self.assertEqual(len(m.solids()), 1)

    @unittest.skipUnless(HAS_M3, "manifold3d is not installed")
    def test_tpms_density_is_the_cells(self):
        from build123d import Box
        for kind, form in (("gyroid", "sheet"), ("schwarz_p", "sheet"), ("schwarz_d", "network"), ("neovius", "sheet")):
            out, rep, spec = self.fill(Box(18, 18, 18), kind=kind, cell=8, form=form, density=0.3, skin=1.0)
            self.assertAlmostEqual(rep["relative_density_measured"], 0.3, delta=0.004, msg=f"{kind} {form}")
            if form == "sheet" and kind != "neovius":              # two channel systems, sealed by the skin (a box can
                self.assertEqual(rep["trapped_voids"], 2, kind)    # cut a network's one system, or a Neovius's, in pieces)
            self.assertGreaterEqual(rep["trapped_voids"], 1)
            self.assertLess(rep["deviation"]["max_mm"], rep["grid_mm"], "facets within one grid step of the level set")
            self.assertEqual(len(out.solids()), 1)
            self.assertAlmostEqual(out.volume, 18 ** 3 - 16 ** 3 * (1 - rep["relative_density_measured"]), delta=0.5)
            self.assertIn(rep["output"], ("brep", "mesh"))
            self.assertIn("faceted B-rep" if rep["output"] == "brep" else "mesh body", rep["representation"])

    @unittest.skipUnless(HAS_M3, "manifold3d is not installed")
    def test_output_is_chosen_and_said(self):
        from build123d import Box
        from form.lattice import geom
        small = geom.plan(Box(10, 10, 10), LT.normalise("gyroid", 8.0, density=0.3, skin=1.0))
        self.assertEqual(small["output"], "brep")
        self.assertIn("faceted", small["why"])
        big = geom.plan(Box(60, 60, 60), LT.normalise("gyroid", 6.0, density=0.3, skin=1.0))
        self.assertEqual(big["output"], "mesh")
        self.assertIn("no exact B-rep", big["why"])
        many = geom.plan(Box(60, 60, 60), LT.normalise("octet", 6.0, strut_d=0.8, skin=1.0))
        self.assertEqual(many["output"], "mesh")
        self.assertGreater(many["struts"], geom.BREP_STRUTS)
        few = geom.plan(Box(18, 18, 18), LT.normalise("octet", 8.0, strut_d=0.8, skin=1.0))
        self.assertEqual(few["output"], "brep")

    @unittest.skipUnless(HAS_M3, "manifold3d is not installed")
    def test_graded_lattice_is_denser_where_asked(self):
        from build123d import Box, Pos
        g = {"mode": "distance", "from": {"plane": {"origin": [-12, 0, 0], "normal": [1, 0, 0]}}, "over": 24, "density": [0.45, 0.15]}
        out, rep, _ = self.fill(Box(24, 16, 16), kind="gyroid", cell=8, skin=0, grading=g, output="mesh")
        left = (out & Pos(-6, 0, 0) * Box(12, 16, 16)).volume
        right = (out & Pos(6, 0, 0) * Box(12, 16, 16)).volume
        self.assertGreater(left, 1.5 * right)
        self.assertTrue(0.15 < rep["relative_density_measured"] < 0.45)
        b, rb, _ = self.fill(Box(24, 16, 16), kind="bcc", cell=8, skin=0, grading={**g, "density": [0.25, 0.05]})
        self.assertGreater(rb["strut_d_mm"][1], 1.5 * rb["strut_d_mm"][0])

    def test_region_box_and_refusals(self):
        from build123d import Box
        from form.lattice import geom
        out, rep, _ = self.fill(Box(30, 16, 16), kind="bcc", cell=8, strut_d=1.2, skin=0, region={"min": [-1, -8, -8], "max": [15, 8, 8]})
        self.assertTrue(out.is_valid)
        self.assertAlmostEqual(rep["inner_volume_mm3"], 16 ** 3, places=3)
        self.assertGreater(out.volume, 14 * 16 * 16)                       # the half outside the region stays solid
        with self.assertRaises(LT.LatticeError):
            geom.plan(Box(10, 10, 10), LT.normalise("bcc", 8.0, strut_d=1.0, skin=6.0))
        with self.assertRaises(LT.LatticeError):
            geom.plan(Box(10, 10, 10), LT.normalise("bcc", 8.0, strut_d=1.0, region={"min": [50, 50, 50], "max": [60, 60, 60]}))


BLOCK = '''from build123d import Box
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Block"
    summary = "A block to fill."
    params = [Param("w", "Width", 18, 10, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 18, 18))]
'''


class InADesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_fill_read_bench_remove(self):
        from form import studies
        from form.lattice import bench, tools
        st = self.st
        p = st.create_design("Lattice block", BLOCK, purpose="model")
        self.assertEqual(bench.summary(st, st.load(p["id"]))["state"], "never")
        r = tools.fill(st, p["id"], "octet", 8.0, strut_d=1.0, skin=1.0, process="sls", material="AL-6061", verify=True,
                       expect_head=p["head"])
        self.assertEqual(r["head"], p["head"] + 1)
        self.assertEqual(r["plan"]["output"], "brep")
        self.assertEqual(r["built"]["output"], "brep")
        self.assertEqual(r["built"]["evidence"], "measured on the built solid")
        self.assertAlmostEqual(r["built"]["relative_density_measured"], r["relative_density"]["value"], delta=0.01)
        self.assertEqual(r["stiffness"]["evidence"], "computed (scaling law)")
        self.assertTrue(r["verification"]["available"])
        rows = {x["id"]: x for x in r["printability"]["rows"]}
        self.assertEqual(rows["lattice.trapped"]["status"], "FAIL")       # a closed skin, sintered: the powder stays in
        self.assertIn("escape holes", rows["lattice.trapped"]["detail"])
        q = st.load(p["id"])
        self.assertFalse(getattr(st.recipe(q), "mesh", False), "struts are a B-rep: STEP is written")
        self.assertEqual(bench.summary(st, q)["state"], "current")
        self.assertIn("lattice", [s.id for s in studies.registry()])
        again = tools.fill(st, p["id"])                                    # read back, nothing asked beyond the cell
        self.assertEqual(again["spec"]["kind"], "octet")
        self.assertEqual(again["state"], "current")
        self.assertEqual(again["built"]["trapped_voids"], 1)
        gone = tools.fill(st, p["id"], remove=True, expect_head=q["head"])
        self.assertEqual(gone["removed"]["kind"], "octet")
        q = st.load(p["id"])
        self.assertIsNone(LT.current(st, q))
        self.assertEqual(bench.summary(st, q)["state"], "never")

    @unittest.skipUnless(HAS_M3, "manifold3d is not installed")
    def test_a_tpms_too_large_for_a_brep_is_a_mesh_design(self):
        from form.lattice import tools
        st = self.st
        p = st.create_design("Lattice block mesh", BLOCK.replace("18, 10, 80", "34, 10, 80"), purpose="model")
        r = tools.fill(st, p["id"], "gyroid", 6.0, density=0.25, skin=1.0, process="sla")
        self.assertEqual(r["plan"]["output"], "mesh")
        self.assertIn("no exact B-rep", r["plan"]["why"])
        self.assertTrue(getattr(st.recipe(st.load(p["id"])), "mesh", False), "a mesh body: no STEP")
        self.assertAlmostEqual(r["built"]["relative_density_measured"], 0.25, delta=0.01)
        self.assertGreaterEqual(r["built"]["trapped_voids"], 2)            # the two channel systems, and any pocket the
        rows = {x["id"]: x for x in r["printability"]["rows"]}             # box cuts off from them at its faces
        self.assertEqual(rows["lattice.trapped"]["status"], "FAIL")
        self.assertEqual(rows["lattice.channels"]["status"], "INFO")

    def test_graded_by_a_strength_study_s_field(self):
        """The von Mises field in the form form/fea writes it (form.fea.field/1: base64 float32 positions and values).
        The solver is an optional engine, so the field here is made by hand: stress rising along x. What is tested is
        the reading of that format, the grid kept in the source, and a lattice built denser where the stress is."""
        import base64
        from unittest import mock
        from form.fea import study as fs
        from form.lattice import tools
        st = self.st
        p = st.create_design("Lattice block graded", BLOCK.replace("18, 10, 80", "34, 10, 80"), purpose="model")
        rng = np.random.default_rng(5)
        P = rng.uniform([-17, -9, -9], [17, 9, 9], (3000, 3)).astype("<f4")
        vm = (2.0 + 80.0 * (P[:, 0] + 17) / 34).astype("<f4")
        field = {"format": "form.fea.field/1", "evidence": "simulated (FEA, linear static, converged to 1.0 %)",
                 "positions": base64.b64encode(P.tobytes()).decode(), "fields": {
                     "von_mises": {"type": "f4", "components": 1, "data": base64.b64encode(vm.tobytes()).decode()}}}
        with mock.patch.object(fs, "field", return_value=field):
            r = tools.fill(st, p["id"], "bcc", 8.0, skin=1.0, study="s1", grading={"mode": "stress", "density": [0.06, 0.25]})
        g = r["spec"]["grading"]
        self.assertEqual(g["study"], "s1")
        self.assertAlmostEqual(g["peak_MPa"], float(vm.max()), places=3)
        self.assertLessEqual(len(g["grid"]["values"]), 512)
        self.assertLess(g["grid"]["values"][0], 0.3)                       # low stress at -x
        d_lo, d_hi = r["built"]["strut_d_mm"]
        self.assertGreater(d_hi, 1.4 * d_lo, "thicker struts where the stress is")
        self.assertIn("'study': 's1'", st.source_text(st.load(p["id"])), "the grid travels in the design's source")
        with self.assertRaises(Exception):                                 # a lattice is in: the study no longer describes the body
            with mock.patch.object(fs, "field", return_value=field):
                tools.fill(st, p["id"], "bcc", 8.0, skin=1.0, study="s1", grading={"mode": "stress", "density": [0.06, 0.25]})


if __name__ == "__main__":
    unittest.main()
