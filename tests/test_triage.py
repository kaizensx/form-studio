"""Triage, safe mesh repair, the working copy of a heavy mesh and the organic route of "make editable".

Every mesh here is made in the test (a box, a sculpted blob, a ring, their broken versions): nothing is downloaded and
no file a person gave is used. The numpy classes need no kernel; `Bodies` builds solids in-process and `Routes` goes
through the Studio and its kernel worker.
"""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from form import meshbody as mb
from form import meshrepair, triage
from form.recon import mesh as mm

TMP = tempfile.mkdtemp(prefix="form-triage-")


def box(size=(80.0, 40.0, 20.0), at=(0.0, 0.0, 0.0), n: int = 6):
    """A closed box as (V, F), every face an n x n grid of quads split in two, outward."""
    sx, sy, sz = size
    g = np.linspace(0.0, 1.0, n + 1)
    faces = []
    for axis in range(3):
        for side in (0.0, 1.0):
            u, v = np.meshgrid(g, g, indexing="ij")
            P = np.zeros((n + 1, n + 1, 3))
            P[..., axis] = side
            P[..., (axis + 1) % 3] = u
            P[..., (axis + 2) % 3] = v
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
            a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
            T = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
            if side == 0.0:
                T = T[:, ::-1]
            faces.append(P.reshape(-1, 3)[T])
    T = np.concatenate(faces) * np.array([sx, sy, sz]) + np.array(at)
    V, F, _ = mm.weld(T, 1e-9)
    return V, F


def blob(n: int = 24):
    return mb.weld(mb.fixture_bust(n))


def ring(R: float = 40.0, r: float = 12.0, nu: int = 96, nv: int = 32, noise: float = 0.05):
    """A torus with a little scan noise: organic by its surface, and it has a handle (genus 1)."""
    u = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    v = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    U, W = np.meshgrid(u, v, indexing="ij")
    P = np.stack([(R + r * np.cos(W)) * np.cos(U), (R + r * np.cos(W)) * np.sin(U), r * np.sin(W)], -1).reshape(-1, 3)
    idx = np.arange(nu * nv).reshape(nu, nv)
    a, b = idx, np.roll(idx, -1, axis=0)
    c, d = np.roll(b, -1, axis=1), np.roll(idx, -1, axis=1)
    F = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
    P = P + np.random.default_rng(1).normal(0, noise, P.shape)
    return P, F


def save(name: str, V, F) -> Path:
    p = Path(TMP) / name
    mm.write_stl(p, V, F)
    return p


def broken(V, F):
    """Two fin triangles hanging off edges, one triangle missing, four turned the wrong way."""
    V2 = np.vstack([V, V[F[10]].mean(0) + [0, 0, 3.0], V[F[300]].mean(0) + [0, 2.0, 0]])
    F2 = np.vstack([F, [F[10, 0], F[10, 1], len(V)], [F[300, 1], F[300, 2], len(V) + 1]])
    F2 = np.delete(F2, [700], axis=0)
    F2[900:904] = F2[900:904][:, ::-1]
    return V2, F2


