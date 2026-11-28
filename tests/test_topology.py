"""Topology optimisation written back as features (form/topo): SIMP against the published MBB beam, the reading of
a density field as pockets and ribs, the features it writes, limits that are kept, and, when the FEA engine's Python
is there, a whole run on a real design: optimised, rebuilt as CAD, studied again, kept as a revision.

SciPy and the solver libraries live in the FEA engine's Python ($FORM_FEA_PYTHON, an installed engine, or this
Python when it has them); what needs them runs there, or is skipped with the reason.
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-topology-")
os.environ["FORM_DATA"] = TMP                      # never the owner's data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import config, fea  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from form.topo import emit  # noqa: E402
from form.topo import study as topo  # noqa: E402
from form.topo import tools  # noqa: E402

ENGINE = fea.python(config.load())
NEEDS_ENGINE = unittest.skipUnless(ENGINE, "the FEA engine is not installed here (set FORM_FEA_PYTHON to its Python)")
HAS_SCIPY = importlib.util.find_spec("scipy") is not None
NEEDS_SCIPY = unittest.skipUnless(HAS_SCIPY, "SciPy is not in this Python (the engine's Python has it)")

PLATE = '''"""Cantilever plate: a flat arm held at one end, loaded at the other."""
from build123d import Align, Box
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param

M = (Align.MIN, Align.MIN, Align.MIN)


class Design(FeatureDesign):
    title = "Cantilever plate"
    summary = "A flat arm held at one end and loaded at the other."
    params = [Param("length", "Length", 80, 40, 160, 1, "mm", "interface", "plate"),
              Param("height", "Height", 30, 10, 60, 1, "mm", "form", "plate"),
              Param("t", "Thickness", 5, 2, 12, 0.5, "mm", "form", "plate")]

    @feature("Plate", role="structure")
    def plate(self, v, body):
        return Box(v["length"], v["height"], v["t"], align=M)
'''
PETG = {"name": "PETG (test values)", "E_GPa": 2.0, "poisson": 0.38, "yield_MPa": 45, "density_kg_m3": 1270,
        "source": "test fixture"}
STATIC = {"kind": "static", "material": PETG, "fixtures": [{"type": "fixed", "faces": [[0, 15, 2.5]]}],
          "loads": [{"type": "force", "faces": [[80, 15, 2.5]], "vector": [0, -60, 0]}], "mesh": {"budget_s": 45}}
# a coarse run, so the whole chain fits a test: large members, few pockets
RUN = {"volfrac": 0.55, "h": 2.5, "rmin": 4.0, "max_iter": 40}


def engine_json(module: str, *args, timeout=900) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    r = subprocess.run([str(ENGINE), "-m", module, *args], capture_output=True, text=True, env=env, timeout=timeout)
    return json.loads(r.stdout)


@NEEDS_ENGINE
class PublishedBenchmark(unittest.TestCase):
    """Sigmund's MBB beam: compliance against the values printed in Andreassen et al. (2011)."""

    @classmethod
    def setUpClass(cls):
        cls.r = engine_json("form.topo.verify", "--quick")

    def test_compliance_matches_the_published_values(self):
        by = {c["case"]: c for c in self.r["cases"]}
        for name, ref in (("MBB 60x20, rmin 2.4, sensitivity filter", 216.81), ("MBB 60x20, rmin 2.4, density filter", 233.71)):
            c = by[name]
            self.assertEqual(c["published"], ref)
            self.assertLess(abs(c["compliance"] - ref) / ref, 5e-4, c)                # within 0.05 %
            self.assertAlmostEqual(c["volume"], 0.5, delta=1e-3)
            self.assertTrue(c["ok"], c)

    def test_the_topology_is_the_published_one(self):
        c = next(c for c in self.r["cases"] if "sensitivity" in c["case"])
        for where, probe in c["topology"].items():
            self.assertTrue(probe["ok"], (where, probe))
        self.assertEqual(sum(1 for q in c["topology"].values() if q["expected"] == "void"), 2)

    def test_the_same_loop_on_tetrahedra_balances_and_improves(self):
        c = next(c for c in self.r["cases"] if "tetrahedra" in c["case"])
        self.assertLess(c["energy_balance_error"], 1e-6)          # compliance of the solid = the work of the loads
        self.assertAlmostEqual(c["volume"], 0.5, delta=2e-3)
        self.assertEqual(c["rises_after_iteration_5"], 0)
        self.assertGreater(c["stiffer_than_even_by"], 1.5)        # against the same material spread evenly
        self.assertTrue(self.r["passed"])


