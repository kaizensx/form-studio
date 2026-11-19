"""Analysis on the model: maps, measuring, print orientations. Known shapes, real kernel.

The direct tests build small solids in this process and hand them to the kernel ops through the kernel's own model
cache; the studio tests run the worker, the pipeline, the CLI and MCP end to end.
"""
import asyncio
import base64
import io
import json
import math
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

TMP = tempfile.mkdtemp(prefix="form-analysis-")
ROOT = Path(__file__).resolve().parents[1]

from build123d import Align, Box, Cylinder, Face, Pos, Solid, Vector, Wire  # noqa: E402

from form import analysis as an, config, kernel  # noqa: E402
from form.recipes.base import Feature, Recipe  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from printing_cfg import with_printing  # noqa: E402

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Plain(Recipe):
    features = [Feature("body", "Body", "structure")]


def put(key, shape, tol=an.TOL):
    """A kernel model of a hand-built solid, placed where the kernel ops look for it."""
    faces = []
    for face in shape.faces():
        P, T = kernel._tessellate(face, tol)
        if not len(T):
            continue
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        faces.append({"feature": "body", "P": P, "T": T.astype(np.uint32), "face": face,
                      "area": float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)})
    bb = shape.bounding_box()
    model = {"recipe": Plain(), "values": {}, "shape": shape, "faces": faces, "by_feature": {"body": [f["face"] for f in faces]},
             "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]], "volume": float(shape.volume),
             "area": float(shape.area), "com": (0, 0, 0), "t_build": 0, "t_total": 0, "tol": tol}
    kernel._cache[(key, tol)] = model
    an._fields.pop((key, tol), None)
    return model


def arr(b64, dtype, cols):
    return np.frombuffer(base64.b64decode(b64), dtype=dtype).reshape(-1, cols)


def tray(wall):
    """An open box 40 × 30 × 20 with the given wall and a 3 mm floor."""
    return Box(40, 30, 20, align=A) - Pos(0, 0, 3) * Box(40 - 2 * wall, 30 - 2 * wall, 20, align=A)


def mesh_of(shape):
    return kernel._tessellate(shape, an.TOL)


