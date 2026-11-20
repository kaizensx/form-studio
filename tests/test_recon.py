"""Mesh to editable CAD (form/recon): readers, repairs that are reported, and the three layers on known parts.

The fixtures are real build123d parts exported as STL (tests/recon_fixtures.py): a box with holes, a turned part, a
filleted bracket and a spur gear with spline flanks. The pipeline runs in this process for the layer checks and once
through the Studio (kernel worker) for the project, CLI and "Make editable" routes.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="form-recon-")

import recon_fixtures as fx  # noqa: E402
from form.recon import distance, holes, mesh  # noqa: E402

TOL = 0.02
_runs = {}


def run(name, tolerance=TOL, layer=2):
    """The pipeline's report for one fixture (computed once per setting)."""
    from form.recon import pipeline
    key = (name, tolerance, layer)
    if key not in _runs:
        stl = Path(TMP) / f"{name}.stl"
        if not stl.exists():
            fx.export(name, TMP)
        out = Path(TMP) / f"out-{name}-{tolerance}-{layer}"
        _runs[key] = (pipeline.reconstruct(stl, out, name, tolerance, layer), out)
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


class Layers(unittest.TestCase):
    """Accuracy on each fixture. The numbers are computed by comparing with the mesh, never assumed."""

    def test_layer0_is_the_mesh_exactly(self):
        for name in fx.FIXTURES:
            with self.subTest(name):
                rep, out = run(name)
                L0 = rep["layers"]["0"]
                self.assertTrue(L0["valid"])
                self.assertEqual(L0["solids"], 1)
                self.assertLessEqual(L0["hausdorff_mm"], 1e-4)
                mv = rep["result"]["mesh_volume_mm3"]
                self.assertAlmostEqual(L0["volume_mm3"], mv, delta=1e-6 * abs(mv))
                self.assertTrue((out / f"{name}_layer0.step").is_file())

    def test_prismatic_parts_are_mostly_parametric_with_the_right_holes(self):
        for name in ("box_with_holes", "filleted_bracket"):
            with self.subTest(name):
                rep, _ = run(name)
                L1 = rep["layers"]["1"]
                self.assertTrue(L1["valid"])
                self.assertGreaterEqual(L1["parametric_area_pct"], 90.0)
                self.assertLessEqual(L1["hausdorff_mm"], TOL)
                got = sorted(h["diameter_mm"] for h in rep["layers"]["2"]["holes"])
                self.assertEqual(got, sorted(facts(name)["holes"]))
                self.assertTrue(all(h["provenance"] == "computed from mesh" for h in rep["layers"]["2"]["holes"]))

    def test_turned_part_finds_its_cone_and_torus(self):
        rep, _ = run("turned_part")
        L1 = rep["layers"]["1"]
        self.assertGreaterEqual(L1["parametric_area_pct"], 90.0)
        self.assertTrue({"plane", "cylinder", "cone", "torus"} <= set(L1["by_kind"]))
        self.assertEqual([b["diameter_mm"] for b in rep["layers"]["2"]["bores_in_profile"]], facts("turned_part")["holes"])
        self.assertTrue(any(s["kind"] == "axisymmetric" for s in rep["layers"]["2"]["symmetry"]))

    def test_layer2_recipe_rebuilds_within_tolerance(self):
        for name in ("box_with_holes", "filleted_bracket", "turned_part"):
            with self.subTest(name):
                rep, out = run(name)
                L2 = rep["layers"]["2"]
                self.assertTrue(L2["verified"], L2.get("error"))
                self.assertLessEqual(L2["hausdorff_mm"], TOL)
                self.assertEqual(rep["layer_achieved"], 2)
                self.assertTrue(rep["result"]["recipe_verified"])
                src = (out / f"{name}_recipe.py").read_text()
                self.assertIn('provenance="mesh"', src)
                # the recipe is a real design: rebuild it here and compare again
                from form.recon import features, solid, verify
                from form.recon.pipeline import load
                V, F, _, _ = load(Path(TMP) / f"{name}.stl")
                shape = features.build_source(src)
                P, T = solid.tessellate(shape, 0.002)
                self.assertLessEqual(verify.compare(V, F, P, T)["hausdorff_mm"], TOL)
        box = run("box_with_holes")[0]["layers"]["2"]
        self.assertEqual([p["kind"] for p in box["patterns"]], ["single", "grid"])

    def test_gear_flanks_stay_honest(self):
        """Spline flanks are not analytic: at 0.02 mm they stay frozen facets and the extrusion recipe is written but
        not offered, because the mesh's own facets leave it 0.04 mm from any straight extrusion."""
        rep, out = run("gear")
        L1 = rep["layers"]["1"]
        self.assertTrue(L1["valid"])
        self.assertLess(L1["parametric_area_pct"], 100.0)
        self.assertGreater(L1["by_kind"]["facet"]["area_mm2"], 0)
        L2 = rep["layers"]["2"]
        self.assertEqual(L2["kind"], "extrude")
        self.assertFalse(L2["verified"])
        self.assertIn("from the mesh", L2["error"])
        self.assertEqual(rep["layer_achieved"], 1)
        self.assertEqual([h["diameter_mm"] for h in L2["holes"]], facts("gear")["holes"])
        self.assertIn({"kind": "rotation", "n": 18}, [{k: s[k] for k in ("kind", "n")} for s in L2["symmetry"] if "n" in s])
        # with a looser tolerance the recipe is within it
        rep5, _ = run("gear", tolerance=0.05)
        self.assertTrue(rep5["layers"]["2"]["verified"])
        self.assertLessEqual(rep5["layers"]["2"]["hausdorff_mm"], 0.05)

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
        prov = st.rev(p)["provenance"]
        self.assertEqual(prov["hole2_d"]["source"], "mesh")
        self.assertIn("M5 clearance", prov["hole2_d"]["note"])
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


if __name__ == "__main__":
    unittest.main()