@NEEDS_SCIPY
class Limits(unittest.TestCase):
    def test_the_iteration_limit_and_a_cancel_stop_the_loop_and_say_so(self):
        from form.topo import simp
        g = simp.Grid2D(30, 10, "mbb")
        o = simp.optimise(g, 0.5, 1.5, max_iter=5)
        self.assertEqual((o["iterations"], o["converged"], o["stopped"]), (5, False, "the limit of 5 iterations"))
        seen = []
        o = simp.optimise(g, 0.5, 1.5, max_iter=50, on_iter=lambda rec, x: seen.append(rec["iteration"]),
                          cancelled=lambda: len(seen) >= 4)
        self.assertEqual((o["iterations"], o["stopped"], seen), (3, "cancelled", [0, 1, 2, 3]))      # 0: the even start
        o = simp.optimise(g, 0.5, 1.5, max_iter=500, budget_s=0.0)
        self.assertEqual(o["iterations"], 1)
        self.assertIn("time limit", o["stopped"])

    def test_passive_regions_stay_and_too_much_of_them_is_refused(self):
        import numpy as np
        from form.topo import simp
        g = simp.Grid2D(30, 10, "cantilever")
        solid = np.zeros(g.n, bool)
        solid[:20] = True
        void = np.zeros(g.n, bool)
        void[-20:-10] = True
        o = simp.optimise(g, 0.5, 1.5, max_iter=15, solid=solid, void=void, ft="sensitivity")
        self.assertTrue((o["x"][solid] == 1).all() and (o["x"][void] == 0).all())
        self.assertAlmostEqual(o["volume"], 0.5, delta=2e-3)
        with self.assertRaises(ValueError) as cm:
            simp.optimise(g, 0.05, 1.5, solid=solid)
        self.assertIn("must stay solid", str(cm.exception))