class Repair(unittest.TestCase):
    def test_fins_a_missing_triangle_and_flipped_triangles_are_repaired_and_listed(self):
        V, F = blob()
        V2, F2 = broken(V, F)
        t0 = mm.topology(V2, F2)
        self.assertFalse(t0["closed"])
        self.assertGreater(t0["non_manifold_edges"], 0)
        W, G, repairs, top = meshrepair.repair(V2, F2)
        self.assertTrue(top["closed"], top)
        self.assertEqual(top["flipped_edges"], 0)
        self.assertEqual(len(G), len(F))
        names = [r["repair"] for r in repairs]
        self.assertIn("removed fin triangles", names)
        self.assertTrue(any("turned" in n for n in names), names)
        self.assertTrue(any("filled" in n or "missing" in str(r.get("method")) for n, r in zip(names, repairs)), repairs)
        self.assertEqual(next(r for r in repairs if r["repair"] == "removed fin triangles")["count"], 2)
        self.assertAlmostEqual(top["volume_mm3"], mm.topology(V, F)["volume_mm3"], delta=1e-6 * abs(top["volume_mm3"]))
        self.assertEqual(top["before_repair"]["non_manifold_edges"], t0["non_manifold_edges"])

    def test_vertices_are_never_moved(self):
        V, F = blob()
        V2, F2 = broken(V, F)
        W, _G, _r, _t = meshrepair.repair(V2, F2)
        have = {tuple(np.round(p, 9)) for p in V2}
        self.assertTrue(all(tuple(np.round(p, 9)) in have for p in W))

    def test_a_large_opening_that_is_not_flat_is_left_open_and_said(self):
        V, F = blob()
        keep = V[F].mean(1)[:, 0] < 0.4 * V[:, 0].max() + 6 * np.sin(V[F].mean(1)[:, 1] / 9.0)
        W, G, repairs, top = meshrepair.repair(V, F[keep], cap_planar=True)
        self.assertFalse(top["closed"])
        self.assertEqual(len(top["large_holes"]), 1)
        self.assertIn("hole left open (large)", [r["repair"] for r in repairs])

    def test_a_flat_opening_of_any_size_is_capped_when_asked(self):
        V, F = box(n=8)
        open_top = F[~np.all(np.isclose(V[F][:, :, 2], 20.0), axis=1)]
        _W, _G, repairs, top = meshrepair.repair(V, open_top)                 # half the part across: not guessed
        self.assertFalse(top["closed"])
        W, G, repairs, top = meshrepair.repair(V, open_top, cap_planar=True)
        self.assertTrue(top["closed"], repairs)
        self.assertIn("capped a flat opening", [r["repair"] for r in repairs])
        self.assertAlmostEqual(top["volume_mm3"], 80 * 40 * 20, delta=1e-6)

    def test_debris_goes_only_when_asked_and_is_counted(self):
        V, F = box()
        v2, f2 = box((0.5, 0.5, 0.5), at=(200, 0, 0), n=1)
        V3, F3 = np.vstack([V, v2]), np.vstack([F, f2 + len(V)])
        _W, G, repairs, top = meshrepair.repair(V3, F3)
        self.assertEqual(top["pieces"], 2)
        _W, G, repairs, top = meshrepair.repair(V3, F3, drop_debris=True)
        self.assertEqual(top["pieces"], 1)
        self.assertEqual(next(r for r in repairs if r["repair"] == "removed loose debris")["triangles"], len(f2))

    def test_what_is_open_is_never_said_as_zero_boundaries(self):
        V, F = blob()
        V2, F2 = broken(V, F)
        t = mm.topology(V2, F2)
        said = meshrepair.open_text(t)
        self.assertNotIn("0 open", said)
        self.assertIn("non-manifold", said)
        self.assertIn("open edge", said)


@unittest.skipUnless(meshrepair.has_manifold(), "manifold3d is not installed")
class WorkingCopy(unittest.TestCase):
    def test_a_heavy_mesh_gets_a_closed_lighter_copy_with_a_measured_distance(self):
        V, F = mb.weld(mb.fixture_bust(60))                                   # 43,200 triangles
        W, G, rec = meshrepair.working_copy(V, F, target=8000)
        self.assertTrue(rec["simplified"])
        self.assertLessEqual(len(G), 8000)
        self.assertGreater(len(G), 2000)
        self.assertTrue(mm.topology(W, G)["closed"])
        d = rec["deviation"]
        self.assertGreater(d["max_mm"], 0.0)                                  # measured, and not zero by construction
        self.assertGreater(d["copy_to_original_max_mm"], 0.0)
        self.assertLess(d["max_mm"], 1.5)                                     # a 140 mm part
        self.assertEqual(rec["triangles_in"], len(F))

    def test_a_light_mesh_is_returned_as_it_is(self):
        V, F = blob()
        W, G, rec = meshrepair.working_copy(V, F, target=len(F) + 1)
        self.assertFalse(rec["simplified"])
        self.assertIs(W, V)


