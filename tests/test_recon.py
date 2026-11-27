"""Mesh to editable CAD (form/recon): readers, repairs that are reported, and the three layers on known parts.

The fixtures are real build123d parts exported as STL (tests/recon_fixtures.py): a box with holes, a turned part, a
filleted bracket and a spur gear with spline flanks. The pipeline runs in this process for the layer checks and once
through the Studio (kernel worker) for the project, CLI and "Make editable" routes. The layer checks here run the
pipeline without its program route (sketches and extrusions read off the mesh, tested in test_recon_program.py), so
Layers 0, 1 and the feature tree are always exercised.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="form-recon-")

import recon_fixtures as fx  # noqa: E402
from form.recon import distance, holes, mesh  # noqa: E402

TOL = 0.02
TESTED_AT = {"spur_gear": 0.05}       # the tolerance each fixture's full run uses (Layer 0 does not depend on it)
_runs = {}


def run(name, tolerance=TOL, layer=2, program=False):
    """The pipeline's report for one fixture (computed once per setting); without the program route unless asked."""
    from form.recon import pipeline
    key = (name, tolerance, layer, program)
    if key not in _runs:
        stl = Path(TMP) / f"{name}.stl"
        if not stl.exists():
            fx.export(name, TMP)
        out = Path(TMP) / f"out-{name}-{tolerance}-{layer}{'-p' if program else ''}"
        keep = pipeline._program
        if not program:
            pipeline._program = lambda *a, **k: {"report": {"method": "sketches and extrusions", "error": "off for this test"}}
        try:
            # a long budget: on a loaded machine (the whole suite in parallel) the feature search must not run out of
            # time and give a different answer
            _runs[key] = (pipeline.reconstruct(stl, out, name, tolerance, layer, budget_s=900.0), out)
        finally:
            pipeline._program = keep
    return _runs[key]


def facts(name):
    return fx.FIXTURES[name]()[1]