class Numpy(unittest.TestCase):
    def test_orientation_ids_round_trip_and_match_the_named_ones(self):
        for name in an.NAMED:
            d = an.orientation_down(name)
            R = an.orientation_matrix(an.down_id(d))
            np.testing.assert_allclose(R @ d, [0, 0, -1], atol=1e-6)        # that direction ends up facing the plate
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)
        self.assertTrue(an.valid_orientation("down:0.7071,0,-0.7071"))
        for bad in ("down:0,0,0", "down:1,2", "sideways", None, "down:a,b,c"):
            self.assertFalse(an.valid_orientation(bad))
        self.assertEqual(an.orientation_label("on_back"), "On its back")
        self.assertIn("down", an.orientation_label("down:0,1,0"))
        q = an.quaternion(an.orientation_matrix("inverted"))
        self.assertAlmostEqual(sum(x * x for x in q), 1.0, places=9)

    def test_refine_keeps_the_surface_and_bounds_the_edges(self):
        P, T = mesh_of(Box(30, 20, 10, align=A))
        P2, T2, parent = an.refine(P, T, 2.0)
        area = lambda P, T: np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1).sum() / 2
        self.assertAlmostEqual(area(P2, T2), area(P, T), places=6)
        longest = max(np.linalg.norm(P2[T2[:, i]] - P2[T2[:, (i + 1) % 3]], axis=1).max() for i in range(3))
        self.assertLessEqual(longest, 2.0 + 1e-9)
        self.assertEqual(len(parent), len(T2))

    def test_section_area_of_a_box_and_the_neck_of_a_dumbbell(self):
        P, T = mesh_of(Box(30, 20, 10, align=A))
        prof = an.section_profile(P, T, "as_modelled", step=0.5)
        self.assertEqual(len(prof["z"]), 20)
        np.testing.assert_allclose(prof["area"], 600.0, atol=1e-6)
        self.assertIsNone(prof["neck"])                                  # a prism has no neck
        np.testing.assert_allclose(an.section_profile(P, T, "on_back", step=0.5)["area"], 300.0, atol=1e-6)   # 30 × 10
        bell = Box(20, 20, 10, align=A) + Pos(0, 0, 10) * Box(6, 6, 10, align=A) + Pos(0, 0, 20) * Box(20, 20, 10, align=A)
        P, T = mesh_of(bell)
        prof = an.section_profile(P, T, "as_modelled", step=0.2)
        nk = prof["neck"]
        self.assertAlmostEqual(nk["area_mm2"], 36.0, places=3)
        self.assertTrue(10 < nk["z_mm"] < 20)
        seg = an.slice_outline(P, T, "as_modelled", nk["z_mm"])
        self.assertAlmostEqual(float(np.linalg.norm(seg[:, :3] - seg[:, 3:], axis=1).sum()), 24.0, places=3)   # perimeter of 6 × 6
        pyramid_like = np.array([100.0, 60, 30, 10])
        self.assertIsNone(an.neck(np.arange(4.0), pyramid_like))         # only shrinks: a tip, not a neck

    def test_fit_circle(self):
        t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        pts = np.stack([3 + 2.5 * np.cos(t), -1 + 2.5 * np.sin(t), np.full(40, 7.0)], axis=1)
        c = an.fit_circle(pts)
        self.assertAlmostEqual(c["radius"], 2.5, places=9)
        np.testing.assert_allclose(c["center"], [3, -1, 7], atol=1e-9)
        self.assertLess(c["rms"], 1e-9)
        self.assertIsNone(an.fit_circle([[0, 0, 0], [1, 0, 0], [2, 0, 0]]))

    def test_distance(self):
        d = an.distance([0, 0, 0], [3, 4, 12])
        self.assertAlmostEqual(d["distance_mm"], 13.0)
        self.assertEqual((d["dx_mm"], d["dy_mm"], d["dz_mm"]), (3.0, 4.0, 12.0))
        self.assertAlmostEqual(an.distance([0, 0, 0], [3, 4, 12], "on_back")["layers_dz_mm"], 4.0)   # Y becomes up
        with self.assertRaises(ValueError):
            an.distance([0, 0], [1, 2, 3])

    def test_rest_directions_of_a_box_are_its_six_faces(self):
        P, T = mesh_of(Box(30, 20, 10, align=A))
        ds = an.rest_directions(P, T)
        self.assertEqual(len(ds), 6)
        for d in ds:
            self.assertAlmostEqual(float(np.abs(d).max()), 1.0, places=6)