class Classify(unittest.TestCase):
    def test_a_box_is_mechanical_and_a_sculpt_is_organic_at_any_density(self):
        self.assertGreaterEqual(triage.mechanical_share(*box())["mechanical_pct"], 90)
        for n in (16, 48):                                                    # 3,072 and 27,648 triangles
            s = triage.mechanical_share(*blob(n))
            self.assertLess(s["mechanical_pct"], triage.ORGANIC_PCT, (n, s))

    def test_a_noisy_scan_of_a_box_is_still_mechanical(self):
        V, F = box(n=40)
        V = V + np.random.default_rng(0).normal(0, 0.02, V.shape)
        s = triage.mechanical_share(V, F)
        self.assertLess(s["flat_pct"], 50)                                    # nothing is exactly flat any more
        self.assertGreaterEqual(s["mechanical_pct"], triage.MECHANICAL_PCT, s)

    def test_units_that_make_no_sense_in_millimetres_are_flagged(self):
        self.assertTrue(triage.units_guess([80, 40, 20])["plausible"])
        g = triage.units_guess([0.08, 0.04, 0.02])
        self.assertFalse(g["plausible"])
        self.assertEqual(g["likely"], "metres")
        self.assertTrue(triage.units_guess([0.08, 0.04, 0.02], "millimeter")["plausible"])    # a 3MF says its unit