class Readers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stl, _, _ = fx.export("box_with_holes", TMP)
        cls.T, cls.info = mesh.read_triangles(cls.stl)

    def test_binary_ascii_obj_3mf_agree(self):
        V, F, w = mesh.weld(self.T)
        self.assertEqual(self.info["format"], "stl (binary)")
        d = Path(TMP)
        # ASCII STL
        lines = ["solid t"] + [f"facet normal 0 0 0\n outer loop\n" + "".join(f"  vertex {x!r} {y!r} {z!r}\n" for x, y, z in t)
                                + " endloop\nendfacet" for t in self.T.tolist()] + ["endsolid t"]
        (d / "a.stl").write_text("\n".join(lines))
        # OBJ with a quad, fan-triangulated
        obj = ["v %r %r %r" % tuple(p) for p in V.tolist()] + ["f %d %d %d" % tuple(f) for f in (F + 1).tolist()]
        (d / "a.obj").write_text("\n".join(obj))
        # 3MF, in centimetres, with a build transform that moves it 10 mm in x
        import zipfile
        vx = "".join(f'<vertex x="{x / 10!r}" y="{y / 10!r}" z="{z / 10!r}"/>' for x, y, z in V.tolist())
        tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in F.tolist())
        model = ('<?xml version="1.0"?><model unit="centimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                 f'<resources><object id="1" type="model"><mesh><vertices>{vx}</vertices><triangles>{tx}</triangles></mesh></object></resources>'
                 '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 1 0 0"/></build></model>')
        with zipfile.ZipFile(d / "a.3mf", "w") as z:
            z.writestr("3D/3dmodel.model", model)
        for f, shift, fmt in (("a.stl", 0, "stl (ascii)"), ("a.obj", 0, "obj"), ("a.3mf", 10.0, "3mf (centimeter)")):
            T, info = mesh.read_triangles(d / f)
            self.assertEqual(info["format"], fmt)
            self.assertEqual(len(T), len(self.T))
            V2, F2, _ = mesh.weld(T)
            self.assertEqual(len(V2), len(V))
            np.testing.assert_allclose(V2.min(axis=0) - [shift, 0, 0], V.min(axis=0), atol=1e-5)
        self.assertTrue(mesh.topology(V, F)["closed"])

    def test_holes_and_non_manifold_edges_are_reported_not_fixed_silently(self):
        from form.recon import pipeline
        V, F, _ = mesh.weld(self.T)
        open_f = F[1:]                                       # one triangle missing: one open boundary
        top = mesh.topology(V, open_f)
        self.assertEqual((top["closed"], top["boundary_loops"], top["boundary_edges"]), (False, 1, 3))
        fin = np.r_[F, [[F[0, 0], F[0, 1], int(np.argmax(V[:, 2]))]]]   # a third triangle on one edge
        self.assertGreaterEqual(mesh.topology(V, fin)["non_manifold_edges"], 1)
        p = Path(TMP) / "open.stl"
        mesh.write_stl(p, V, open_f)
        rep = pipeline.reconstruct(p, Path(TMP) / "out-open-nofill", "open", TOL, 0, fill_holes=False)
        self.assertIn("not closed", rep["error"])
        self.assertNotIn("result", rep)
        rep = pipeline.reconstruct(p, Path(TMP) / "out-open", "open", TOL, 0)
        self.assertEqual([r["repair"] for r in rep["repairs"]], ["filled hole"])     # said, not silent
        self.assertEqual(rep["input"]["topology"]["before_repair"]["boundary_loops"], 1)
        self.assertTrue(rep["layers"]["0"]["valid"])

    def test_exact_point_triangle_distance(self):
        A, B, C = np.array([[0, 0, 0.0]]), np.array([[1, 0, 0.0]]), np.array([[0, 1, 0.0]])
        P = np.array([[0.2, 0.2, 1.0], [-1, -1, 0.0], [2, 0, 0.0], [0.6, 0.6, 0.0]])
        Q = np.vstack([distance.closest_on_triangles(p[None], A, B, C) for p in P])
        np.testing.assert_allclose(Q, [[0.2, 0.2, 0], [0, 0, 0], [1, 0, 0], [0.5, 0.5, 0]], atol=1e-12)

    def test_hole_sizes_snap_to_standards_with_provenance(self):
        s = holes.snap(5.507, 0.04)
        self.assertEqual((s["diameter_mm"], s["standard"], s["provenance"]), (5.5, "M5 clearance, normal (ISO 273)", "computed from mesh"))
        self.assertEqual(holes.snap(6.61, 0.04)["standard"], "M6 clearance, normal (ISO 273)")
        self.assertEqual(holes.snap(8.0, 0.04)["standard"], "Ø8 mm drill")
        self.assertIsNone(holes.snap(7.77, 0.01)["standard"])


# Accuracy on each fixture; the numbers are computed by comparing with the mesh, never assumed. The checks are grouped
# by fixture, one test class each, so a fixture's pipeline run (minutes on a CI runner) happens once per process and the
# classes can run in parallel (scripts/ci/test_shards.py splits this module by class).

def check_layer0(t, name):
    """Layer 0 is the mesh exactly: one valid solid, at most 0.1 um from the mesh, the same volume, a STEP file."""
    if name == "spur_gear" and importlib.util.find_spec("py_gearworks") is None:
        t.skipTest("py_gearworks is not installed (the [parts] extra)")
    rep, out = run(name, TESTED_AT.get(name, TOL))
    L0 = rep["layers"]["0"]
    t.assertTrue(L0["valid"])
    t.assertEqual(L0["solids"], 1)
    t.assertLessEqual(L0["hausdorff_mm"], 1e-4)
    mv = rep["result"]["mesh_volume_mm3"]
    t.assertAlmostEqual(L0["volume_mm3"], mv, delta=1e-6 * abs(mv))
    t.assertTrue((out / f"{name}_layer0.step").is_file())


def check_mostly_parametric_with_the_right_holes(t, name):
    rep, _ = run(name)
    L1 = rep["layers"]["1"]
    t.assertTrue(L1["valid"])
    t.assertGreaterEqual(L1["parametric_area_pct"], 90.0)
    t.assertLessEqual(L1["hausdorff_mm"], TOL)
    got = sorted(h["diameter_mm"] for h in rep["layers"]["2"]["holes"])
    t.assertEqual(got, sorted(facts(name)["holes"]))
    t.assertTrue(all(h["provenance"] == "computed from mesh" for h in rep["layers"]["2"]["holes"]))