class Thickness(unittest.TestCase):
    def test_the_map_finds_the_known_wall_and_agrees_with_the_check(self):
        m = put("tray2", tray(2.0))
        r = an.op_analysis("tray2", "x", {}, map="thickness", nozzle=0.4)
        self.assertEqual(r["evidence"], "computed")
        self.assertAlmostEqual(r["stats"]["min_mm"], 2.0, places=2)
        self.assertEqual(r["stats"]["under_two_perimeters_pct"], 0.0)
        thin, hist = kernel._thickness(m)                               # what the Thinnest-wall check reports
        self.assertAlmostEqual(thin["t"], r["stats"]["min_mm"], places=2)
        P, T = arr(r["positions"], np.float32, 3), arr(r["indices"], np.uint32, 3)
        vals, col = arr(r["values"], np.float32, 1)[:, 0], arr(r["colors"], np.uint8, 4)
        self.assertEqual(len(vals), len(P))
        self.assertEqual(len(col), len(P))
        self.assertLess(int(T.max()), len(P))
        outer = np.isclose(P[:, 0], 20.0) & (P[:, 2] > 6) & (P[:, 2] < 19) & (np.abs(P[:, 1]) < 10)   # the +X wall, away from floor, rim and corners
        self.assertGreater(outer.sum(), 10)
        np.testing.assert_allclose(vals[outer], 2.0, atol=0.01)
        self.assertNotIn(tuple(an.SIGNAL), {tuple(c[:3]) for c in col})
        lg = r["legend"]
        self.assertIn("0.8", lg["stops"][0]["label"])                   # under two perimeters of a 0.4 mm nozzle
        self.assertIn("Not a strength analysis", lg["not"])
        self.assertIn("mm", lg["unit"])

    def test_parts_that_touch_are_not_a_thin_wall(self):
        # a 5 mm plate with a 5 mm block resting on it: two parts, each 5 mm thick where they touch
        from build123d import Compound
        two = Compound([Box(40, 30, 5, align=A), Pos(0, 0, 5) * Box(20, 20, 5, align=A)])
        thin, _ = kernel._thickness(put("touching", two))
        self.assertGreater(thin["t"], 4.9)
        r = an.op_analysis("touching", "x", {}, map="thickness", nozzle=0.4)
        self.assertGreater(r["stats"]["min_mm"], 4.9)

    def test_a_sharp_edge_is_not_a_wall_but_a_thin_fin_is(self):
        # a wedge whose slanted side meets the floor at 45°: its edge tapers to nothing but has no wall
        wedge = Solid.extrude(Face(Wire.make_polygon([(0, 0, 0), (20, 0, 0), (20, 0, 20)], close=True)), Vector(0, 30, 0))
        thin, _ = kernel._thickness(put("wedge", wedge))
        self.assertGreater(thin["t"], 2.0)
        # a real 0.5 mm fin standing on a block still fails
        fin = Box(30, 30, 4, align=A) + Pos(0, 0, 4) * Box(0.5, 20, 10, align=A)
        thin, _ = kernel._thickness(put("fin", fin))
        self.assertAlmostEqual(thin["t"], 0.5, places=2)

    def test_a_wall_under_two_perimeters_is_signal_coloured(self):
        put("tray06", tray(0.6))
        r = an.op_analysis("tray06", "x", {}, map="thickness", nozzle=0.4)
        self.assertAlmostEqual(r["stats"]["min_mm"], 0.6, places=2)
        self.assertGreater(r["stats"]["under_two_perimeters_pct"], 20)
        col = arr(r["colors"], np.uint8, 4)
        self.assertIn(tuple(an.SIGNAL), {tuple(c[:3]) for c in col})
        self.assertEqual(r["markers"][0]["kind"], "thin")

    def test_small_features(self):
        plate = Box(40, 30, 4, align=A) - Pos(-10, 0, 0) * Cylinder(0.6, 4, align=A) - Pos(10, 0, 0) * Cylinder(2.5, 4, align=A)
        slotted = plate - Pos(0, 10, 0) * Box(20, 0.3, 4, align=A)       # a 0.3 mm slot
        put("feat", slotted)
        r = an.op_analysis("feat", "x", {}, map="features", nozzle=0.4)
        self.assertEqual(sorted(round(h["diameter_mm"], 3) for h in r["holes"]), [1.2, 5.0])
        self.assertEqual(r["stats"]["small_holes"], 1)                  # Ø1.2 is under 5 nozzle widths, Ø5 is not
        gaps = [m for m in r["markers"] if m["kind"] == "gap"]
        self.assertTrue(gaps)
        self.assertAlmostEqual(gaps[0]["value_mm"], 0.3, places=2)
        self.assertEqual(r["stats"]["thin_markers"], 0)
        put("clean", Box(40, 30, 4, align=A))
        self.assertEqual(an.op_analysis("clean", "x", {}, map="features")["markers"], [])