@NEEDS_SCIPY
class Reading(unittest.TestCase):
    """A density picture with a known layout: two pockets between three ribs."""

    def picture(self):
        import numpy as np
        img = np.ones((60, 160))
        img[10:50, 20:70] = 0.02
        img[10:50, 90:140] = 0.02
        inside = np.ones_like(img, bool)
        keep = np.zeros_like(img, bool)
        keep[:, :6] = True
        return img, inside, keep, {"px": 0.5, "u0": 0.0, "v0": 0.0}

    def test_outlines_have_the_right_area_and_direction(self):
        import numpy as np
        from form.topo import recon
        f = np.zeros((20, 30))
        f[5:12, 8:20] = 1
        f[7:9, 11:14] = 0                                         # an island inside
        loops = sorted(recon.contours(f, 0.5), key=lambda lp: -abs(recon.area(lp)))
        self.assertEqual(len(loops), 2)
        self.assertAlmostEqual(recon.area(loops[0]), 7 * 12, delta=1.0)       # outer: positive
        self.assertAlmostEqual(recon.area(loops[1]), -2 * 3, delta=1.0)       # the island's boundary: negative
        sq = recon.simplify(loops[0], 0.6)
        self.assertLessEqual(len(sq), 8)
        # no corner moves by more than the tolerance, so the area changes by less than tolerance x perimeter
        self.assertAlmostEqual(recon.area(sq), recon.area(loops[0]), delta=0.6 * 38)
        self.assertGreaterEqual(len(sq), 4)

    def test_pockets_and_ribs_are_read_with_their_sizes(self):
        from form.topo import recon
        img, inside, keep, grid = self.picture()
        lay = recon.pockets(img, inside, keep, grid, volfrac=0.58, min_pocket_mm=3.0, rim_px=4)
        self.assertEqual(len(lay["pockets"]), 2)
        for pk in lay["pockets"]:
            self.assertAlmostEqual(pk["area_mm2"], 20 * 25, delta=25)          # 40 x 50 pixels of 0.5 mm
        self.assertAlmostEqual(sorted(pk["centre"][0] for pk in lay["pockets"])[0], 22.5, delta=0.6)
        self.assertAlmostEqual(lay["solid_fraction_predicted"], 1 - 2 * 2000 / 9600, delta=0.02)
        r = lay["ribs"]
        self.assertGreaterEqual(r["count"], 3)
        self.assertAlmostEqual(r["width_min_mm"], 5.0, delta=1.1)              # the rim: 10 pixels
        self.assertTrue(any(abs(m["width_mm"] - 10.0) < 1.1 for m in r["members"]))   # the middle rib: 20 pixels

    def test_pockets_grow_to_the_volume_asked_for_but_never_join(self):
        from form.topo import recon
        img, inside, keep, grid = self.picture()
        a = recon.pockets(img, inside, keep, grid, volfrac=0.58, min_pocket_mm=3.0, rim_px=4)
        b = recon.pockets(img, inside, keep, grid, volfrac=0.40, min_pocket_mm=3.0, rim_px=4)
        self.assertEqual(a["grown_mm"], 0.0)
        self.assertGreater(b["grown_mm"], 0.0)
        self.assertEqual(len(b["pockets"]), 2)
        self.assertLess(b["solid_fraction_predicted"], a["solid_fraction_predicted"])
        self.assertGreaterEqual(b["ribs"]["width_min_mm"], 1.5)
        c = recon.pockets(img, inside, keep, grid, volfrac=0.05, min_pocket_mm=3.0, rim_px=4)
        self.assertEqual(len(c["pockets"]), 2)                                 # asked for less than can be had: said
        self.assertGreater(c["solid_fraction_predicted"], c["volume_fraction_asked"])

    def test_nothing_to_cut_gives_no_pocket(self):
        import numpy as np
        from form.topo import recon
        img, inside, keep, grid = self.picture()
        lay = recon.pockets(np.ones_like(img), inside, keep, grid, volfrac=0.99, min_pocket_mm=3.0)
        self.assertEqual(lay["pockets"], [])

    def test_the_mesh_body_is_closed_and_has_the_volume_of_the_dense_half(self):
        import numpy as np
        from form.topo import recon
        from form.topo.run import mesh_volume
        # a unit cube of six tetrahedra, dense where x < 0.5
        P = np.array([[x, y, z] for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)])
        T = np.array([[0, 1, 3, 7], [0, 1, 5, 7], [0, 2, 3, 7], [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 6, 7]])
        faces = {}
        for t in T:
            for tri in ([t[0], t[1], t[2]], [t[0], t[1], t[3]], [t[0], t[2], t[3]], [t[1], t[2], t[3]]):
                faces.setdefault(tuple(sorted(tri)), []).append((tri, t))
        S = []
        for _key, owners in faces.items():
            if len(owners) == 1:
                tri, t = owners[0]
                a, b, c = P[tri]
                out = np.dot(np.cross(b - a, c - a), (a + b + c) / 3 - P[t].mean(axis=0)) > 0
                S.append(tri if out else [tri[0], tri[2], tri[1]])
        V, F = recon.iso_mesh(P, T, np.array(S), 1.0 - P[:, 0], 0.5, smooth=0)
        self.assertAlmostEqual(mesh_volume(V, F), 0.5, places=6)
        edges = {}
        for f in F:
            for k in range(3):
                e = (int(f[k]), int(f[(k + 1) % 3]))
                edges[e] = edges.get(e, 0) + 1
        self.assertTrue(all(edges.get((b, a), 0) == n for (a, b), n in edges.items()))    # every edge has its twin