def check_layer2_recipe_rebuilds_within_tolerance(t, name):
    rep, out = run(name)
    L2 = rep["layers"]["2"]
    t.assertTrue(L2["verified"], L2.get("error"))
    t.assertLessEqual(L2["hausdorff_mm"], TOL)
    t.assertEqual(rep["layer_achieved"], 2)
    t.assertTrue(rep["result"]["recipe_verified"])
    src = (out / f"{name}_recipe.py").read_text()
    t.assertIn('provenance="mesh"', src)
    # the recipe is a real design: rebuild it here and compare again
    from form.recon import features, solid, verify
    from form.recon.pipeline import load
    V, F, _, _ = load(Path(TMP) / f"{name}.stl")
    shape = features.build_source(src)
    P, T = solid.tessellate(shape, 0.002)
    t.assertLessEqual(verify.compare(V, F, P, T)["hausdorff_mm"], TOL)


class BoxWithHoles(unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "box_with_holes")

    def test_mostly_parametric_with_the_right_holes(self):
        check_mostly_parametric_with_the_right_holes(self, "box_with_holes")

    def test_layer2_recipe_rebuilds_within_tolerance(self):
        check_layer2_recipe_rebuilds_within_tolerance(self, "box_with_holes")
        box = run("box_with_holes")[0]["layers"]["2"]
        self.assertEqual(sorted(p["kind"] for p in box["patterns"]), ["grid", "single"])

    def test_report_and_deviation_map(self):
        rep, out = run("box_with_holes")
        on_disk = json.loads((out / "box_with_holes_report.json").read_text())
        self.assertEqual(on_disk["result"], rep["result"])
        for k in ("hausdorff_mm", "volume_delta_mm3", "volume_delta_pct", "parametric_area_pct", "frozen_area_pct"):
            self.assertIn(k, rep["result"])
        dm = json.loads((out / "box_with_holes_deviation.json").read_text())
        self.assertEqual((dm["map"], dm["evidence"], dm["legend"]["unit"]), ("deviation", "computed", "mm"))
        self.assertTrue(dm["positions"] and dm["values"] and dm["colors"])
        self.assertLessEqual(dm["stats"]["max_mm"], TOL)


class FilletedBracket(unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "filleted_bracket")

    def test_mostly_parametric_with_the_right_holes(self):
        check_mostly_parametric_with_the_right_holes(self, "filleted_bracket")

    def test_layer2_recipe_rebuilds_within_tolerance(self):
        check_layer2_recipe_rebuilds_within_tolerance(self, "filleted_bracket")


class TurnedPart(unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "turned_part")

    def test_finds_its_cone_and_torus(self):
        rep, _ = run("turned_part")
        L1 = rep["layers"]["1"]
        self.assertGreaterEqual(L1["parametric_area_pct"], 90.0)
        self.assertTrue({"plane", "cylinder", "cone", "torus"} <= set(L1["by_kind"]))
        self.assertEqual([b["diameter_mm"] for b in rep["layers"]["2"]["features"] if b["kind"] == "bore"], facts("turned_part")["holes"])
        self.assertTrue(any(s["kind"] == "axisymmetric" for s in rep["layers"]["2"]["symmetry"]))

    def test_layer2_recipe_rebuilds_within_tolerance(self):
        check_layer2_recipe_rebuilds_within_tolerance(self, "turned_part")