class Triage(unittest.TestCase):
    def route(self, name, V, F):
        return triage.triage(str(save(name, V, F)))

    def test_mechanical_part_goes_parametric_without_a_question(self):
        t = self.route("box.stl", *box())
        self.assertEqual((t["input"]["kind"], t["class"], t["route"]), ("mesh", "mechanical", "parametric"))
        self.assertIsNone(t["ask"])
        self.assertTrue(t["steps"][0].startswith("reconstruct("))

    def test_smooth_closed_sculpt_goes_to_a_surface_body(self):
        t = self.route("blob.stl", *blob())
        self.assertEqual((t["class"], t["route"]), ("organic", "surface_body"))
        self.assertEqual(t["facts"]["genus"], 0)
        self.assertIn("mesh_body", t["alternates"])
        self.assertTrue(any("Dimensions" in c for c in t["cannot"]))

    def test_sculpt_with_a_handle_goes_to_a_mesh_body_and_says_why(self):
        t = self.route("ring.stl", *ring())
        self.assertEqual((t["class"], t["route"]), ("organic", "mesh_body"))
        self.assertEqual(t["facts"]["genus"], 1)
        self.assertIn("genus 1", t["why"])
        self.assertTrue(any("STEP" in c for c in t["cannot"]))

    def test_broken_mesh_is_repaired_in_the_assessment_and_keeps_its_route(self):
        V, F = blob()
        t = self.route("blob_broken.stl", *broken(V, F))
        f = t["facts"]
        self.assertFalse(f["as_given"]["closed"])
        self.assertGreater(f["as_given"]["non_manifold_edges"], 0)
        self.assertTrue(f["after_repair"]["closed"])
        self.assertEqual(t["route"], "surface_body")
        self.assertEqual(t["prepare"][0]["step"], "repair")

    def test_open_surface_is_reference_only_and_names_the_next_call(self):
        V, F = blob()
        keep = V[F].mean(1)[:, 0] < 0.4 * V[:, 0].max() + 6 * np.sin(V[F].mean(1)[:, 1] / 9.0)
        t = self.route("blob_open.stl", V, F[keep])
        self.assertEqual(t["route"], "reference_only")
        self.assertIn("does not close", t["why"])
        self.assertTrue(any("import_reference" in s for s in t["steps"]))
        self.assertNotIn("0 open", t["why"])

    def test_two_bodies_in_one_file_are_an_assembly(self):
        V, F = box()
        v2, f2 = box((20, 20, 30), at=(120, 0, 0))
        t = self.route("two.stl", np.vstack([V, v2]), np.vstack([F, f2 + len(V)]))
        self.assertEqual(t["route"], "assembly")
        self.assertEqual(t["facts"]["bodies"], 2)

    def test_a_part_in_metres_asks_one_question_about_units(self):
        V, F = box()
        t = self.route("box_m.stl", V * 0.001, F)
        self.assertEqual(t["route"], "parametric")
        self.assertIsNotNone(t["ask"])
        self.assertIn("metres", t["ask"]["question"])
        self.assertLessEqual(len(t["ask"]["choices"]), 3)

    def test_heavy_mechanical_mesh_is_prepared_and_heavy_sculpt_gets_a_working_copy(self):
        V, F = box(n=240)                                                     # 691,200 triangles
        t = self.route("box_heavy.stl", V, F)
        self.assertEqual(t["route"], "parametric")
        self.assertIn("working_copy", [p["step"] for p in t["prepare"]])
        self.assertGreater(t["facts"]["triangles"], triage.PARAMETRIC_TRIANGLES)
        V, F = mb.weld(mb.fixture_bust(110))                                  # 145,200 triangles
        t = self.route("blob_heavy.stl", V, F)
        self.assertEqual(t["class"], "organic")
        self.assertIn("working_copy", [p["step"] for p in t["prepare"]])

    def test_step_photo_pdf_link_and_words_each_get_their_route(self):
        step = Path(TMP) / "part.step"
        step.write_text("ISO-10303-21;\nDATA;\n#1=MANIFOLD_SOLID_BREP('a',#2);\n#3=ADVANCED_FACE('',(#4),#5,.T.);\n"
                        "#9=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));\nENDSEC;\n", encoding="utf-8")
        t = triage.triage(str(step))
        self.assertEqual((t["input"]["kind"], t["route"]), ("cad", "cad_reference"))
        self.assertEqual((t["facts"]["solids"], t["facts"]["faces"], t["facts"]["units"]["units"]), (1, 1, "mm"))
        for name, kind, route in (("p.jpg", "photo", "photo_reference"), ("d.pdf", "document", "document")):
            f = Path(TMP) / name
            f.write_bytes(b"x")
            t = triage.triage(str(f))
            self.assertEqual((t["input"]["kind"], t["route"]), (kind, route))
        self.assertIsNotNone(triage.triage(str(Path(TMP) / "p.jpg"))["ask"])   # a photo has no scale of its own
        self.assertEqual(triage.triage("https://example.com/part.stl")["route"], "link")
        self.assertEqual(triage.triage("a hook for my desk")["route"], "concepts")
        self.assertEqual(triage.triage("a bracket 80 mm wide with two M6 holes 40 mm apart")["route"], "describe")
        self.assertEqual(triage.triage(str(Path(TMP) / "missing.stl"))["route"], "unknown")
        bad = Path(TMP) / "bad.stl"
        bad.write_bytes(b"not a mesh")
        t = triage.triage(str(bad))
        self.assertEqual(t["route"], "unknown")
        self.assertIn("could not be read", t["why"])


class Errors(unittest.TestCase):
    """A tool error is short, and the same refusal twice says so (form/mcp_server.py)."""

    def test_long_message_is_cut_and_a_repeat_is_named(self):
        from form import mcp_server
        from form.studio import StudioError
        mcp_server.S.pop("refusals", None)
        long = "API MeshBody(V, F) | " + "x" * 9000
        e1 = str(mcp_server._fail(StudioError(long, "Fix the source.")))
        self.assertLess(len(e1), mcp_server.MESSAGE_MAX + 600)
        self.assertIn("more characters cut", e1)
        self.assertIn("not a way to print", e1)
        self.assertNotIn("same refusal", e1)
        e2 = str(mcp_server._fail(StudioError(long, "Fix the source.")))
        self.assertIn("same refusal as before", e2)
        e3 = str(mcp_server._fail(StudioError("Another problem.", "Do X.")))
        self.assertNotIn("same refusal", e3)
        self.assertIn("Hint: Do X.", e3)