class Overhang(unittest.TestCase):
    def lean(self, deg):
        """A 10 mm thick slab, 20 deep, leaning so its underside is `deg` past vertical."""
        dx = 20 * math.tan(math.radians(deg))
        pts = [(0, 0, 0), (10, 0, 0), (10 + dx, 0, 20), (dx, 0, 20)]
        return Solid.extrude(Face(Wire.make_polygon([Vector(*p) for p in pts], close=True)), Vector(0, 20, 0))

    def test_angle_and_area_of_a_known_overhang(self):
        for deg, steep in ((30, False), (60, True)):
            m = put(f"lean{deg}", self.lean(deg))
            self.assertTrue(m["shape"].is_valid)
            r = an.op_analysis(f"lean{deg}", "x", {}, map="overhang", orientation="as_modelled")
            vals = arr(r["values"], np.float32, 1)[:, 0]
            P = arr(r["positions"], np.float32, 3)
            under = (P[:, 2] > 1) & (P[:, 2] < 19) & (np.abs(P[:, 1] - 10) < 8) & (P[:, 0] > 10 + P[:, 2] * math.tan(math.radians(deg)) - 0.01)
            self.assertGreater(under.sum(), 5)
            np.testing.assert_allclose(vals[under], deg, atol=0.05)     # the underside leans exactly that far past vertical
            slant = 20 / math.cos(math.radians(deg)) * 20                # the underside's area
            self.assertAlmostEqual(r["stats"]["steep_mm2"], slant if steep else 0.0, delta=0.01)
            self.assertAlmostEqual(r["stats"]["contact_mm2"], 200.0, delta=0.01)
            row = next(x for x in kernel._orientation_table(*kernel._mesh_arrays(m)) if x["id"] == "as_modelled")
            self.assertAlmostEqual(row["steep_mm2"], r["stats"]["steep_mm2"], places=1)        # the check's own number
            cls = np.frombuffer(base64.b64decode(r["classes"]), dtype=np.uint8)
            self.assertEqual(bool((cls == an.OH_STEEP).any()), steep)
            self.assertTrue((cls == an.OH_CONTACT).any())
            self.assertIn("Not a slice", r["legend"]["not"])

    def test_a_bridged_ceiling_is_its_own_class(self):
        arch = Box(30, 10, 20, align=A) - Box(20, 10, 12, align=A)
        put("arch", arch)
        r = an.op_analysis("arch", "x", {}, map="overhang")
        self.assertAlmostEqual(r["stats"]["ceiling_mm2"], 200.0, delta=0.01)
        self.assertAlmostEqual(r["stats"]["steep_mm2"], 0.0, delta=0.01)
        self.assertAlmostEqual(r["stats"]["support_mm3"], 200.0 * 12, delta=1)
        cls = np.frombuffer(base64.b64decode(r["classes"]), dtype=np.uint8)
        self.assertTrue((cls == an.OH_CEILING).any())


class Measure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plate = Box(40, 30, 4, align=A) - Pos(10, 5, 0) * Cylinder(2.5, 4, align=A)
        put("plate", cls.plate)

    def test_hole_diameter_is_exact_from_the_solid(self):
        pr = an.op_probe("plate", "x", {}, at=[12.5, 5, 2])
        c = pr["circle"]
        self.assertAlmostEqual(c["diameter_mm"], 5.0, places=6)
        self.assertTrue(c["hole"])
        self.assertIn("exact", c["method"])
        np.testing.assert_allclose(c["center"][:2], [10, 5], atol=1e-6)
        self.assertEqual(pr["face"]["type"], "cylinder")
        self.assertLess(pr["off_surface_mm"], 0.06)

    def test_rim_click_finds_the_circular_edge(self):
        pr = an.op_probe("plate", "x", {}, at=[12.6, 5, 4])              # on the top face, just outside the rim
        self.assertEqual(pr["face"]["type"], "plane")
        self.assertAlmostEqual(pr["circle"]["diameter_mm"], 5.0, places=6)
        self.assertAlmostEqual(pr["circle"]["edge_distance_mm"], 0.1, places=3)
        self.assertIn("circle centre", [s["kind"] for s in pr["snaps"]])

    def test_face_area_tilt_and_snaps(self):
        top = an.op_probe("plate", "x", {}, at=[-10, -5, 4])
        self.assertAlmostEqual(top["face"]["area_mm2"], 40 * 30 - math.pi * 2.5 ** 2, places=3)
        self.assertAlmostEqual(top["face"]["tilt_deg"], 0.0, places=3)
        side = an.op_probe("plate", "x", {}, at=[20, 0, 2])
        self.assertAlmostEqual(side["face"]["area_mm2"], 120.0, places=6)
        self.assertAlmostEqual(side["face"]["tilt_deg"], 90.0, places=3)
        lying = sorted(an.op_probe("plate", "x", {}, at=[20, 0, 2], orientation=o)["face"]["tilt_deg"] for o in ("on_left", "on_right"))
        self.assertEqual(lying, [0.0, 180.0])                            # laid on a side, that wall faces the bed or straight up
        corner = an.op_probe("plate", "x", {}, at=[19.8, 14.9, 4])
        self.assertEqual(corner["snaps"][0]["kind"], "vertex")
        np.testing.assert_allclose(corner["snaps"][0]["at"], [20, 15, 4], atol=1e-6)

    def test_a_circle_is_fitted_where_there_is_no_cad_solid(self):
        P, T = mesh_of(self.plate)
        loops = an._loops(kernel._mesh_edges(P, T))
        rim = min(loops, key=lambda lp: float(np.min(np.linalg.norm(lp - np.array([12.5, 5, 4]), axis=1))))
        c = an.fit_circle(rim)
        self.assertAlmostEqual(2 * c["radius"], 5.0, delta=0.02)        # fitted to the tessellation: close, not exact
        self.assertLess(c["rms"], 0.02)