class Gear(unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "gear")

    def test_flanks_stay_honest(self):
        """Spline flanks: the gear is recognised (18 teeth, module 2, 20 degrees), but the mesh's own facets are
        about 0.03 mm from the flanks it was made from, so at 0.02 mm no smooth gear can be within the tolerance and
        the parametric gear is not offered. The feature tree keeps the toothed outline as reconstructed (frozen
        facets) under the bore, but only within its own limit (Layer 1's distance), which is outside the 0.02 mm
        asked for; the mixed result (the exact solid with its faces as dimensions) is within it and makes more of the
        surface editable, so it is the result and the tree is listed beside it. At 0.05 mm the parametric gear is
        within the tolerance."""
        rep, out = run("gear")
        L2 = rep["layers"]["2"]
        gear = next(t for t in L2["also_tried"] if t.get("method") == "spur gear")
        self.assertFalse(gear["verified"])
        self.assertIn("from the mesh", gear["error"])
        L1 = rep["layers"]["1"]
        self.assertTrue(L1["valid"])
        self.assertGreater(L1["by_kind"]["facet"]["area_mm2"], 0)
        tree = next(t for t in L2["also_tried"] if t.get("method") == "feature tree")
        self.assertEqual(tree["base"], "embedded solid")
        self.assertLess(tree["driven_by_params_pct"], 50)
        self.assertGreater(tree["hausdorff_mm"], TOL)                          # inside Layer 1's limit, not the 0.02
        self.assertTrue(L2["method"].startswith("mixed"), L2.get("method"))
        self.assertLessEqual(rep["result"]["hausdorff_mm"], TOL)
        self.assertGreater(rep["result"]["feature_area_pct"], tree["driven_by_params_pct"])
        # with a looser tolerance the parametric gear is within it
        rep5, _ = run("gear", tolerance=0.05)
        g5 = rep5["layers"]["2"]
        self.assertTrue(g5["verified"], g5.get("error"))
        self.assertEqual(g5["method"], "spur gear")
        self.assertEqual(g5["fit"]["teeth"], 18)
        self.assertLessEqual(g5["hausdorff_mm"], 0.05)


def rebuild(name, out, **changes):
    """Build a fixture's recipe with some Params changed. Returns (solid, check)."""
    from form.recipes import meshsolid
    from form.recon import solid, tree
    src = (out / f"{name}_recipe.py").read_text()
    meshsolid.set_paths({p.name: str(p) for p in out.glob("*_base.step")})
    try:
        if changes:
            from form.recipes import SOURCE_PREFIX, load_source, source_id
            rid = source_id(src)
            p = Path(TMP) / f"{rid[len(SOURCE_PREFIX):]}.py"
            p.write_text(src)
            rec = load_source(p, rid)
            shape = rec.build(rec.validate({**rec.defaults(), **changes}))[-1].shape
        else:
            shape = tree._build(src)
    finally:
        meshsolid.set_paths({})
    return shape, solid.check(shape.wrapped)


def params(out, name):
    src = (out / f"{name}_recipe.py").read_text()
    import re
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"Param\('([a-z0-9_]+)', '[^']*', ([-0-9.e]+)", src)} | \
        {m.group(1): float(m.group(2)) for m in re.finditer(r'Param\("([a-z0-9_]+)", "[^"]*", ([-0-9.e]+)', src)}


class _Edits:
    """Layer 2 on real mechanical parts, a gear and an organic shape: a recipe of features that verifies within the
    tolerance, and whose Params change the part (a different fillet radius or hole size still builds a valid solid,
    and the volume moves the way it should)."""

    def assert_edits(self, name, out, key, delta, sign):
        base, ck0 = rebuild(name, out)
        v = params(out, name)[key]
        shape, ck = rebuild(name, out, **{key: v + delta})
        self.assertTrue(ck["valid"], f"{key} = {v + delta} gives an invalid solid")
        self.assertEqual(ck["solids"], 1)
        dv = ck["volume_mm3"] - ck0["volume_mm3"]
        self.assertGreater(sign * dv, 1e-3, f"{key} {v} -> {v + delta}: volume {ck0['volume_mm3']:.3f} -> {ck['volume_mm3']:.3f}")