class Writing(unittest.TestCase):
    LAYOUT = {"pockets": [{"outline": [[10, 5], [30, 5], [30, 20], [10, 20]], "area_mm2": 300.0, "corners": 4, "centre": [20, 12.5]},
                          {"outline": [[40, 5], [60, 5], [50, 22]], "area_mm2": 170.0, "corners": 3, "centre": [50, 10.7]}],
              "ribs": {"count": 3, "width_min_mm": 4.0, "members": [{"width_mm": 10.0}]}}
    GRID = {"e1": [1.0, 0.0, 0.0], "e2": [0.0, 1.0, 0.0], "pull": [0.0, 0.0, 1.0], "origin": [0.0, 0.0, 0.0], "w0": 0.0, "w1": 5.0}

    def test_a_layout_becomes_parameters_and_one_feature_per_pocket(self):
        ops, summary = emit.ops_for(self.LAYOUT, self.GRID, 1.2, 3.0)
        self.assertEqual([o["param"]["key"] for o in ops if "param" in o], ["topo_inset", "topo_fillet", "topo_web"])
        feats = [o for o in ops if "feature" in o]
        self.assertEqual([o["feature"] for o in feats], ["topo_pocket_1", "topo_pocket_2"])
        self.assertEqual(feats[0]["label"], "Lightening pocket 1")
        for o in feats:
            fn = ast.parse(o["code"]).body[0]
            self.assertEqual(fn.name, o["feature"])
            self.assertIn("cad.pocket(body, frame, outline, v[\"topo_inset\"], v[\"topo_fillet\"], v[\"topo_web\"])", o["code"])
        self.assertIn("(10.000, 5.000)", feats[0]["code"])
        self.assertIn("2 lightening pockets (470 mm² in all)", summary)
        web = next(o["param"] for o in ops if o.get("param", {}).get("key") == "topo_web")
        self.assertEqual((web["default"], web["max"]), (0.0, 5.0))
        self.assertEqual(next(o["param"]["default"] for o in ops if o.get("param", {}).get("key") == "topo_fillet"), 1.2)
        self.assertTrue(emit.already("class D:\n    def topo_pocket_1(self, v, body): ...\n"))
        self.assertFalse(emit.already(PLATE))

    def test_outline_geometry_is_what_it_says(self):
        import math
        from form.topo import cad
        sq = [(0, 0), (20, 0), (20, 10), (0, 10)]
        corners = cad.rounded_corners(sq, 2.0)
        for (p1, mid, p2), (cx, cy) in zip(corners, [(2, 2), (18, 2), (18, 8), (2, 8)]):
            for q in (p1, mid, p2):                                # every arc point is 2 mm from its centre
                self.assertAlmostEqual(math.hypot(q[0] - cx, q[1] - cy), 2.0, places=9)
        for got, want in ((corners[0][0], (0.0, 2.0)), (corners[0][2], (2.0, 0.0))):      # tangent to both sides
            self.assertAlmostEqual(math.hypot(got[0] - want[0], got[1] - want[1]), 0.0, places=9)
        tight = cad.rounded_corners([(0, 0), (2, 0), (2, 2), (0, 2)], 5.0)       # no room: a smaller arc, not a failure
        self.assertAlmostEqual(tight[0][2][0], cad.ARC_SHARE * 2)
        self.assertIsNone(cad.rounded_corners([(0, 0), (5, 0), (10, 0), (10, 5), (0, 5)], 1.0)[1][1])   # in line: no arc
        self.assertAlmostEqual(cad.outline_area(sq, 2.0), 200 - (4 - math.pi) * 4, places=9)      # four corners of r 2
        self.assertAlmostEqual(cad.outline_area(sq[::-1], 2.0), 200 - (4 - math.pi) * 4, places=9)
        ell = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]             # one corner points into the pocket
        self.assertAlmostEqual(cad.outline_area(ell, 2.0), 300 - 5 * (1 - math.pi / 4) * 4 + (1 - math.pi / 4) * 4, places=9)
        self.assertAlmostEqual(cad.outline_area(ell, 0.0), 300.0)

    def test_the_app_side_imports_without_the_solver_libraries_and_the_engine_side_is_packaged(self):
        code = ("import sys\n"
                "for m in ('scipy', 'netgen', 'skfem', 'pyamg'):\n"
                "    sys.modules[m] = None\n"
                "import form.topo.study, form.topo.tools, form.topo.emit, form.topo.cad\n"
                "import form.inverse.design, form.inverse.tools, form.inverse.bench, form.inverse.cli, form.inverse.verify\n"
                "print('ok')\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env={**os.environ, "PYTHONPATH": str(ROOT)})
        self.assertEqual(r.stdout.strip(), "ok", r.stderr[-600:])
        spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")
        self.assertIn('"engine_src/form/topo"', spec)
        for m in ("form.topo.simp", "form.topo.mesh3d", "form.topo.recon", "form.topo.run", "form.topo.verify"):
            self.assertIn(f'"{m}"', spec)
        from form import engines
        self.assertIn("form.topo.run", engines.SPECS["fea"]["check"])

    def test_settings_are_checked(self):
        o = topo.clean({"volfrac": 0.4, "pull": "y", "max_iter": 30})
        self.assertEqual((o["volfrac"], o["pull"], o["max_iter"], o["mode"], o["tries"]), (0.4, [0.0, 1.0, 0.0], 30, "pockets", 3))
        for body, word in (({"volfrac": 0.99}, "outside"), ({"speed": 1}, "Unknown topology setting"),
                           ({"mode": "lattice"}, "Unknown mode"), ({"pull": [0, 0, 0]}, "pull direction"),
                           ({"mass_g": -1}, "above 0"), ({"filter": "blur"}, "filter is")):
            with self.assertRaises(StudioError, msg=str(body)) as cm:
                topo.clean(body)
            self.assertIn(word, str(cm.exception))


class WithoutAStudyOrAnEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Bare plate", PLATE, "", purpose="model")["id"]

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def test_no_study_is_said_and_nothing_is_made_up(self):
        with self.assertRaises(StudioError) as cm:
            topo.run(self.st, self.pid, {"volfrac": 0.5})
        self.assertIn("no static strength study", str(cm.exception))
        self.assertIsNone(topo.get(self.st, self.st.load(self.pid)))
        with self.assertRaises(StudioError) as cm:
            topo.apply(self.st, self.pid)
        self.assertIn("no topology run", str(cm.exception))

    def test_the_bench_lists_both_entries_in_the_design_chapter(self):
        from form import studies
        from form.inverse import bench
        p = self.st.load(self.pid)
        for sid, label, tool in ((bench.INVERSE, "Inverse design", "inverse_design"),
                                 (bench.TOPOLOGY, "Topology optimisation", "topology_optimise")):
            e = studies.show(self.st, p, sid)
            self.assertEqual((e["label"], e["tool"], e["chapter"], e["group"]), (label, tool, "design", "study"))
            self.assertIn(e["state"], ("never", "unavailable"))
            self.assertTrue(e["why"])

    def test_the_tools_are_registered_and_say_what_they_claim(self):
        import asyncio
        from form import mcp_server
        by = {t.name: " ".join(t.description.split()) for t in asyncio.run(mcp_server.build().list_tools())}
        for name in ("topology_optimise", "get_topology", "apply_topology"):
            self.assertIn(name, by)
        for word in ("editable features", "topo_inset", "mesh body", "strength study is solved again"):
            self.assertIn(word, by["topology_optimise"])
        out = tools.run_call(self.st, self.pid, None)
        self.assertEqual(out["runs"], [])
        self.assertEqual(out["settings"]["volfrac"]["default"], 0.5)
        self.assertEqual(tools.read_call(self.st, self.pid)["state"], "never")
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        cli = subprocess.run([sys.executable, "-m", "form", "optimize", "topology", self.pid, "--show"], capture_output=True,
                             text=True, cwd=ROOT, env=env)
        self.assertEqual(cli.returncode, 0, cli.stderr[-400:])
        self.assertEqual(json.loads(cli.stdout)["state"], "never")

    def test_without_the_engine_the_run_is_refused(self):
        from unittest import mock
        from form.fea import study
        study.define(self.st, self.st.load(self.pid), STATIC)
        with mock.patch("form.topo.study.python", return_value=None):
            with self.assertRaises(StudioError) as cm:
                topo.run(self.st, self.pid, {"volfrac": 0.5})
        self.assertIn("No result was made up", str(cm.exception))
        self.assertEqual(cm.exception.extra.get("kind"), "unavailable")


@NEEDS_ENGINE
class WholeRun(unittest.TestCase):
    """Optimise, rebuild as features, study the rebuilt CAD, keep it."""

    @classmethod
    def setUpClass(cls):
        from form.fea import study
        cls.st = Studio(config.load())
        cls.pid = cls.st.create_design("Topology plate", PLATE, "", purpose="model")["id"]
        cls.sid = study.define(cls.st, cls.st.load(cls.pid), STATIC)["id"]
        cls.progress = []
        cls.rec = topo.run(cls.st, cls.pid, RUN, on_progress=cls.progress.append)

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.shutdown()

    def test_the_limits_are_kept_and_stated(self):
        rec = self.rec
        self.assertLessEqual(rec["iterations"], RUN["max_iter"])
        self.assertEqual(len(rec["history"]), rec["iterations"])
        self.assertLessEqual(rec["mesh"]["tets"], 60000)
        self.assertIn("elements of about 2.5 mm", rec["resolution"])
        self.assertEqual((rec["settings"]["rmin_mm"], rec["settings"]["rim_mm"]), (4.0, 2.5))
        b = rec["budget"]
        self.assertEqual(b["optimisation_solves"], rec["iterations"] + 2)             # the solid part and the thresholded field
        self.assertEqual((b["tries"], b["strength_studies"]), (1, 2))
        self.assertGreater(b["wall_seconds"], 0)
        self.assertTrue(any(ev.get("iteration") == 1 for ev in self.progress))

    def test_the_density_field_of_every_iteration_is_stored(self):
        import base64
        fr = json.loads(Path(self.rec["frames_file"]).read_text(encoding="utf-8"))
        g = fr["grid"]
        self.assertEqual(len(fr["frames"]), self.rec["iterations"] + 1)               # with the even start, iteration 0
        self.assertEqual([f["iteration"] for f in fr["frames"][:2]], [0, 1])
        self.assertIsNone(fr["frames"][0]["compliance"])
        self.assertLess(fr["frames"][-1]["compliance"], 0.8 * fr["frames"][1]["compliance"])
        self.assertEqual(len(base64.b64decode(fr["frames"][-1]["image"])), g["nu"] * g["nv"])
        self.assertEqual(len(fr["surface"]["frames"]), self.rec["iterations"] + 1)
        self.assertEqual(len(base64.b64decode(fr["surface"]["frames"][0])), fr["surface"]["vertices"])
        self.assertEqual(g["pull"], [0.0, 0.0, 1.0])                                  # the thinnest direction, chosen
        first, last = (list(base64.b64decode(fr["frames"][k]["image"])) for k in (0, -1))
        free = [k for k, v in enumerate(first) if v < 200]                            # not held solid from the start
        spread = lambda px: (lambda xs: (sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)) ** 0.5)([px[k] for k in free])  # noqa: E731
        self.assertGreater(len(free), 100)
        self.assertGreater(spread(last), 1.5 * spread(first))                         # from even grey to solid and void

    def test_the_layout_is_rebuilt_as_features_and_builds(self):
        rc = self.rec["reconstruction"]
        self.assertEqual(self.rec["outcome"], "features", rc.get("why"))
        self.assertGreaterEqual(len(rc["features"]), 2)
        self.assertEqual(set(rc["parameters"]), {"topo_inset", "topo_fillet", "topo_web"})
        self.assertEqual(rc["built"]["evidence"], "computed (B-rep)")
        self.assertNotIn("pockets_that_cut_nothing", rc["built"])
        self.assertAlmostEqual(rc["built"]["volume_fraction"], RUN["volfrac"], delta=0.08)
        self.assertGreaterEqual(self.rec["layout"]["ribs"]["count"], 3)
        # the volume the kernel reports for the cut is the outlines' own area (lines and arcs, computed here
        # without the kernel) through the thickness
        from form.topo import cad
        area = sum(cad.outline_area(pk["outline"], rc["parameters"]["topo_fillet"]) for pk in self.rec["layout"]["pockets"])
        cut = rc["built"]["volume_before_mm3"] - rc["built"]["volume_mm3"]
        self.assertAlmostEqual(cut, 5.0 * area, delta=0.002 * cut)

    def test_the_rebuilt_cad_is_studied_and_agrees_with_the_density_result(self):
        rec = self.rec
        ver = rec["reconstruction"]["verified"]
        self.assertTrue(ver["converged"], ver)
        self.assertIn("simulated (FEA, linear static, converged", ver["evidence"])
        self.assertGreaterEqual(ver["refinements"], 3)
        cmp = rec["comparison"]
        r = cmp["rebuilt_over_density"]
        lo, hi = topo.SF_BAND
        self.assertTrue(lo <= r["safety_factor"] <= hi, r)                            # the stated band
        self.assertTrue(cmp["safety_factor_band"]["inside"])
        self.assertAlmostEqual(r["mass"], 1.0, delta=0.12)
        self.assertAlmostEqual(r["compliance"], 1.0, delta=0.2)
        self.assertAlmostEqual(r["max_displacement"], 1.0, delta=0.2)
        s = cmp["rebuilt_over_solid_part"]
        self.assertLess(s["mass"], 0.65)                                              # lighter
        self.assertLess(s["safety_factor"], 1.0)                                      # and it costs strength: said
        self.assertGreater(s["max_displacement"], 1.0)
        self.assertIn("pockets", rec["headline"])
        self.assertIn("safety factor", rec["headline"])
        self.assertEqual(rec["evidence"], "simulated (FEA) on the rebuilt CAD")
        self.assertNotIn("fallback", rec)

    def test_the_mesh_body_is_always_written_and_labelled(self):
        b = self.rec["body"]
        self.assertTrue(Path(b["path"]).is_file())
        self.assertIn("mesh body (not editable CAD)", b["label"])
        self.assertAlmostEqual(b["volume_fraction"], RUN["volfrac"], delta=0.06)

    def test_z_keeping_it_adds_the_features_as_one_revision(self):
        st = self.st
        d = tools.read_call(st, self.pid)
        self.assertEqual(d["state"], "current")
        self.assertNotIn("ops", d["result"]["reconstruction"])
        head = st.load(self.pid)["head"]
        r = topo.apply(st, self.pid, self.rec["id"], expect_head=head)
        p = st.load(self.pid)
        self.assertEqual((r["kept"], p["head"]), ("features", head + 1))
        vals = st.rev(p)["values"]
        self.assertEqual((vals["topo_inset"], vals["topo_fillet"], vals["topo_web"]), (0.0, 1.6, 0.0))
        src = st.source_text(p)
        self.assertIn("def topo_pocket_1(self, v, body):", src)
        self.assertIn("Lightening pocket 1", src)
        built = self.rec["reconstruction"]["built"]["volume_mm3"]
        self.assertAlmostEqual(st.head_summary(p)["volume_mm3"], built, delta=built * 1e-3)
        # the parameters are real: a web under the pockets gives material back, a wide inset closes them
        from form import modelling
        pv = modelling.preview(st, p, [{"op": "set_param", "param": "topo_web", "value": 2.0}])
        self.assertGreater(pv["volume_mm3"]["after"], built * 1.1)
        pv = modelling.preview(st, p, [{"op": "set_param", "param": "topo_fillet", "value": 0.0}])
        self.assertTrue(pv["ok"])
        self.assertLess(pv["volume_mm3"]["after"], built)                             # sharp corners cut a little more
        self.assertAlmostEqual(pv["volume_mm3"]["after"], built, delta=built * 0.05)
        pv = modelling.preview(st, p, [{"op": "set_param", "param": "topo_inset", "value": 1.0}])
        self.assertGreater(pv["volume_mm3"]["after"], built * 1.05)                   # every rib 2 mm wider
        # the run described the revision before: it is stale now, and cannot be applied twice
        self.assertTrue(topo.get(st, p)["stale"])
        with self.assertRaises(StudioError) as cm:
            topo.apply(st, self.pid, self.rec["id"])
        self.assertIn("changed since this run", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