@unittest.skipUnless(meshrepair.has_manifold(), "manifold3d is not installed")
class Bodies(unittest.TestCase):
    """Mesh bodies and the direct mesh-to-solid builder (OCCT, in this process)."""

    def test_a_closed_mesh_becomes_a_solid_with_its_volume_without_sewing(self):
        from form.recipes.meshsolid import solid_from_mesh, solid_from_triangles
        V, F = blob()
        s = solid_from_mesh(V, F)
        vol = mm.topology(V, F)["volume_mm3"]
        self.assertEqual(len(s.faces()), len(F))
        self.assertAlmostEqual(s.volume, vol, delta=1e-6 * vol)
        self.assertTrue(s.is_valid)
        self.assertAlmostEqual(solid_from_triangles(V[F].tolist()).volume, vol, delta=1e-6 * vol)
        with self.assertRaises(ValueError):
            solid_from_mesh(V, F[:-5])                                        # open: the caller sews instead

    def test_load_repairs_a_file_and_the_body_takes_exact_cuts(self):
        from build123d import Cylinder, Pos
        V, F = blob()
        path = save("load_broken.stl", *broken(V, F))
        body = mb.MeshBody.load(str(path))
        self.assertEqual(body.source["file"], "load_broken.stl")
        self.assertIn("removed fin triangles", [r["repair"] for r in body.source["repairs"]])
        v0 = body.volume()
        (lo, hi) = body.bounds()
        body.trim((0, 0, lo[2] + 10.0), (0, 0, 1), "flat base")
        self.assertLess(body.volume(), v0)
        self.assertAlmostEqual(body.bounds()[0][2], lo[2] + 10.0, places=3)
        v1 = body.volume()
        body.cut(Pos(0, 0, 0) * Cylinder(4, 400), "pin hole")
        self.assertLess(body.volume(), v1)
        v2 = body.volume()
        body.scale(0.5, about=(0, 0, lo[2] + 10.0))
        self.assertAlmostEqual(body.volume(), v2 / 8, delta=1e-3 * v2)
        self.assertAlmostEqual(body.bounds()[0][2], lo[2] + 10.0, places=3)
        self.assertEqual(body.features, ["flat base", "pin hole"])
        s = body.solid()
        self.assertAlmostEqual(s.volume, body.volume(), delta=1e-4 * body.volume())
        with self.assertRaises(ValueError) as c:
            mb.MeshBody.load("nothing-here.stl")
        self.assertIn("absolute path", str(c.exception))

    def test_load_refuses_a_surface_that_does_not_close_and_says_what_is_open(self):
        V, F = blob()
        keep = V[F].mean(1)[:, 0] < 0.4 * V[:, 0].max() + 6 * np.sin(V[F].mean(1)[:, 1] / 9.0)
        with self.assertRaises(ValueError) as c:
            mb.MeshBody.load(str(save("load_open.stl", V, F[keep])))
        self.assertIn("open edge", str(c.exception))
        self.assertIn("reference", str(c.exception))