class SteppedBracket(_Edits, unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "stepped_bracket")

    def test_feature_tree(self):
        rep, out = run("stepped_bracket")
        L2 = rep["layers"]["2"]
        self.assertEqual(rep["layer_achieved"], 2, L2.get("error"))
        self.assertEqual(L2["base"], "extrusion stack")
        self.assertLessEqual(L2["hausdorff_mm"], TOL)
        self.assertEqual(L2["driven_by_params_pct"], 100.0)
        self.assertEqual(sorted(h["diameter_mm"] for h in L2["holes"]), facts("stepped_bracket")["holes"])
        axes = {tuple(abs(round(x)) for x in h["axis"]) for h in L2["holes"]}
        self.assertEqual(axes, {(0, 0, 1), (1, 0, 0)})                         # holes on two axes
        cb = [h for h in L2["holes"] if len(h["steps"]) == 2]
        self.assertEqual([h["steps"][0][1] for h in cb], facts("stepped_bracket")["counterbores"])
        self.assertEqual(sorted({f["radius_mm"] for f in L2["features"] if f["kind"] == "fillet"}), facts("stepped_bracket")["fillets"])
        self.assertEqual([f["distance_mm"] for f in L2["features"] if f["kind"] == "chamfer"], facts("stepped_bracket")["chamfers"])
        src = (out / "stepped_bracket_recipe.py").read_text()
        for word in ("pocket1_depth", "step1_h", "fillet1_r", "hole2_cbore_d", "fillet("):
            self.assertIn(word, src)
        # edits: a bigger fillet takes material off a convex corner, a bigger hole takes material away, a deeper
        # pocket too
        p = params(out, "stepped_bracket")
        convex = "fillet2_r" if p["fillet2_r"] == 5.0 else "fillet1_r"
        self.assert_edits("stepped_bracket", out, convex, 1.0, -1)
        self.assert_edits("stepped_bracket", out, "hole1_d", 1.0, -1)
        self.assert_edits("stepped_bracket", out, "pocket1_depth", 1.0, -1)


class ShippedConfiguration(unittest.TestCase):
    def test_shipped_configuration_keeps_layer1_its_time(self):
        """The pipeline as the app runs it: the program route ON (no stub) and the default 240 s budget. The program
        route (both its readings together) is held to its share of the budget, so the floor, Layer 1 and the
        feature search have their time and the part comes out editable.

        A budget in seconds buys less work on a slower machine: 240 s is the default on the machine it was set on,
        and a CI runner that does the same work two or three times slower gets that many times the seconds (the
        same amount of work), or the result here would say how fast the runner is, not what the pipeline does."""
        import machine
        from form.recon import pipeline
        stl = Path(TMP) / "stepped_bracket.stl"
        if not stl.exists():
            fx.export("stepped_bracket", TMP)
        k = min(machine.speed(fresh=True), 2.5)
        budget = round(240.0 * k)
        print(f"\nshipped configuration: machine speed {k:.2f}, budget {budget} s")
        t = time.perf_counter()
        rep = pipeline.reconstruct(stl, Path(TMP) / "out-shipped-stepped_bracket", "stepped_bracket", TOL, 2,
                                   budget_s=budget)
        took = time.perf_counter() - t
        print(f"shipped configuration: {took:.0f} s, the program route {rep.get('program_seconds')} s")
        # the route is stopped PROGRAM_SLACK after its share at the latest (bounded.py); starting and stopping its
        # helper process is on top of that, and takes longer on a slower machine and under coverage
        slack = pipeline.PROGRAM_SLACK + (35 if "coverage" in sys.modules else 5) * k
        self.assertLessEqual(rep["program_seconds"], pipeline.PROGRAM_SHARE * budget + slack, "the program route keeps to its share")
        L1, L2 = rep["layers"]["1"], rep["layers"]["2"]
        self.assertNotIn("error", L1)
        self.assertEqual(rep["layer_achieved"], 2, L2.get("error"))
        self.assertLessEqual(rep["result"]["hausdorff_mm"], TOL)
        if L2.get("kind") != "program":                    # the feature tree won: it found every hole, as without
            self.assertEqual(sorted(h["diameter_mm"] for h in L2["holes"]), facts("stepped_bracket")["holes"])
        self.assertGreater(rep["result"]["editable_pct"], 0.0)
        self.assertLess(took, budget * 1.5, f"{took:.0f} s of a {budget} s budget")