class Orient(unittest.TestCase):
    def test_ranking_shows_its_numbers_and_prefers_the_obvious_way(self):
        tee = Box(40, 40, 4, align=A) + Pos(0, 0, 4) * Box(6, 6, 30, align=A)        # a post on a plate
        put("tee", tee)
        r = an.op_orient("tee", "x", {}, envelope=(180, 180, 180), margin=2.0, current="as_modelled")
        cands = r["candidates"]
        self.assertEqual(cands[0]["id"], "as_modelled")
        self.assertTrue(cands[0]["current"])
        self.assertEqual([c["rank"] for c in cands], list(range(1, len(cands) + 1)))
        self.assertTrue({"as_modelled", "inverted", "on_back"} <= {c["id"] for c in cands})
        for c in cands:
            self.assertAlmostEqual(sum(c["terms"].values()), c["score"], places=3)
            self.assertEqual(set(c["terms"]), set(an.ORIENT_WEIGHTS))
            self.assertEqual(len(c["quaternion"]), 4)
        self.assertAlmostEqual(sum(an.ORIENT_WEIGHTS.values()), 1.0)
        base, flipped = cands[0], next(c for c in cands if c["id"] == "inverted")
        self.assertAlmostEqual(base["contact_mm2"], 1600.0, delta=0.01)
        self.assertAlmostEqual(base["support_mm3"], 0.0, delta=0.01)
        self.assertAlmostEqual(flipped["contact_mm2"], 36.0, delta=0.01)
        self.assertAlmostEqual(flipped["support_mm3"], (1600 - 36) * 30, delta=1)     # the plate's underside, 30 mm up
        self.assertIsNone(flipped["min_layer_mm2"])                      # standing on the post: a narrow base, not a neck between two wider regions
        self.assertIn("not a print-success prediction", r["not"])
        self.assertIn("0.35·support", r["formula"])

    def test_hull_faces_become_candidates_and_export_the_same_way(self):
        wedge = Solid.extrude(Face(Wire.make_polygon([Vector(0, 0, 0), Vector(30, 0, 0), Vector(0, 0, 20)], close=True)), Vector(0, 15, 0))
        m = put("wedge", wedge)
        r = an.op_orient("wedge", "x", {})
        slope = [c for c in r["candidates"] if not c["named"]]
        self.assertEqual(len(slope), 1)                                  # the sloped face; the other four are axis faces
        c = slope[0]
        self.assertAlmostEqual(c["contact_mm2"], math.hypot(30, 20) * 15, delta=0.01)
        self.assertEqual(c["rests_on"], "body")
        bb = kernel._oriented(m["shape"], c["id"]).bounding_box()        # what the STL export does with that id
        self.assertAlmostEqual(bb.size.Z, c["height_mm"], places=4)
        self.assertAlmostEqual(bb.min.Z, 0.0, places=6)
        table = kernel._orientation_table(*kernel._mesh_arrays(m), extra=(c["id"],))
        self.assertEqual(len(table), 7)
        self.assertAlmostEqual(table[-1]["contact_mm2"], c["contact_mm2"], places=3)
        self.assertEqual(len(kernel._orientation_table(*kernel._mesh_arrays(m))), 6)