@unittest.skipUnless(meshrepair.has_manifold(), "manifold3d is not installed")
class Routes(unittest.TestCase):
    """reconstruct takes the route itself: through the Studio and its kernel worker."""

    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = str(Path(TMP) / "data")
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_a_broken_sculpt_with_a_handle_becomes_a_mesh_body_design_that_rebuilds(self):
        V, F = ring()
        V2, F2 = broken(V, F)
        out = self.st.reconstruct(save("ring_broken.stl", V2, F2))
        s = out["summary"]
        self.assertEqual((out["triage"]["class"], out["triage"]["taken"], s["route"]), ("organic", "mesh_body", "mesh_body"))
        self.assertIn("removed fin triangles", [r["repair"] for r in s["repairs"]])
        self.assertEqual(s["triangles"], len(F))
        self.assertEqual(s["hausdorff_mm"], 0.0)                              # the body is the repaired mesh itself
        self.assertIn("Mesh body", s["headline"])
        p = self.st.load(out["project"])
        self.assertEqual(p["reconstruction"]["summary"]["tier"], mb.TIER_MESH)
        names = {r["file"] for r in self.st.references(p)}
        self.assertIn("ring_broken.stl", names)                               # the file itself, to compare with
        self.assertIn("ring_broken_body.stl", names)
        v0 = self.st.view(p)["volume_mm3"]
        self.st.commit(p, {"scale_pct": 50, "base_cut": 3})                  # the two parameters work
        p = self.st.load(out["project"])
        self.assertEqual(p["head"], 2)
        self.assertLess(self.st.view(p)["volume_mm3"], v0 / 7.5)

    def test_a_smooth_sculpt_becomes_a_surface_body_within_the_accepted_distance(self):
        out = self.st.reconstruct(save("blob_route.stl", *blob(40)))            # fine enough that its facets are not the error
        s = out["summary"]
        self.assertEqual(s["route"], "surface_body")
        self.assertTrue(s["step"])
        self.assertLessEqual(s["hausdorff_mm"], s["surface"]["accept_mm"])
        self.assertGreater(s["hausdorff_mm"], 0.0)
        self.assertEqual(s["tier"], mb.TIER_SURFACE)
        # the design builds the very solid that distance was measured on (same cage, one face per quad)
        p = self.st.load(out["project"])
        self.assertAlmostEqual(self.st.view(p)["volume_mm3"], s["volume_mm3"], delta=1e-4 * s["volume_mm3"])

    def test_an_open_surface_is_refused_once_with_the_next_call(self):
        from form.studio import StudioError
        V, F = blob()
        keep = V[F].mean(1)[:, 0] < 0.4 * V[:, 0].max() + 6 * np.sin(V[F].mean(1)[:, 1] / 9.0)
        with self.assertRaises(StudioError) as c:
            self.st.reconstruct(save("open_route.stl", V, F[keep]))
        self.assertIn("does not close", str(c.exception))
        self.assertIn("import_reference", c.exception.hint)
        self.assertIn("Do not call reconstruct again", c.exception.hint)
        self.assertEqual(c.exception.extra["next"], "reference_only")

    def test_units_that_make_no_sense_are_asked_about_before_anything_is_built(self):
        from form.studio import StudioError
        V, F = box()
        src = save("box_metres.stl", V * 0.001, F)
        before = len(self.st.list())
        with self.assertRaises(StudioError) as c:
            self.st.reconstruct(src)
        self.assertIn("metres", str(c.exception))
        self.assertEqual(c.exception.extra["next"], "ask_units")
        self.assertIn('units="m"', c.exception.hint)
        self.assertEqual(len(self.st.list()), before)                         # nothing was made on a guess
        with self.assertRaises(StudioError):
            self.st.reconstruct(src, units="furlongs")

    def test_a_heavy_reference_mesh_is_drawn_from_a_lighter_copy_not_refused(self):
        from form import kernel
        V, F = mb.weld(mb.fixture_bust(190))                                  # 433,200 triangles: above the old limit
        src = save("heavy_ref.stl", V, F)
        info = kernel.op_reference(str(src), ".stl", str(Path(TMP) / "heavy.view.json"))
        self.assertEqual(info["triangles_in_file"], len(F))
        self.assertLess(info["triangles"], kernel.DRAW_TRIANGLES)
        self.assertIn(f"{len(F):,}", info["drawn"]["note"])


if __name__ == "__main__":
    unittest.main()