class FlangedShaft(_Edits, unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "flanged_shaft")

    def test_feature_tree(self):
        rep, out = run("flanged_shaft")
        L2 = rep["layers"]["2"]
        self.assertEqual(rep["layer_achieved"], 2, L2.get("error"))
        self.assertEqual(L2["base"], "revolution")
        self.assertLessEqual(L2["hausdorff_mm"], TOL)
        self.assertEqual(sorted(h["diameter_mm"] for h in L2["holes"]), facts("flanged_shaft")["holes"])
        polar = [p for p in L2["patterns"] if p["kind"] == "polar"]
        self.assertEqual([(p["n"], p["pcd_mm"]) for p in polar], [(4, 38.0)])
        self.assertEqual([f["diameter_mm"] for f in L2["features"] if f["kind"] == "bore"], facts("flanged_shaft")["bores"])
        self.assertEqual([f["radius_mm"] for f in L2["features"] if f["kind"] == "fillet"], facts("flanged_shaft")["fillets"])
        self.assert_edits("flanged_shaft", out, "fillet1_r", 1.0, 1)              # a concave round adds material
        self.assert_edits("flanged_shaft", out, "hole1_d", 0.5, -1)
        shape, ck = rebuild("flanged_shaft", out, hole1_pcd=42.0)          # the bolt circle moves out, still one solid
        self.assertTrue(ck["valid"])
        self.assertEqual(ck["solids"], 1)


class SpurGear(_Edits, unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "spur_gear")

    def test_feature_tree(self):
        try:
            import py_gearworks  # noqa: F401
        except ImportError:
            self.skipTest("py_gearworks is not installed")
        # The STL of a py_gearworks gear is itself 0.03 to 0.04 mm from the gear's spline flanks (measured), so it is
        # checked against the mesh at 0.05 mm, and against the gear it was made from at 0.02 mm.
        rep, out = run("spur_gear", tolerance=0.05)
        L2 = rep["layers"]["2"]
        self.assertEqual(rep["layer_achieved"], 2, L2.get("error"))
        self.assertEqual(L2["method"], "spur gear")
        self.assertIn("form.parts", L2["base"])
        self.assertLessEqual(L2["hausdorff_mm"], 0.05)
        from form.recon import solid, verify
        part, _ = fx.FIXTURES["spur_gear"]()
        Pp, Tp = solid.tessellate(part, 0.002)
        shape, _ = rebuild("spur_gear", out)
        Pr, Tr = solid.tessellate(shape, 0.002)
        self.assertLessEqual(verify.compare(Pp, Tp, Pr, Tr)["hausdorff_mm"], TOL)
        f = facts("spur_gear")
        self.assertEqual((L2["fit"]["teeth"], round(L2["fit"]["module_mm"], 2)), (f["teeth"], f["module"]))
        self.assertIn("from form.parts import spur_gear", (out / "spur_gear_recipe.py").read_text())
        self.assertEqual(rep["result"]["driven_by_params_pct"], 100.0)
        shape, ck = rebuild("spur_gear", out, teeth=20)                         # two more teeth: a bigger gear
        _, ck0 = rebuild("spur_gear", out)
        self.assertTrue(ck["valid"])
        self.assertGreater(ck["volume_mm3"], ck0["volume_mm3"])


class OrganicBlob(_Edits, unittest.TestCase):
    def test_layer0_is_the_mesh_exactly(self):
        check_layer0(self, "organic_blob")

    def test_feature_tree(self):
        rep, out = run("organic_blob")
        L1 = rep["layers"]["1"]
        self.assertTrue(L1["valid"], L1.get("error"))
        self.assertGreaterEqual(L1["freeform_area_pct"], 80.0)                 # B-spline patches, not facets
        self.assertLessEqual(L1["frozen_area_pct"], 1.0)
        self.assertLessEqual(L1["hausdorff_mm"], TOL)
        L2 = rep["layers"]["2"]
        self.assertEqual(rep["layer_achieved"], 2, L2.get("error"))
        self.assertEqual(L2["base"], "embedded solid")
        self.assertEqual([h["diameter_mm"] for h in L2["holes"]], facts("organic_blob")["holes"])
        self.assertLessEqual(L2["hausdorff_mm"], TOL)
        self.assertTrue(rep["result"]["recipe_references"])
        self.assertGreater(rep["result"]["freeform_area_pct"], 80.0)
        self.assert_edits("organic_blob", out, "hole1_d", 2.0, -1)