class Pictures(unittest.TestCase):
    def test_every_map_renders_to_a_png_and_a_digest(self):
        put("tray2", tray(2.0))
        for name in an.MAPS:
            r = an.op_analysis("tray2", "x", {}, map=name)
            png = an.render_map_png(r, "Tray")
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            d = an.digest(r)
            self.assertNotIn("positions", d)
            self.assertEqual(d["legend"]["evidence"], "computed")
            self.assertTrue(d["legend"]["not"])
            json.dumps(d)
        with self.assertRaises(ValueError):
            an.op_analysis("tray2", "x", {}, map="stress")


class Viewport(unittest.TestCase):
    def test_mesh_geometry_takes_colours_and_reads_values_back(self):
        try:
            from PySide6.QtGui import QVector3D
            from form.app.geometry import MeshGeometry
        except ImportError:
            self.skipTest("PySide6 not installed")
        put("tray2", tray(2.0))
        r = an.op_analysis("tray2", "x", {}, map="thickness")
        g = MeshGeometry()
        g.source = {k: r[k] for k in ("positions", "indices", "colors", "values")}
        self.assertEqual(g.stride(), 40)                                 # position, normal, colour
        self.assertAlmostEqual(g.valueAt(QVector3D(20, 3.3, 11.7)), 2.0, delta=0.01)   # the middle of the +X wall
        plain = MeshGeometry()
        plain.positions, plain.indices = r["positions"], r["indices"]
        self.assertEqual(plain.stride(), 24)
        self.assertTrue(math.isnan(plain.valueAt(QVector3D(0, 0, 0))))


class StudioAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(with_printing(config.load()))
        p = cls.st.create("Analysis hook", "hook")
        cls.pid = p["id"]
        cls.st.run_sync(cls.pid, ["geometry", "exports", "checks"])

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def load(self):
        return self.st.load(self.pid)

    def test_maps_are_cached_artifacts_and_agree_with_the_checks(self):
        p = self.load()
        r = an.run_map(self.st, p, "thickness")
        files = list((self.st.dir(self.pid) / "artifacts" / "analysis").glob("thickness-*.json"))
        self.assertEqual(len(files), 1)
        again = an.run_map(self.st, p, "thickness")
        self.assertEqual(again["stats"], r["stats"])
        checks = {c["id"]: c for c in self.st.state(self.pid)["checks"]["checks"]}
        wall = float(checks["wall"]["value"].split()[0])
        self.assertLessEqual(r["stats"]["min_mm"], wall + 0.05)          # denser sampling can only find the same wall or a thinner one
        oh = an.run_map(self.st, p, "overhang")
        self.assertAlmostEqual(oh["stats"]["steep_mm2"], float(checks["overhang"]["value"].split()[0]), delta=0.6)
        self.assertEqual(oh["rev"], p["head"])
        with self.assertRaises(StudioError):
            an.run_map(self.st, p, "stress")

    def test_measure_and_probe(self):
        p = self.load()
        bb = self.st.view(p)["bbox"]
        m = an.measure(self.st, p, bb[0], bb[1])
        self.assertAlmostEqual(m["distance_mm"], math.dist(bb[0], bb[1]), places=6)
        self.assertEqual(m["evidence"], "computed")
        self.assertIn("off_surface_mm", m["from_on"])
        with self.assertRaises(StudioError):
            an.measure(self.st, p, [0, 0], [1, 1, 1])
        self.assertIn("face", an.probe(self.st, p, bb[0]))

    def test_orientation_finder_applies_through_settings_and_the_pipeline(self):
        p = self.load()
        r = an.orientations(self.st, p)
        self.assertGreaterEqual(len(r["candidates"]), 6)
        self.assertEqual(sum(c["current"] for c in r["candidates"]), 1)
        custom = next((c for c in r["candidates"] if not c["named"]), None)
        pick = custom["id"] if custom else "down:0.6,0,-0.8"
        with self.assertRaises(StudioError):
            self.st.settings(p, {"orientation": "down:0,0,0"})
        self.st.settings(p, {"orientation": pick})
        job = self.st.run_sync(self.pid, ["geometry", "exports", "checks"])
        self.assertEqual(job["state"], "done", job)
        ch = self.st.state(self.pid)["checks"]
        self.assertEqual(ch["orientation_table"][-1]["id"], pick)         # the custom orientation has its own row
        self.assertEqual(len(ch["orientation_table"]), 7)
        self.assertEqual(ch["context"]["orientation"], pick)
        self.assertTrue(any(c["current"] for c in an.orientations(self.st, self.load())["candidates"]))
        self.assertIn(pick, self.load()["decisions"][-1]["text"] + pick)
        self.st.settings(self.load(), {"orientation": "as_modelled"})

    def test_cli(self):
        from form.__main__ import main
        png = Path(TMP) / "map.png"

        def run(*argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(list(argv))
            return rc, json.loads(buf.getvalue())
        rc, out = run("analyze", self.pid, "--map", "section", "--png", str(png))
        self.assertEqual(rc, 0)
        self.assertEqual(out["map"], "section")
        self.assertIn("not a strength analysis", out["legend"]["not"])
        self.assertTrue(png.read_bytes().startswith(b"\x89PNG"))
        rc, out = run("measure", self.pid, "--from", "0,0,0", "--to", "3,4,0")
        self.assertAlmostEqual(out["distance_mm"], 5.0)
        rc, out = run("measure", self.pid, "--at", "0,0,0")
        self.assertIn("face", out)
        rc, out = run("orient", self.pid)
        self.assertEqual(out["candidates"][0]["rank"], 1)
        self.assertIn("formula", out)
        rc, out = run("measure", self.pid)
        self.assertEqual(rc, 2)


class MCPAnalysis(unittest.TestCase):
    def test_tools(self):
        asyncio.run(self._session())

    async def _session(self):
        from mcp import Client, StdioServerParameters
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "PYTHONPATH": str(ROOT)}
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env, cwd=str(ROOT))
            async with Client(params) as c:
                tools = {t.name for t in (await c.list_tools()).tools}
                self.assertTrue({"analyze", "measure", "suggest_orientation"} <= tools)
                made = await c.call_tool("create_project", {"name": "Hook", "recipe": "hook", "run": True})
                sc = made.structured_content
                pid = (sc.get("result", sc) if isinstance(sc, dict) else json.loads(made.content[0].text))["project"]
                res = await c.call_tool("analyze", {"project": pid, "map": "overhang"})
                self.assertIn("image", [x.type for x in res.content])
                stats = json.loads(next(x.text for x in res.content if x.type == "text"))
                self.assertEqual(stats["evidence"], "computed")
                self.assertIn("steep_mm2", stats["stats"])
                res = await c.call_tool("measure", {"project": pid, "from_point": [0, 0, 0], "to_point": [0, 0, 10]})
                sc = res.structured_content or json.loads(next(x.text for x in res.content if x.type == "text"))
                self.assertAlmostEqual((sc.get("result", sc))["distance_mm"], 10.0)
                res = await c.call_tool("suggest_orientation", {"project": pid})
                self.assertIn("image", [x.type for x in res.content])
                ranked = json.loads(next(x.text for x in res.content if x.type == "text"))
                self.assertEqual(ranked["candidates"][0]["rank"], 1)
                bad = await c.call_tool("analyze", {"project": pid, "map": "stress"})
                self.assertTrue(bad.is_error)


if __name__ == "__main__":
    unittest.main()
