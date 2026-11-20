"""Reference parts an agent rebuilds as clean CAD (form/remodel), and meshes drawn without their triangle edges.

The fixtures are a small synthetic mechanism built in build123d and exported as STL (tests/remodel_fixtures.py): a tray
with chamfered edges, rails, a rounded slot, a through hole and a pivot pin; a slider running between the rails; and a
stepped disc turning on the pin.
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
TMP = tempfile.mkdtemp(prefix="form-remodel-")

import remodel_fixtures as fx  # noqa: E402


def stl(name):
    return fx.export(name, Path(TMP) / "in")


class Sections(unittest.TestCase):
    def test_loops_are_described(self):
        from form.remodel import analyze as an
        from form.remodel import sections as sx
        V, F, info = an.load(stl("tray"))
        self.assertTrue(info["closed"])
        loops = sx.analyse(V, F, 2, 2.25)["loops"]
        kinds = sorted((r["role"], r["kind"]) for r in loops)
        self.assertEqual(kinds, [("opening", "circle"), ("opening", "slot"), ("outline", "rectangle")])
        slot = next(r for r in loops if r["kind"] == "slot")
        self.assertAlmostEqual(slot["width"], 6.0, delta=0.02)
        self.assertAlmostEqual(slot["length"], 20.0, delta=0.05)
        hole = next(r for r in loops if r["kind"] == "circle")
        self.assertAlmostEqual(hole["diameter"], 4.0, delta=0.02)
        self.assertEqual(hole["center"], [0.0, 40.0])

    def test_occupancy_volume(self):
        from form.remodel import analyze as an
        from form.remodel.occupancy import Occupancy
        V, F, _ = an.load(stl("tray"))
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        vol = np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6
        o = Occupancy(V, F, h=0.2)
        self.assertAlmostEqual(o.grid.sum() * o.h ** 3, vol, delta=0.03 * vol)
        self.assertTrue(o.inside(np.array([[20.0, 0, 1.5]]))[0])          # in the plate
        self.assertFalse(o.inside(np.array([[0.0, 40, 1.5]]))[0])         # in the hole


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from form.remodel import analyze as an
        V, F, _ = an.load(stl("tray"))
        cls.res = an.public(an.analyse(V, F, name="tray"))
        cls.kinds = {}
        for f in cls.res["features"]:
            cls.kinds.setdefault(f["kind"], []).append(f)

    def test_axes_and_levels(self):
        r = self.res
        self.assertTrue(r["principal"]["aligned_to_world"])
        self.assertEqual(r["up_axis"], "z")
        ups = {f["at"] for f in r["levels"]["faces"] if f["facing"] == "up"}
        self.assertTrue({1.5, 3.0, 8.0, 11.0} <= ups, ups)                 # slot floor, plate, pin top, rails

    def test_holes_bosses_slots(self):
        hole = self.kinds["hole"][0]
        self.assertAlmostEqual(hole["diameter"], 4.0, delta=0.01)
        self.assertTrue(hole["through"])
        self.assertEqual(hole["axis"], "z")
        pin = self.kinds["boss"][0]
        self.assertAlmostEqual(pin["diameter"], 6.0, delta=0.01)
        self.assertAlmostEqual(pin["height_mm"], 5.0, delta=0.05)
        opening = next(f for f in self.kinds["opening"] if f["shape"] == "slot")
        self.assertAlmostEqual(opening["width"], 6.0, delta=0.05)

    def test_rails_chamfers_fillets(self):
        rails = [f for f in self.kinds["rail"] if f["across"] == "x"]
        self.assertEqual(len(rails), 2)
        self.assertTrue(all(abs(f["thickness"] - 2.0) < 0.01 and f["along"] == "y" for f in rails))
        ch = self.kinds["chamfer"]
        self.assertEqual(len(ch), 4)
        self.assertTrue(all(abs(c["legs"][0] - 1.0) < 0.02 and c["angles_deg"] == [45.0, 45.0] for c in ch))
        self.assertTrue(any(abs(f["radius"] - 3.0) < 0.02 and not f["convex"] for f in self.kinds["fillet"]))
        self.assertEqual(self.res["wall_thickness"]["min_mm"], 1.5)        # under the slot pocket

    def test_symmetry_and_pictures(self):
        from form.remodel import analyze as an
        sym = {s["plane"]: s["verdict"] for s in self.res["symmetry"]}
        self.assertEqual(sym["y = 0"], "not symmetric")                    # the hole, the slot and the pin are off it
        self.assertNotEqual(sym["x = 0"], "symmetric")                     # the pin is left of centre
        V, F, _ = an.load(stl("tray"))
        pngs = an.images(an.analyse(V, F, name="tray"))
        self.assertEqual(sorted(a for a, _ in pngs), ["x", "y", "z"])
        self.assertTrue(all(p[:8] == b"\x89PNG\r\n\x1a\n" for _, p in pngs))


class Mechanism(unittest.TestCase):
    def test_slide_hinge_and_stop(self):
        from form.remodel import analyze as an
        from form.remodel import mechanism as me
        parts = [(n, *an.load(stl(n))[:2]) for n in ("tray", "slider", "disc")]
        out = me.analyse(parts)
        j = {x["part"]: x for x in out["joints"]}
        self.assertEqual(j["slider"]["kind"], "slide")
        self.assertEqual(j["slider"]["axis"], "y")
        # the slider runs back until it meets the pivot pin, about 28 mm from where it was given
        self.assertAlmostEqual(j["slider"]["range_mm"][0], -28.5, delta=1.5)
        self.assertTrue(j["slider"]["stops"]["-"])
        self.assertIn("+z", out["motion"]["slider"]["comes_away"])
        self.assertEqual(j["disc"]["kind"], "hinge")
        self.assertEqual(j["disc"]["axis"], "z")
        np.testing.assert_allclose(j["disc"]["through"][:2], [-12.0, -36.0], atol=0.05)
        self.assertAlmostEqual(j["disc"]["bearing_radius_mm"], 3.0, delta=0.05)
        self.assertIn("slides along y", out["summary"])
        clear = out["clearances"]["tray / slider"]
        self.assertAlmostEqual(clear["smallest_clearance_mm"], 0.2, delta=0.03)


class Project(unittest.TestCase):
    """Studio, MCP and CLI routes, through the kernel worker."""

    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = str(Path(TMP) / "data")
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())
        cls.p = cls.st.create("Mechanism", "storage_box")
        for n in ("tray", "slider", "disc"):
            cls.st.import_reference(cls.p, stl(n))

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_analyze_reference_is_saved(self):
        from form.remodel import project as rp
        p = self.st.load(self.p["id"])
        out = rp.analyze_reference(self.st, p, "tray")                     # the stem is enough
        self.assertEqual(out["reference"], "tray.stl")
        self.assertEqual(len(out["images"]), 3)
        self.assertTrue(all(Path(i["path"]).is_file() for i in out["images"]))
        self.assertTrue(Path(out["saved"]).is_file())
        again = rp.analyze_reference(self.st, p, "tray.stl")              # cached
        self.assertEqual(again["features"], json.loads(json.dumps(out["features"])))
        from form.studio import StudioError
        with self.assertRaises(StudioError):
            rp.analyze_reference(self.st, p, "nothing.stl")

    def test_compare_finds_the_changed_hole(self):
        from form.remodel import project as rp
        st = self.st
        rp.analyze_reference(st, st.load(self.p["id"]), "tray")
        d = st.create_design("Tray rebuilt", fx.tray_code(), references=[str(stl("tray"))])
        rp.analyze_reference(st, st.load(d["id"]), "tray")
        same = rp.compare_to_reference(st, st.load(d["id"]), "tray")
        self.assertTrue(same["within_tolerance"], same["verdict"])
        self.assertLess(same["hausdorff_mm"], 0.05)
        self.assertTrue(Path(same["image"]).is_file())
        st.commit(st.load(d["id"]), {"hole_d": 5.0}, origin="test")
        diff = rp.compare_to_reference(st, st.load(d["id"]), "tray")
        self.assertFalse(diff["within_tolerance"])
        worst = diff["worst_regions"][0]
        self.assertAlmostEqual(worst["max_mm"], 0.5, delta=0.05)
        self.assertLess(np.hypot(worst["at"][0] - 0, worst["at"][1] - 40), 3.5)
        self.assertEqual(worst["design_has"], "less material than the mesh")
        self.assertIn("hole", worst["near_feature"])
        hole = next(f for f in diff["features"] if f["feature"].startswith("hole"))
        self.assertFalse(hole["ok"])
        self.assertAlmostEqual(hole["design_diameter"], 5.0, delta=0.02)
        self.assertAlmostEqual(hole["reference_diameter"], 4.0, delta=0.01)

    def test_rebuild_brief_and_guide(self):
        from form import design_guide
        from form.remodel import project as rp
        msg = rp.rebuild_brief(self.st, self.st.load(self.p["id"]))["message"]
        self.assertIn("tray.stl, slider.stl and disc.stl", msg)
        self.assertIn("Never embed the meshes", msg)
        self.assertIn("analyze_assembly", msg)
        self.assertIn("compare_to_reference", msg)
        g = design_guide.topic("reference_parts")["guide"]
        for word in ("never embed the raw meshes", "analyze_reference", "analyze_assembly", "compare_to_reference", "0.1 mm"):
            self.assertIn(word, g)

    def test_mcp_tools_and_measure_message(self):
        import anyio
        from form import mcp_server

        async def names():
            return {t.name for t in await mcp_server.build().list_tools()}
        self.assertTrue({"analyze_reference", "analyze_assembly", "compare_to_reference"} <= anyio.run(names))
        msg = mcp_server._measure_usage([0, 0, 0], None)
        self.assertIn("from_point", msg)
        self.assertIn("to_point", msg)
        self.assertIn('measure(project="p1", from_point=', mcp_server.MEASURE_EXAMPLE)
        self.assertIn("at=", mcp_server.MEASURE_EXAMPLE)

    def test_cli(self):
        env = {**os.environ, "FORM_DATA": str(Path(TMP) / "data")}
        r = subprocess.run([sys.executable, "-m", "form", "analyze-reference", self.p["id"], "disc", "--levels", '{"z": [3.5]}'],
                           capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = json.loads(r.stdout)
        self.assertEqual(out["reference"], "disc.stl")
        self.assertEqual([s["plane"] for s in out["sections"]["z"]], ["z = 3.5"])
        holes = [f for f in out["features"] if f["kind"] == "hole"]
        self.assertAlmostEqual(holes[0]["diameter"], 6.6, delta=0.02)


class FacetEdges(unittest.TestCase):
    """A mesh solid is drawn smooth, with lines only at creases and boundaries; a CAD solid keeps every edge."""

    def test_faceted_solid_draws_creases_only(self):
        from build123d import Box, Cylinder, Pos
        from form import kernel
        from form.recipes.meshsolid import solid_from_triangles
        from form.recon.mesh import read_triangles
        cad = Box(20, 20, 10) - Pos(0, 0, 0) * Cylinder(4, 20)
        n_cad = len(kernel._edges(cad))
        self.assertGreater(n_cad, 12)                                      # box and hole edges, all drawn
        f = Path(TMP) / "cad.stl"
        from build123d import export_stl
        export_stl(cad, str(f), tolerance=0.01, angular_tolerance=0.1)
        tris = read_triangles(f)[0]
        mesh = solid_from_triangles(tris.tolist())
        facets = kernel._facet_normals(mesh)
        self.assertEqual(len(facets), len(mesh.faces()))
        E = kernel._edges(mesh, facets)
        every = len(mesh.edges())
        self.assertLess(len(E), every / 2)                                 # no triangle edges on the flat and round faces
        # every drawn segment lies on a crease of the box or the hole (a box face border or a hole rim)
        mid = (E[:, :3] + E[:, 3:]) / 2
        on_border = (np.abs(np.abs(mid[:, 0]) - 10) < 1e-3) | (np.abs(np.abs(mid[:, 1]) - 10) < 1e-3)
        on_rim = np.abs(np.abs(mid[:, 2]) - 5) < 1e-3
        self.assertTrue(np.all(on_border | on_rim))

    def test_smooth_facets_shares_vertices(self):
        from form import kernel
        # a fan of 8 facets round a cone tip, plus a sharp 90 degree fold
        P = []
        for k in range(8):
            a0, a1 = 2 * np.pi * k / 8, 2 * np.pi * (k + 1) / 8
            P += [[0, 0, 1], [np.cos(a0), np.sin(a0), 0.8], [np.cos(a1), np.sin(a1), 0.8]]
        P = np.array(P, dtype=float)
        T = np.arange(len(P)).reshape(-1, 3)
        P2, T2 = kernel.smooth_facets(P, T)
        self.assertEqual(len(P2), 9)                                       # tip + 8 rim points, shared
        np.testing.assert_allclose(P2[T2], P[T], atol=1e-9)                # nothing moved
        fold = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 0, 0], [0, 0, -1.0]])
        P3, T3 = kernel.smooth_facets(fold, np.arange(6).reshape(-1, 3))
        self.assertEqual(len(P3), 6)                                       # a crease keeps its own vertices


if __name__ == "__main__":
    unittest.main()