class Surfaces(unittest.TestCase):
    """Studio, CLI and the app's route, through the kernel worker."""

    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = str(Path(TMP) / "data")
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())
        cls.stl, _, _ = fx.export("box_with_holes", TMP)

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_make_editable_from_an_imported_reference(self):
        st = self.st
        host = st.create("Holder", "storage_box")
        st.import_reference(host, self.stl, "scan.stl")
        seen = []
        out = st.reconstruct_reference(st.load(host["id"]), "scan.stl", on_progress=seen.append)
        self.assertTrue(seen)                                       # progress came through the worker
        p = st.load(out["project"])
        self.assertEqual(p["reconstruction"]["summary"]["layer"], 2)
        self.assertTrue(p["reconstruction"]["summary"]["recipe_verified"])
        self.assertTrue(p["reconstruction"]["summary"]["headline"].startswith("100% editable"))
        prov = st.rev(p)["provenance"]
        m5 = [v for v in prov.values() if "M5 clearance" in (v.get("note") or "")]
        self.assertTrue(m5, prov)                                  # the four Ø5.5 holes: one Param, a standard size
        self.assertEqual(m5[0]["source"], "mesh")
        self.assertTrue((st.dir(p["id"]) / "reconstruction" / "box_with_holes_report.json").is_file() or
                        any(f.endswith("_report.json") for f in p["reconstruction"]["files"]))
        self.assertIn("reconstruct", [d["kind"] for d in p["decisions"]])
        job = st.run_sync(p["id"], ["geometry"])
        self.assertEqual(job["state"], "done", job)

    def test_obj_reference_part(self):
        V, F, _ = mesh.weld(mesh.read_triangles(self.stl)[0])
        obj = Path(TMP) / "plate.obj"
        obj.write_text("\n".join(["v %r %r %r" % tuple(p) for p in V.tolist()] + ["f %d %d %d" % tuple(f) for f in (F + 1).tolist()]))
        p = self.st.create("OBJ host", "storage_box")
        rec = self.st.import_reference(p, obj)
        self.assertEqual((rec["format"], rec["triangles"]), ("obj", len(F)))
        np.testing.assert_allclose(rec["bbox"], [[-30, -20, 0], [30, 20, 10]], atol=1e-4)

    def test_layer0_design_wraps_the_solid(self):
        out = self.st.reconstruct(self.stl, name="Box exact", layer=0)
        p = self.st.load(out["project"])
        self.assertEqual(out["summary"]["layer"], 0)
        self.assertIn("self.reference(", self.st.source_text(p))
        self.assertTrue(any(r["file"].endswith(".step") for r in self.st.references(p)))

    def test_cli(self):
        env = {**os.environ, "FORM_DATA": str(Path(TMP) / "cli")}
        r = subprocess.run([sys.executable, "-m", "form", "reconstruct", str(self.stl), "--layer", "0", "--name", "CLI box"],
                           capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = json.loads(r.stdout)
        self.assertEqual(out["name"], "CLI box")
        self.assertLessEqual(out["summary"]["hausdorff_mm"], 1e-4)

    def test_mcp_tool_is_registered(self):
        import anyio
        from form import mcp_server

        async def names():
            return {t.name for t in await mcp_server.build().list_tools()}
        self.assertIn("reconstruct", anyio.run(names))


class PartialFreeze(unittest.TestCase):
    """A plane with a few triangles off it keeps the rest of its triangles as a plane, one region per connected piece."""

    def test_plane_keeps_its_good_triangles(self):
        from form.recon import fit, pipeline
        from form.recon.segment import Region
        # a 4 x 1 strip of quads (8 triangles) on z = 0; the two middle triangles are "off"
        V = np.array([[x, y, 0.0] for y in (0, 1) for x in range(5)])
        F = []
        for x in range(4):
            a, b, c, d = x, x + 1, 5 + x + 1, 5 + x
            F += [[a, b, c], [a, c, d]]
        F = np.array(F)
        plane = Region(0, "plane", np.arange(8), fit.fit_plane(V), 4.0)
        out = pipeline._freeze(V, F, [plane], [0], {0: np.array([2, 3])})
        kinds = sorted(r.kind for r in out)
        self.assertEqual(kinds.count("facet"), 2)
        planes = [r for r in out if r.kind == "plane"]
        self.assertEqual(sorted(len(r.tris) for r in planes), [2, 4])      # two pieces either side of the frozen quad
        self.assertEqual([r.id for r in out], list(range(len(out))))
        self.assertEqual(len(pipeline._pieces(F, np.array([0, 1, 6, 7]))), 2)


if __name__ == "__main__":
    unittest.main()
